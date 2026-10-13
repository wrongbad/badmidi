"""Standard MIDI File (format 1) writer. No dependencies.

Playback decisions (velocities, tempo changes, pedal) come from perform.py.
"""
from __future__ import annotations

from fractions import Fraction

from . import perform
from .score import Score

PPQ = 960  # ticks per quarter note; divisible by 3 and 5, so triplets and quintuplets are exact


def _vlq(n: int) -> bytes:
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    return bytes(reversed(out))


def _meta(kind: int, data: bytes) -> bytes:
    return bytes([0xFF, kind]) + _vlq(len(data)) + data


def _track(events: list[tuple[int, int, bytes]]) -> bytes:
    """events: (tick, order-within-tick, message). Lower order sorts first:
    controller and note-off messages go before note-ons at the same tick."""
    body, last = bytearray(), 0
    for tick, _, msg in sorted(events, key=lambda e: (e[0], e[1])):
        body += _vlq(tick - last) + msg
        last = tick
    body += _vlq(0) + _meta(0x2F, b"")
    return b"MTrk" + len(body).to_bytes(4, "big") + bytes(body)


def _time_signature(m) -> bytes | None:
    """A time-signature meta event; a free bar gets the plain signature of its
    length (11 quarters -> 11/4) if it has one."""
    num, den = m.num, m.den
    if m.free is not None:
        den = next((d for d in (4, 8, 16, 32) if (m.free * d / 4).denominator == 1), None)
        if den is None or m.free * den / 4 > 255:
            return None
        num = int(m.free * den / 4)
    return _meta(0x58, bytes([num, den.bit_length() - 1, 24, 8]))


def midi_bytes(score: Score) -> bytes:
    conductor = [
        (0, 0, _meta(0x03, (score.title or "badmidi").encode())),
        (0, 0, _meta(0x59, bytes([score.key.signature & 0xFF, 1 if score.key.minor else 0]))),
    ]
    for bar, m in score.meter_changes(score.bars):
        sig = _time_signature(m)
        if sig:
            conductor.append((round(score.bar_start(bar) * PPQ), 0, sig))
    for t, bpm in perform.tempo_map(score):
        conductor.append((round(t * PPQ), 1, _meta(0x51, round(60_000_000 / bpm).to_bytes(3, "big"))))
    tracks = [_track(conductor)]

    # one MIDI channel per part.channel (a piano's hands share one), skipping GM percussion
    free = [c for c in range(16) if c != 9]
    keys = list(dict.fromkeys(p.channel for p in score.parts))
    channel_of = {k: free[i % len(free)] for i, k in enumerate(keys)}
    n = len(keys)

    for part in score.parts:
        ch = channel_of[part.channel]
        first_in_channel = next(p for p in score.parts if p.channel == part.channel) is part
        evs = [(0, 0, _meta(0x03, part.name.encode()))]
        if first_in_channel:
            i = keys.index(part.channel)
            pan = part.pan if part.pan is not None else (64 if n == 1 else round(34 + 60 * i / (n - 1)))
            evs += [(0, 0, bytes([0xC0 | ch, part.program])), (0, 0, bytes([0xB0 | ch, 10, pan]))]
            for t, value in perform.pedal_events(part):
                evs.append((round(t * PPQ), 0, bytes([0xB0 | ch, 64, value])))
        for t, _, program in part.registrations:
            if program is not None:
                evs.append((round(t * PPQ), 0, bytes([0xC0 | ch, program])))
        dyn = perform.Dynamics(part)
        for t, note in part.events():
            if note.is_rest:
                continue
            on = round(t * PPQ)
            off = round((t + perform.sounding_dur(note)) * PPQ)
            vel = perform.velocity(dyn, part, t, note)
            for m in sorted({p.midi + c for p in note.pitches for c in part.couplers if 0 <= p.midi + c < 128}):
                evs.append((on, 2, bytes([0x90 | ch, m, vel])))
                evs.append((off, 1, bytes([0x80 | ch, m, 0])))
        tracks.append(_track(evs))
    header = (b"MThd" + (6).to_bytes(4, "big") + (1).to_bytes(2, "big")
              + len(tracks).to_bytes(2, "big") + PPQ.to_bytes(2, "big"))
    return header + b"".join(tracks)


def write_midi(score: Score, path: str) -> None:
    with open(path, "wb") as f:
        f.write(midi_bytes(score))


# --- reading -------------------------------------------------------------------


def read_notes(data: bytes) -> list[tuple[Fraction, int, Fraction]]:
    """(onset, pitch, duration) for every note in a Standard MIDI File, times in
    quarter notes. Used to prove an engraving contains exactly the score's notes."""
    if data[:4] != b"MThd":
        raise ValueError("not a MIDI file")
    ntracks = int.from_bytes(data[10:12], "big")
    ppq = int.from_bytes(data[12:14], "big")
    pos, notes = 14, []
    for _ in range(ntracks):
        if data[pos:pos + 4] != b"MTrk":
            raise ValueError("bad track header")
        end = pos + 8 + int.from_bytes(data[pos + 4:pos + 8], "big")
        pos += 8
        tick, status, sounding = 0, 0, {}
        while pos < end:
            delta = 0
            while True:
                b = data[pos]
                pos += 1
                delta = (delta << 7) | (b & 0x7F)
                if b < 0x80:
                    break
            tick += delta
            if data[pos] >= 0x80:
                status = data[pos]
                pos += 1
            kind = status & 0xF0
            if status == 0xFF:                      # meta: type, length, data
                pos += 1
                length = 0
                while True:
                    b = data[pos]
                    pos += 1
                    length = (length << 7) | (b & 0x7F)
                    if b < 0x80:
                        break
                pos += length
            elif status in (0xF0, 0xF7):            # sysex
                length = 0
                while True:
                    b = data[pos]
                    pos += 1
                    length = (length << 7) | (b & 0x7F)
                    if b < 0x80:
                        break
                pos += length
            elif kind in (0x80, 0x90):
                pitch, vel = data[pos], data[pos + 1]
                pos += 2
                k = (status & 0x0F, pitch)
                if kind == 0x90 and vel > 0:
                    sounding.setdefault(k, []).append(tick)
                elif sounding.get(k):
                    on = sounding[k].pop(0)
                    notes.append((Fraction(on, ppq), pitch, Fraction(tick - on, ppq)))
            elif kind in (0xC0, 0xD0):
                pos += 1
            else:                                   # 0xA0, 0xB0, 0xE0
                pos += 2
        pos = end
    return sorted(notes)
