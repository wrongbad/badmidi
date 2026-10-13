"""Scores and parts: placing motifs at explicit bar/beat anchors."""
from __future__ import annotations

from fractions import Fraction

from .core import Bar, Mark, Motif, Note, Pitch, as_pitch
from .scale import Scale, key as parse_key

# name: (General MIDI program, lowest pitch, highest pitch) -- sounding ranges.
INSTRUMENTS: dict[str, tuple[int, int, int]] = {
    "piano": (0, 21, 108), "harpsichord": (6, 29, 89), "celesta": (8, 60, 108),
    "glockenspiel": (9, 79, 108), "vibraphone": (11, 53, 89), "marimba": (12, 45, 96),
    "organ": (19, 36, 96), "pedal": (19, 36, 67), "drawbar organ": (16, 36, 96),
    "percussive organ": (17, 36, 96), "rock organ": (18, 36, 96), "reed organ": (20, 36, 96),
    "guitar": (24, 40, 83), "bass guitar": (33, 28, 67),
    "violin": (40, 55, 103), "viola": (41, 48, 88), "cello": (42, 36, 81),
    "contrabass": (43, 28, 67), "harp": (46, 24, 103), "strings": (48, 28, 103),
    "choir": (52, 40, 81), "soprano": (52, 60, 81), "alto": (52, 53, 74),
    "tenor": (52, 48, 69), "bass": (52, 40, 64),
    "trumpet": (56, 54, 86), "trombone": (57, 40, 77), "tuba": (58, 26, 65),
    "horn": (60, 35, 77), "oboe": (68, 58, 93), "english horn": (69, 52, 81),
    "bassoon": (70, 34, 76), "clarinet": (71, 50, 94), "piccolo": (72, 74, 108),
    "flute": (73, 60, 96), "recorder": (74, 72, 98),
}


def _exact(x) -> Fraction:
    return Fraction(x).limit_denominator(192) if isinstance(x, float) else Fraction(x)


class Part:
    """One instrument's line. Place material at explicit anchors:

        vln.at(5, theme)             # bar 5, beat 1
        vln.at(5, theme, beat=3)     # bar 5, beat 3
        vln.then(answer)             # straight after whatever was placed last
        vln.mark(9, "<")             # a marking with no notes: bar 9, beat 1

    Engraving: parts sharing a `staff` are printed as voices on one staff;
    parts sharing a `group` (a piano's hands, an organ's manuals and pedal)
    are bracketed together and share dynamics and pedal marks. Braced
    staves (brace=True) go inside the group's brace; an organ's pedal staff
    sits below it.

    Performance only: `balance` is a velocity offset (bring out a melody);
    `couplers` are octave offsets that sound with every note ((0, -12) is an
    organ pedal with a 16' stop); parts with the same `channel` share a MIDI
    channel (a piano's hands), otherwise each part gets its own.
    """

    def __init__(self, score: "Score", name: str, instrument: str | None = None,
                 program: int | None = None, range: tuple | None = None,
                 group: str | None = None, staff: str | None = None, clef: str | None = None,
                 brace: bool = True, balance: int = 0, couplers: tuple[int, ...] = (0,),
                 channel: str | None = None, pan: int | None = None):
        inst = instrument or (name if name in INSTRUMENTS else "piano")
        if inst not in INSTRUMENTS:
            raise ValueError(f"unknown instrument {inst!r}; known: {', '.join(INSTRUMENTS)}")
        prog, lo, hi = INSTRUMENTS[inst]
        self.score = score
        self.name = name
        self.instrument = inst
        self.program = prog if program is None else program
        self.range: tuple[Pitch, Pitch] = (as_pitch(range[0]), as_pitch(range[1])) if range else (Pitch(lo), Pitch(hi))
        self.group = group
        self.staff = staff or name
        self.clef = clef
        self.brace = brace
        self.balance = balance
        self.couplers = couplers
        self.channel = channel or name
        self.registrations: list[tuple[Fraction, str, int | None]] = []
        self.pan = pan
        self.placements: list[tuple[Fraction, Motif]] = []
        self._last_end = Fraction(0)

    def at(self, bar: int, *material, beat=1) -> "Part":
        start = self.score.time(bar, beat)
        motif = Motif(*material)
        self.placements.append((start, motif))
        self._last_end = start + motif.dur
        return self

    def then(self, *material) -> "Part":
        motif = Motif(*material)
        self.placements.append((self._last_end, motif))
        self._last_end += motif.dur
        return self

    def registration(self, bar: int, text: str, program: int | str | None = None, beat=1) -> "Part":
        """A registration change, printed above the staff ("Sw.: Flutes 8' 4'").
        program (a GM number or an instrument name) is what it sounds like."""
        if isinstance(program, str):
            program = INSTRUMENTS[program][0]
        self.registrations.append((self.score.time(bar, beat), text, program))
        self.registrations.sort(key=lambda r: r[0])
        return self

    def mark(self, bar: int, *marks, beat=1) -> "Part":
        """Place markings (dynamics, hairpins, pedal, text) at a position
        without any notes, e.g. part.mark(12, "<", beat=3)."""
        motif = Motif(*marks)
        if motif.notes:
            raise ValueError("mark() takes markings only; use at() for notes")
        self.placements.append((self.score.time(bar, beat), motif))
        return self

    @property
    def end(self) -> Fraction:
        return max((s + m.dur for s, m in self.placements), default=Fraction(0))

    def events(self, merge_ties: bool = True) -> list[tuple[Fraction, Note]]:
        """(start time, note) for every note and rest, sorted by time.

        With merge_ties, a tied note and the same-pitched note right after it
        become one event, which is how it sounds."""
        out = []
        for start, motif in self.placements:
            t = start
            for it in motif.items:
                if isinstance(it, Note):
                    out.append((t, it))
                    t += it.dur
        out.sort(key=lambda e: e[0])
        if not merge_ties:
            return out
        merged: list[tuple[Fraction, Note]] = []
        for t, n in out:
            if merged:
                pt, pn = merged[-1]
                if pn.tied and pt + pn.dur == t and pn.pitches == n.pitches:
                    art = pn.art + ("@" if "@" in n.art else "")
                    merged[-1] = (pt, Note(n.pitches, pn.dur + n.dur, n.tied, art))
                    continue
            merged.append((t, n))
        return merged

    def marks(self, kind: type | None = None) -> list[tuple[Fraction, Bar | Mark]]:
        """(time, item) for every bar anchor and marking, sorted by time
        (stable, so marks at the same moment keep their written order)."""
        out = []
        for start, motif in self.placements:
            t = start
            for it in motif.items:
                if isinstance(it, Note):
                    t += it.dur
                elif kind is None or isinstance(it, kind):
                    out.append((t, it))
        out.sort(key=lambda e: e[0])
        return out

    def __repr__(self) -> str:
        return f"Part({self.name!r}, {self.instrument!r})"


