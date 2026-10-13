"""Engraving: export a score as LilyPond source, and render it to PDF/PNG.

Notes are split at barlines (and into printable values) with ties, exactly
as in the melody view. Markings go where a printed score puts them:
dynamics, hairpins and expression text on a Dynamics line under the staff
(between the hands for piano), pedal under the bottom staff, tempo marks
and rit./accel. spanners above the top staff.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from fractions import Fraction

from .core import Mark, Note, octave_of, pc_name, spelling
from .midi import read_notes
from .score import Part, Score

PLAIN = {Fraction(4, 2 ** k): str(2 ** k) for k in range(6)}          # 4 -> "1" ... 1/8 -> "32"
DOTTED = {d * Fraction(3, 2): s + "." for d, s in PLAIN.items()}
NORMAL = dict(sorted({**PLAIN, **DOTTED}.items(), reverse=True))
TRIPLET = dict(sorted({d * Fraction(2, 3): s for d, s in PLAIN.items()}.items(), reverse=True))
ARTICULATION = {">": "->", "^": "-^", "'": "-.", "_": "--", "@": "\\fermata"}
MODES = {"major": "major", "minor": "minor", "harmonic minor": "minor", "melodic minor": "minor",
         "dorian": "dorian", "phrygian": "phrygian", "lydian": "lydian",
         "mixolydian": "mixolydian", "locrian": "locrian"}


# --- small pieces ------------------------------------------------------------


def _pitch(p) -> str:
    name = p.spell or pc_name(p.pc)
    acc = "s" * name.count("#") + "f" * name.count("b")
    octave = octave_of(p.midi, name)
    return name[0].lower() + acc + ("'" * (octave - 3) if octave > 3 else "," * (3 - octave))


def _whole(d: Fraction) -> str:
    """A spacer/rest length in LilyPond's multiplier syntax: 1*3/4 etc."""
    w = d / 4
    return "1" if w == 1 else f"1*{w.numerator}/{w.denominator}"


def _split(d: Fraction) -> list[tuple[Fraction, str, bool]]:
    """Break a length into printable values: (length, lily duration, is_triplet)."""
    table, trip = (TRIPLET, True) if (d * 3).denominator & ((d * 3).denominator - 1) == 0 and d.denominator % 3 == 0 \
        else (NORMAL, False)
    out = []
    while d > 0:
        for v, s in table.items():
            if v <= d:
                out.append((v, s, trip))
                d -= v
                break
        else:  # not expressible with plain, dotted or triplet values: scale the duration
            out.append((d, f"4*{d.numerator}/{d.denominator}", False))
            break
    return out


def _clef(parts: list[Part]) -> str:
    if parts[0].clef:
        return parts[0].clef
    if parts[0].instrument in ("tenor", "guitar"):
        return '"treble_8"'
    ps = sorted(p.midi for part in parts for _, n in part.events() for p in n.pitches)
    return "bass" if ps and ps[len(ps) // 2] < 57 else "treble"


# --- note voices ---------------------------------------------------------------


# Ottava rule: a bar that sits this far off the staff gets an 8va/8vb sign
# rather than a ladder of ledger lines. (clef, lowest, highest, shift)
OTTAVA = {"treble": lambda lo, hi: 1 if lo >= 76 and hi >= 88 else 0,     # all above E5, reaching E6
          "bass": lambda lo, hi: -1 if hi <= 48 and lo <= 33 else 0}      # all below C3, reaching A1


def _ottavas(score: Score, part: Part, nbars: int, clef: str) -> list[int]:
    rule = OTTAVA.get(clef)
    shifts = [0] * nbars
    if rule is None:
        return shifts
    bl = score.bar_len
    ranges: list[list[int]] = [[] for _ in range(nbars)]
    for t, n in part.events(merge_ties=False):
        for b in range(int(t // bl), min(nbars, int(-(-(t + n.dur) // bl)))):
            ranges[b].extend(p.midi for p in n.pitches)
    return [rule(min(r), max(r)) if r else 0 for r in ranges]


def _voice(score: Score, part: Part, nbars: int, primary: bool, clef: str | None = None) -> str:
    """One voice as LilyPond music, with a bar check after every bar.
    Gaps print as rests in a staff's first voice and as invisible spacers in
    the others. With a clef, bars far off the staff get an ottava sign."""
    bl = score.bar_len
    total = nbars * bl
    timeline: list[tuple[Fraction, Fraction, Note | None]] = []
    cur = Fraction(0)
    for t, n in part.events(merge_ties=False):
        if t > cur:
            timeline.append((cur, t - cur, None))
        timeline.append((t, n.dur, n))
        cur = max(cur, t + n.dur)
    if cur < total:
        timeline.append((cur, total - cur, None))

    bars: list[list[tuple[str, bool]]] = [[] for _ in range(nbars)]   # (token, is_triplet)
    for start, dur, note in timeline:
        s, left = start, dur
        while left > 0:
            b = int(s // bl)
            seg = min(left, (b + 1) * bl - s)
            if b >= nbars:
                break
            if note is None and seg == bl:
                bars[b].append((("R" if primary else "s") + _whole(seg), False))
            else:
                pieces = _split(seg)
                for i, (v, ly, trip) in enumerate(pieces):
                    first = s == start and i == 0
                    last = seg == left and i == len(pieces) - 1
                    if note is None:
                        tok = ("r" if primary else "s") + ly
                    elif note.is_rest:
                        tok = "r" + ly + (ARTICULATION["@"] if "@" in note.art and last else "")
                    else:
                        head = _pitch(note.pitches[0]) if len(note.pitches) == 1 \
                            else "<" + " ".join(_pitch(p) for p in note.pitches) + ">"
                        tie = "~" if (not last or note.tied) else ""
                        arts = "".join(ARTICULATION[c] for c in note.art
                                       if (c == "@" and last) or (c != "@" and first))
                        tok = head + ly + tie + arts
                    bars[b].append((tok, v if trip else False))   # a triplet carries its length
            s += seg
            left -= seg

    shifts = _ottavas(score, part, nbars, clef) if clef else [0] * nbars
    out, shift = [], 0
    for b, bar in enumerate(bars):
        words, run = [], []
        if shifts[b] != shift:
            shift = shifts[b]
            words.append(f"\\ottava #{shift}")
        held = Fraction(0)
        for tok, trip in bar + [("", False)]:
            if trip:
                # one bracket per beat's worth, not one across a whole run
                run.append(tok)
                held += trip
                if held.denominator == 1:
                    words.append("\\tuplet 3/2 { " + " ".join(run) + " }")
                    run, held = [], Fraction(0)
                continue
            if run:
                words.append("\\tuplet 3/2 { " + " ".join(run) + " }")
                run, held = [], Fraction(0)
            if tok:
                words.append(tok)
        out.append(" ".join(words) + " |")
    return "\n    ".join(out)


# --- marking lines -------------------------------------------------------------


def _spacers(segments: list[tuple[Fraction, Fraction, str]]) -> str:
    """segments: (start, length, attachments) -> spacer rests with attachments."""
    return " ".join(f"s{_whole(d)}{att}" for _, d, att in segments if d > 0)


def _mark_line(times_marks: list[tuple[Fraction, str]], total: Fraction) -> str:
    """Spacer music carrying attachments at the given times. Attachments at
    the very end go on a short final spacer."""
    tail = Fraction(1, 8)
    at: dict[Fraction, str] = {}
    for t, ly in times_marks:
        t = min(t, total - tail)
        at[t] = at.get(t, "") + ly
    cuts = sorted(set(at) | {Fraction(0), total})
    return _spacers([(a, b - a, at.get(a, "")) for a, b in zip(cuts, cuts[1:])])


def _dynamics_line(parts: list[Part], total: Fraction, defs: list[str]) -> str | None:
    seen, items = set(), []
    for p in parts:
        for t, m in p.marks(Mark):
            if m.kind in ("dyn", "cresc", "dim", "end", "text") and (t, m) not in seen:
                seen.add((t, m))
                items.append((t, m))
    if not items:
        return None
    ly = {"cresc": "\\<", "dim": "\\>", "end": "\\!"}
    by_time: dict[Fraction, list[Mark]] = {}
    for t, m in sorted(items, key=lambda x: x[0]):
        by_time.setdefault(t, []).append(m)
    out = []
    for t, ms in by_time.items():
        dyns = [m for m in ms if m.kind == "dyn"]
        texts = [m.value for m in ms if m.kind == "text"]
        if len(dyns) == 1 and texts:          # "p dolce" side by side, as one dynamic
            name = f"dynText{_letters(len(defs))}"
            words = " ".join(f'#:normal-text #:italic "{_esc(x)}"' for x in texts)
            defs.append(f'{name} = #(make-dynamic-script (markup #:dynamic "{dyns[0].value}" {words}))')
            out.append((t, "\\" + name))
            ms = [m for m in ms if m.kind not in ("dyn", "text")]
        for m in ms:
            if m.kind == "dyn":
                out.append((t, "\\" + m.value))
            elif m.kind == "text":
                out.append((t, f'-\\markup {{ \\italic "{_esc(m.value)}" }}'))
            else:
                out.append((t, ly[m.kind]))
    return _mark_line(out, total)


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _letters(n: int) -> str:
    """0 -> 'A', 25 -> 'Z', 26 -> 'BA': LilyPond names can't contain digits."""
    out = ""
    while True:
        out = chr(65 + n % 26) + out
        n //= 26
        if not n:
            return out


def _pedal_line(parts: list[Part], total: Fraction) -> str | None:
    seen, items = set(), []
    for p in parts:
        for t, m in p.marks(Mark):
            if m.kind in ("ped", "pedup") and (t, m) not in seen:
                seen.add((t, m))
                items.append((t, m))
    if not items:
        return None
    out, down = [], False
    for t, m in sorted(items, key=lambda x: x[0]):
        if m.kind == "ped":
            out.append((t, "\\sustainOff\\sustainOn" if down else "\\sustainOn"))
            down = True
        elif down:
            out.append((t, "\\sustainOff"))
            down = False
    if down:
        out.append((total, "\\sustainOff"))
    return _mark_line(out, total)


def _tempo_line(score: Score, total: Fraction) -> str:
    items = []
    for m in score.tempo_marks:
        if m.gradual:
            items.append((m.start, "\\once \\override TextSpanner.bound-details.left.text = "
                                   f'\\markup {{ \\italic "{m.text}" }} '))
            items.append((m.start, "\\startTextSpan"))
            items.append((m.end, "\\stopTextSpan"))
        elif m.text or m.bpm:
            txt = f'"{m.text}" ' if m.text else ""
            bpm = f"4 = {round(m.bpm)}" if m.bpm else ""
            items.append((m.start, f"\\tempo {txt}{bpm} "))
    # \tempo and \override come before the spacer, \startTextSpan after it
    tail = Fraction(1, 8)
    before: dict[Fraction, str] = {}
    after: dict[Fraction, str] = {}
    for t, ly in items:
        t = min(t, total - tail) if t >= total else t
        (after if ly.startswith("\\st") else before)[t] = (after if ly.startswith("\\st") else before).get(t, "") + ly
    cuts = sorted(set(before) | set(after) | {Fraction(0), total})
    return " ".join(f"{before.get(a, '')}s{_whole(b - a)}{after.get(a, '')}" for a, b in zip(cuts, cuts[1:]))


# --- the whole score -----------------------------------------------------------


def lilypond(score: Score) -> str:
    nbars = score.bars
    total = nbars * score.bar_len
    k = score.key
    with spelling(k):
        tonic = _pitch_name_only(k.tonic_name)
        glob = (f"\\key {tonic} \\{MODES[k.mode]} \\time {score.meter[0]}/{score.meter[1]} "
                f"s{_whole(total)} \\bar \"|.\"")

        # staves in score order; each staff = parts sharing .staff
        staves: list[tuple[str, list[Part]]] = []
        for p in score.parts:
            for name, members in staves:
                if name == p.staff:
                    members.append(p)
                    break
            else:
                staves.append((p.staff, [p]))

        def staff_ly(name: str, members: list[Part], top: bool) -> str:
            m0 = members[0]
            title = "Ped." if m0.instrument == "pedal" else name.title()
            label = f'\\with {{ instrumentName = "{title}" }} ' if not (m0.group and m0.brace) else ""
            lines = [f'\\new Staff = "{name}" {label}<<', "  \\global", f"  \\clef {_clef(members)}"]
            if top:
                lines.append("  { " + _tempo_line(score, total) + " }")
            texts: dict[Fraction, list[str]] = {}
            for m in members:                       # one label per moment, duplicates merged
                for t, text, _ in m.registrations:
                    if text not in texts.setdefault(t, []):
                        texts[t].append(text)
            regs = [(t, f'^\\markup {{ \\small \\italic "{_esc(" / ".join(ts))}" }}')
                    for t, ts in sorted(texts.items())]
            if regs:
                lines.append("  { " + _mark_line(regs, total) + " }")
            if len(members) == 1:   # ottava signs only where one voice owns the staff
                lines.append("  {\n    " + _voice(score, members[0], nbars, True, _clef(members)) + "\n  }")
            else:
                for i, m in enumerate(members):
                    vo = ["\\voiceOne", "\\voiceTwo", "\\voiceThree", "\\voiceFour"][min(i, 3)]
                    lines.append(f'  \\new Voice = "{m.name}" {{ {vo}\n    '
                                 + _voice(score, m, nbars, i == 0) + "\n  }")
            lines.append(">>")
            return "\n".join(lines)

        defs: list[str] = []
        body: list[str] = []
        done_groups: set[str] = set()
        for i, (name, members) in enumerate(staves):
            group = members[0].group
            if group is None:
                body.append(staff_ly(name, members, i == 0))
                dyn = _dynamics_line(members, total, defs)
                ped = _pedal_line(members, total)
                for line in (dyn, ped):
                    if line:
                        body.append("\\new Dynamics { " + line + " }")
                continue
            if group in done_groups:
                continue
            done_groups.add(group)
            gstaves = [(n, ms) for n, ms in staves if ms[0].group == group]
            gparts = [p for _, ms in gstaves for p in ms]
            braced = [(n, ms) for n, ms in gstaves if ms[0].brace]
            loose = [(n, ms) for n, ms in gstaves if not ms[0].brace]   # e.g. organ pedal
            inner = []
            for j, (n, ms) in enumerate(braced):
                inner.append(staff_ly(n, ms, i == 0 and j == 0))
                if j == 0:
                    dyn = _dynamics_line(gparts, total, defs)
                    if dyn:
                        inner.append("\\new Dynamics { " + dyn + " }")
            ped = _pedal_line(gparts, total)
            if ped:
                inner.append("\\new Dynamics \\with { pedalSustainStyle = #'mixed } { " + ped + " }")
            body.append(f'\\new PianoStaff \\with {{ instrumentName = "{group}" }} <<\n'
                        + _indent("\n".join(inner)) + "\n>>")
            body.extend(staff_ly(n, ms, False) for n, ms in loose)

    header = [f'  title = "{score.title}"'] if score.title else []
    if score.composer:
        header.append(f'  composer = "{score.composer}"')
    header.append("  tagline = ##f")
    return "\n".join([
        '\\version "2.24.0"',
        '\\language "english"',
        "\\header {", *header, "}",
        *defs,
        "global = { " + glob + " }",
        "\\score {",
        "  <<",
        _indent(_indent("\n".join(body))),
        "  >>",
        "  \\layout { }",
        "  \\midi { }",
        "}",
        "",
    ])


def _pitch_name_only(name: str) -> str:
    return name[0].lower() + "s" * name.count("#") + "f" * name.count("b")


def _indent(text: str) -> str:
    return "\n".join("  " + line if line else line for line in text.splitlines())


class EngraveError(RuntimeError):
    pass


def score_notes(score: Score) -> list[tuple[Fraction, int, Fraction]]:
    """Every sounding (onset, pitch, duration) in the score as written (ties
    merged; no couplers, staccato or other performance changes)."""
    return sorted((t, p.midi, n.dur) for part in score.parts for t, n in part.events()
                  if not n.is_rest for p in n.pitches)


def verify(score: Score, engraved_midi: bytes) -> list[str]:
    """Compare the notes LilyPond engraved (via the MIDI it writes from the
    same source) with the score. Returns the differences, empty if identical."""
    from collections import Counter
    from .core import Pitch
    from .views import fmt_pos
    # LilyPond's MIDI plays staccato notes short, so those match on onset and pitch only
    short = {(t, p.midi) for part in score.parts for t, n in part.events() if "'" in n.art for p in n.pitches}

    def key(t, m, d):
        return (t, m, None) if (t, m) in short else (t, m, d)
    want = Counter(key(*n) for n in score_notes(score))
    got = Counter(key(*n) for n in read_notes(engraved_midi))
    problems = []
    for label, diff in (("missing from the engraving", want - got), ("extra in the engraving", got - want)):
        for (t, m, d), n in sorted(diff.items(), key=lambda x: (x[0][0], x[0][1])):
            length = "staccato" if d is None else f"{d} quarters"
            problems.append(f"{label}: {Pitch(m)} at {fmt_pos(score, t)}, {length}" + (f" (x{n})" if n > 1 else ""))
    return problems


def engrave(score: Score, path: str, fmt: str = "pdf", strict: bool = True) -> str:
    """Write <stem>.ly next to `path` and render it with LilyPond to pdf or png.

    Then prove the engraving: LilyPond also writes MIDI from the same source,
    and every note in it must match the score exactly (pitch, onset, length).
    With strict, any LilyPond warning is an error too. Returns LilyPond's log."""
    exe = shutil.which("lilypond")
    if not exe:
        raise FileNotFoundError("lilypond not found (brew install lilypond)")
    stem = os.path.splitext(path)[0]
    with open(stem + ".ly", "w") as f:
        f.write(lilypond(score))
    args = [exe, "-s", "-o", stem]
    args += ["--png", "-dresolution=110"] if fmt == "png" else ["--pdf"]
    r = subprocess.run(args + [stem + ".ly"], capture_output=True, text=True)
    if r.returncode != 0:
        raise EngraveError(f"lilypond failed:\n{r.stderr}")
    warnings = [line for line in r.stderr.splitlines() if "warning:" in line or "error:" in line]
    if strict and warnings:
        raise EngraveError("lilypond warnings (see " + stem + ".ly):\n" + "\n".join(warnings))
    midi_path = stem + ".midi"
    with open(midi_path, "rb") as f:
        problems = verify(score, f.read())
    os.remove(midi_path)
    if problems:
        raise EngraveError(f"the engraving does not match the score ({len(problems)} differences):\n"
                           + "\n".join(problems[:20]))
    return r.stderr