class TempoMark:
    """A tempo indication at a point (text and/or metronome mark), or a
    gradual change over a span (rit./accel. to a target tempo)."""

    def __init__(self, start: Fraction, text: str | None = None, bpm: float | None = None,
                 end: Fraction | None = None):
        self.start, self.text, self.bpm, self.end = start, text, bpm, end

    @property
    def gradual(self) -> bool:
        return self.end is not None

    def __repr__(self) -> str:
        return f"TempoMark({self.start}, {self.text!r}, {self.bpm}, end={self.end})"


class Score:
    """A piece: meter, tempo, key, and an ordered list of parts (top to bottom).

    tempo is the starting metronome mark in quarter notes per minute;
    tempo_text the printed indication ("Allegro agitato"). Later tempo
    changes go through tempo_mark(), rit() and accel().
    """

    def __init__(self, title: str = "", meter: tuple[int, int] = (4, 4),
                 tempo: float = 100, key: str | Scale = "C major",
                 tempo_text: str | None = None, composer: str | None = None):
        self.title = title
        self.composer = composer
        self.meter = meter
        self.tempo = tempo
        self.key = parse_key(key)
        self.parts: list[Part] = []
        self.tempo_marks: list[TempoMark] = [TempoMark(Fraction(0), tempo_text, tempo)]

    def part(self, name: str, instrument: str | None = None, **kw) -> Part:
        if any(p.name == name for p in self.parts):
            raise ValueError(f"duplicate part name {name!r}")
        p = Part(self, name, instrument, **kw)
        self.parts.append(p)
        return p

    def ordered_parts(self) -> list[Part]:
        """Parts top to bottom as printed: by staff, in order of each staff's
        first appearance; parts sharing a staff stay in creation order."""
        staves = list(dict.fromkeys(p.staff for p in self.parts))
        return [p for st in staves for p in self.parts if p.staff == st]

    def piano(self, upper: str = "rh", lower: str = "lh", name: str = "Piano") -> tuple[Part, Part]:
        """A grand staff: right hand (treble) and left hand (bass), one MIDI channel."""
        return (self.part(upper, "piano", group=name, clef="treble", channel=name),
                self.part(lower, "piano", group=name, clef="bass", channel=name))

    def organ(self, upper: str = "rh", lower: str = "lh", pedal: str = "pedal",
              name: str = "Organ") -> tuple[Part, Part, Part]:
        """Two manual staves in a brace and a pedal staff below, with a 16'
        stop on the pedal. Add more voices with
        score.part("alto", "organ", group="Organ", staff="rh")."""
        return (self.part(upper, "organ", group=name, clef="treble"),
                self.part(lower, "organ", group=name, clef="bass"),
                self.part(pedal, "pedal", group=name, clef="bass", brace=False, couplers=(0, -12)))

    # --- tempo --------------------------------------------------------------

    def pos(self, at) -> Fraction:
        """A position given as a bar number or a (bar, beat) tuple."""
        return self.time(*at) if isinstance(at, tuple) else self.time(at)

    def tempo_mark(self, at, text: str | None = None, bpm: float | None = None) -> "Score":
        """score.tempo_mark(20, "Più mosso", 144); score.tempo_mark((31, 3), "a tempo", 132)"""
        self.tempo_marks.append(TempoMark(self.pos(at), text, bpm))
        self.tempo_marks.sort(key=lambda m: m.start)
        return self

    def rit(self, start, end, to: float, text: str = "rit.") -> "Score":
        """Gradually slow from `start` to `end` (bar or (bar, beat)), arriving at `to`."""
        self.tempo_marks.append(TempoMark(self.pos(start), text, to, self.pos(end)))
        self.tempo_marks.sort(key=lambda m: m.start)
        return self

    def accel(self, start, end, to: float, text: str = "accel.") -> "Score":
        return self.rit(start, end, to, text)

    def __getitem__(self, name: str) -> Part:
        for p in self.parts:
            if p.name == name:
                return p
        raise KeyError(name)

    # --- time ---------------------------------------------------------------

    @property
    def bar_len(self) -> Fraction:
        return Fraction(4 * self.meter[0], self.meter[1])

    @property
    def beat_len(self) -> Fraction:
        return Fraction(4, self.meter[1])

    def time(self, bar: int, beat=1) -> Fraction:
        """Absolute time (in quarter notes) of bar N, beat B (both 1-based)."""
        beat = _exact(beat)
        if bar < 1 or beat < 1:
            raise ValueError(f"bars and beats are numbered from 1 (got bar {bar}, beat {beat})")
        if beat >= self.meter[0] + 1:
            raise ValueError(f"beat {beat} is past the end of a {self.meter[0]}/{self.meter[1]} bar")
        return (bar - 1) * self.bar_len + (beat - 1) * self.beat_len

    def position(self, t: Fraction) -> tuple[int, Fraction]:
        """Inverse of time(): (bar, beat) for an absolute time."""
        bar = int(t // self.bar_len)
        return bar + 1, (t - bar * self.bar_len) / self.beat_len + 1

    def where(self, t: Fraction) -> str:
        from .views import fmt_pos
        return fmt_pos(self, t)

    @property
    def end(self) -> Fraction:
        return max((p.end for p in self.parts), default=Fraction(0))

    @property
    def bars(self) -> int:
        return max(1, -(-self.end // self.bar_len))

    def seconds(self, t: Fraction) -> float:
        from .perform import tempo_map, seconds_at
        return seconds_at(tempo_map(self), t)

    # --- output -------------------------------------------------------------

    def melody(self, **kw) -> str:
        from .views import melody
        return melody(self, **kw)

    def grid(self, **kw) -> str:
        from .views import grid
        return grid(self, **kw)

    def check(self, **kw) -> str:
        from .views import check
        return check(self, **kw)

    def write_midi(self, path: str) -> None:
        from .midi import write_midi
        write_midi(self, path)

    def render_wav(self, path: str, soundfont: str | None = None) -> None:
        from .render import render_wav
        render_wav(self, path, soundfont)

    def lilypond(self) -> str:
        from .lilypond import lilypond
        return lilypond(self)

    def engrave(self, path: str, fmt: str = "pdf") -> str:
        from .lilypond import engrave
        return engrave(self, path, fmt)

    def __repr__(self) -> str:
        return f"Score({self.title!r}, {len(self.parts)} parts, {self.bars} bars)"
