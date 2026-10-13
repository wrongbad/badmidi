"""Core values: pitches, chords, notes, rests, bar anchors and motifs.

All time is measured in quarter notes, as exact Fractions, so durations
never drift from floating point error.
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from fractions import Fraction
from typing import Callable, Iterable

SHARP_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLAT_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
LETTERS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

_names: list[str] = SHARP_NAMES


@contextmanager
def spelling(how):
    """Spell computed pitches inside the block: True = flats, False = sharps,
    or a key (anything with .names, a 12-entry pitch-class -> name table)."""
    global _names
    table = how.names if hasattr(how, "names") else (FLAT_NAMES if how else SHARP_NAMES)
    old, _names = _names, table
    try:
        yield
    finally:
        _names = old


def pc_name(pc: int, flats: bool | None = None) -> str:
    if flats is None:
        return _names[pc % 12]
    return (FLAT_NAMES if flats else SHARP_NAMES)[pc % 12]


def octave_of(midi: int, name: str) -> int:
    """Octave number for a pitch spelled `name`: B#3 is MIDI 60, Cb4 is 59."""
    alter = name.count("#") - name.count("b")
    return (midi - alter - LETTERS[name[0]]) // 12 - 1


# Durations in quarter notes. Suffix "d" = dotted, "3" = triplet.
DURATIONS: dict[str, Fraction] = {
    "w": Fraction(4), "h": Fraction(2), "q": Fraction(1), "e": Fraction(1, 2),
    "s": Fraction(1, 4), "t": Fraction(1, 8),
    "wd": Fraction(6), "hd": Fraction(3), "qd": Fraction(3, 2), "ed": Fraction(3, 4), "sd": Fraction(3, 8),
    "h3": Fraction(4, 3), "q3": Fraction(2, 3), "e3": Fraction(1, 3), "s3": Fraction(1, 6),
}
DURATION_CODES = {v: k for k, v in DURATIONS.items()}


def as_duration(x) -> Fraction:
    """Coerce a number of quarter notes to an exact positive Fraction."""
    if isinstance(x, bool):
        raise TypeError(f"duration must be a number of quarter notes, got {x!r}")
    if isinstance(x, Fraction):
        d = x
    elif isinstance(x, int):
        d = Fraction(x)
    elif isinstance(x, float):
        d = Fraction(x).limit_denominator(192)
    else:
        raise TypeError(f"duration must be a number of quarter notes, got {x!r}")
    if d <= 0:
        raise ValueError(f"duration must be positive, got {x!r}")
    return d


def fmt_number(x: Fraction) -> str:
    """3 -> '3', 5/2 -> '2.5', 5/3 -> '(5/3)'."""
    x = Fraction(x)
    if x.denominator == 1:
        return str(x.numerator)
    if x.denominator & (x.denominator - 1) == 0:  # power of two: exact decimal
        return f"{float(x):g}"
    return f"({x.numerator}/{x.denominator})"


def dur_suffix(d: Fraction) -> str:
    code = DURATION_CODES.get(d)
    return f".{code}" if code else f"*{fmt_number(d)}"


class _Durational:
    """Mixin: anything that becomes a Note once given a duration.

    E4.q, E4.qd (dotted), E4.e3 (triplet), or E4 * 1.5 (in quarter notes).
    """
    __slots__ = ()

    def _with_dur(self, d: Fraction) -> "Note":
        raise NotImplementedError

    def __mul__(self, beats) -> "Note":
        return self._with_dur(as_duration(beats))

    __rmul__ = __mul__

    w = property(lambda self: self._with_dur(DURATIONS["w"]))
    h = property(lambda self: self._with_dur(DURATIONS["h"]))
    q = property(lambda self: self._with_dur(DURATIONS["q"]))
    e = property(lambda self: self._with_dur(DURATIONS["e"]))
    s = property(lambda self: self._with_dur(DURATIONS["s"]))
    t = property(lambda self: self._with_dur(DURATIONS["t"]))
    wd = property(lambda self: self._with_dur(DURATIONS["wd"]))
    hd = property(lambda self: self._with_dur(DURATIONS["hd"]))
    qd = property(lambda self: self._with_dur(DURATIONS["qd"]))
    ed = property(lambda self: self._with_dur(DURATIONS["ed"]))
    sd = property(lambda self: self._with_dur(DURATIONS["sd"]))
    h3 = property(lambda self: self._with_dur(DURATIONS["h3"]))
    q3 = property(lambda self: self._with_dur(DURATIONS["q3"]))
    e3 = property(lambda self: self._with_dur(DURATIONS["e3"]))
    s3 = property(lambda self: self._with_dur(DURATIONS["s3"]))


class Pitch(_Durational):
    """A MIDI pitch. E4 + 7 -> B4; B4 - E4 -> 7; E4 & G4 -> Chord.

    spell remembers how a pitch was written ("Bb", "B#"), so it prints the
    same way back. Computed pitches (transpositions etc.) have no spelling
    of their own and are spelled by the key of the score being shown.
    """
    __slots__ = ("midi", "spell")

    def __init__(self, midi: int, spell: str | None = None):
        if not 0 <= midi <= 127:
            raise ValueError(f"pitch out of MIDI range: {midi}")
        self.midi = int(midi)
        self.spell = spell

    @classmethod
    def parse(cls, text: str) -> "Pitch":
        m = re.fullmatch(r"([A-Ga-g])([#sb]*)(-?\d)", text.strip())
        if not m:
            raise ValueError(f"can't parse pitch {text!r} (expected e.g. 'E4', 'F#3', 'Bb2')")
        letter, acc, octave = m.groups()
        sharps = acc.count("#") + acc.count("s")
        pc = LETTERS[letter.upper()] + sharps - acc.count("b")
        spell = letter.upper() + "#" * sharps + "b" * acc.count("b") if acc else None
        return cls(12 * (int(octave) + 1) + pc, spell)

    @property
    def pc(self) -> int:
        return self.midi % 12

    @property
    def octave(self) -> int:
        return self.midi // 12 - 1

    @property
    def name(self) -> str:
        n = self.spell or pc_name(self.pc)
        return f"{n}{octave_of(self.midi, n)}"

    def __repr__(self) -> str:
        return self.name.replace("#", "s")  # valid Python name: Fs4, Bb3

    def __str__(self) -> str:
        return self.name

    def __add__(self, semitones: int) -> "Pitch":
        if isinstance(semitones, int) and not isinstance(semitones, bool):
            # whole octaves keep the written spelling: D#4 + 12 is D#5, not Eb5
            return Pitch(self.midi + semitones, self.spell if semitones % 12 == 0 else None)
        return NotImplemented

    __radd__ = __add__

    def __sub__(self, other):
        if isinstance(other, Pitch):
            return self.midi - other.midi
        if isinstance(other, int):
            return Pitch(self.midi - other)
        return NotImplemented

    def __and__(self, other) -> "Chord":
        return Chord(self, other)

    def __eq__(self, other) -> bool:
        return isinstance(other, Pitch) and other.midi == self.midi

    def __hash__(self) -> int:
        return hash(self.midi)

    def __lt__(self, other: "Pitch") -> bool:
        return self.midi < other.midi

    def __le__(self, other: "Pitch") -> bool:
        return self.midi <= other.midi

    def __gt__(self, other: "Pitch") -> bool:
        return self.midi > other.midi

    def __ge__(self, other: "Pitch") -> bool:
        return self.midi >= other.midi

    def _with_dur(self, d: Fraction) -> "Note":
        return Note((self,), d)


def as_pitch(x) -> Pitch:
    if isinstance(x, Pitch):
        return x
    if isinstance(x, int) and not isinstance(x, bool):
        return Pitch(x)
    if isinstance(x, str):
        return Pitch.parse(x)
    raise TypeError(f"expected a pitch, got {x!r}")


class Chord(_Durational):
    """Simultaneous pitches without a duration yet: (C4 & E4 & G4).h"""
    __slots__ = ("pitches",)

    def __init__(self, *pitches):
        ps: set[Pitch] = set()
        for p in pitches:
            ps.update(p.pitches if isinstance(p, Chord) else (as_pitch(p),))
        self.pitches = tuple(sorted(ps))

    def __and__(self, other) -> "Chord":
        return Chord(self, other)

    __rand__ = __and__

    def __add__(self, semitones: int) -> "Chord":
        return Chord(*(p + semitones for p in self.pitches))

    def __repr__(self) -> str:
        return "(" + " & ".join(map(repr, self.pitches)) + ")"

    def _with_dur(self, d: Fraction) -> "Note":
        return Note(self.pitches, d)


# Articulation suffixes, in canonical order.
ARTICULATIONS = {">": "accent", "^": "marcato", "'": "staccato", "_": "tenuto", "@": "fermata"}


class Note:
    """Pitches sounding for a duration. No pitches = rest; several = chord.

    tied=True ties the note into the next one if it has the same pitches
    (written E4.h.tie in Python, E4.h~ in strings): it sounds as one note.
    art holds articulation suffixes (see ARTICULATIONS): E4.q> is accented.
    """
    __slots__ = ("pitches", "dur", "tied", "art")

    def __init__(self, pitches: Iterable = (), dur=1, tied: bool = False, art: str = ""):
        self.pitches: tuple[Pitch, ...] = tuple(sorted({as_pitch(p) for p in pitches}))
        self.dur: Fraction = as_duration(dur)
        self.tied = bool(tied) and bool(self.pitches)
        bad = set(art) - set(ARTICULATIONS)
        if bad:
            raise ValueError(f"unknown articulation {''.join(sorted(bad))!r}; known: {' '.join(ARTICULATIONS)}")
        if not self.pitches and set(art) - {"@"}:
            raise ValueError("a rest can only take a fermata (@)")
        self.art = "".join(c for c in ARTICULATIONS if c in art)

    @property
    def is_rest(self) -> bool:
        return not self.pitches

    @property
    def pitch(self) -> Pitch:
        if len(self.pitches) != 1:
            raise ValueError(f"{self!r} is not a single pitch")
        return self.pitches[0]

    @property
    def dot(self) -> "Note":
        return Note(self.pitches, self.dur * Fraction(3, 2), self.tied, self.art)

    @property
    def tie(self) -> "Note":
        return Note(self.pitches, self.dur, True, self.art)

    def articulate(self, art: str) -> "Note":
        return Note(self.pitches, self.dur, self.tied, self.art + art)

    accent = property(lambda self: self.articulate(">"))
    marcato = property(lambda self: self.articulate("^"))
    staccato = property(lambda self: self.articulate("'"))
    tenuto = property(lambda self: self.articulate("_"))
    fermata = property(lambda self: self.articulate("@"))

    def with_dur(self, dur) -> "Note":
        return Note(self.pitches, dur, self.tied, self.art)

    def with_tied(self, tied: bool) -> "Note":
        return Note(self.pitches, self.dur, tied, self.art)

    def map_pitches(self, fn: Callable[[Pitch], Pitch]) -> "Note":
        return Note(tuple(fn(p) for p in self.pitches), self.dur, self.tied, self.art)

    def __add__(self, other) -> "Motif":
        return Motif(self, other)

    def __radd__(self, other) -> "Motif":
        return Motif(other, self)

    def __eq__(self, other) -> bool:
        return isinstance(other, Note) and self._key() == other._key()

    def __hash__(self) -> int:
        return hash(self._key())

    def _key(self):
        return self.pitches, self.dur, self.tied, self.art

    def head(self) -> str:
        """The pitch part of the token: 'E4', '[C4 E4 G4]', 'R'."""
        if self.is_rest:
            return "R"
        if len(self.pitches) == 1:
            return repr(self.pitches[0])
        return "[" + " ".join(map(repr, self.pitches)) + "]"

    def __repr__(self) -> str:
        """The string-notation token: E4.q, [C4 E4 G4].h, R.e, E4.h~, E4.q>"""
        return self.head() + dur_suffix(self.dur) + self.art + ("~" if self.tied else "")


class _Rest(_Durational):
    """R.q, R.h, R * 3 ..."""
    __slots__ = ()

    def _with_dur(self, d: Fraction) -> Note:
        return Note((), d)

    def __repr__(self) -> str:
        return "R"


R = _Rest()


class Bar:
    """An anchor inside a motif asserting "a barline falls here".

    Bar(14) additionally asserts it is the start of bar 14. `badmidi check`
    reports any anchor that doesn't land where it claims, so counting errors
    stay local instead of silently shifting everything after them.
    """
    __slots__ = ("number",)

    def __init__(self, number: int | None = None):
        self.number = number

    def __eq__(self, other) -> bool:
        return isinstance(other, Bar) and other.number == self.number

    def __hash__(self) -> int:
        return hash(("Bar", self.number))

    def __repr__(self) -> str:
        return "BAR" if self.number is None else f"Bar({self.number})"

    @property
    def token(self) -> str:
        """String-notation form: '|' or '|14'."""
        return "|" if self.number is None else f"|{self.number}"


BAR = Bar()


DYNAMICS = ("ppp", "pp", "p", "mp", "mf", "f", "ff", "fff", "sf", "sfz", "fp", "rfz")


class Mark:
    """A marking at a point in the music, as on a printed score.

        dynamic    p  ff  sfz ...      Mark("dyn", "p")      dyn("p")
        hairpin    <  >  (end: !)      CRESC, DIM, HAIRPIN_END
        pedal      ped  *              PED (down, or change if down), PED_UP
        text       "con fuoco"         text("con fuoco")

    A hairpin runs until the next dynamic (its target) or an explicit !.
    """
    __slots__ = ("kind", "value")
    TOKENS = {"cresc": "<", "dim": ">", "end": "!", "ped": "ped", "pedup": "*"}

    def __init__(self, kind: str, value: str | None = None):
        if kind == "dyn" and value not in DYNAMICS:
            raise ValueError(f"unknown dynamic {value!r}; known: {' '.join(DYNAMICS)}")
        if kind not in self.TOKENS and kind not in ("dyn", "text"):
            raise ValueError(f"unknown mark kind {kind!r}")
        self.kind, self.value = kind, value

    @property
    def token(self) -> str:
        if self.kind == "dyn":
            return self.value
        if self.kind == "text":
            return f'"{self.value}"'
        return self.TOKENS[self.kind]

    def __eq__(self, other) -> bool:
        return isinstance(other, Mark) and (other.kind, other.value) == (self.kind, self.value)

    def __hash__(self) -> int:
        return hash((self.kind, self.value))

    def __repr__(self) -> str:
        return self.token


def dyn(level: str) -> Mark:
    return Mark("dyn", level)


def text(words: str) -> Mark:
    return Mark("text", words)


CRESC, DIM, HAIRPIN_END = Mark("cresc"), Mark("dim"), Mark("end")
PED, PED_UP = Mark("ped"), Mark("pedup")


class Motif:
    """An immutable sequence of notes (and bar anchors). Every transformation
    returns a new Motif, so ideas can be named and developed like values:

        theme  = M(E4.q, G4.e, A4.e, B4.h)
        answer = theme.invert(around=A4).transpose(5)
    """
    __slots__ = ("items",)

    def __init__(self, *items):
        out: list[Note | Bar] = []
        for it in items:
            self._flatten(it, out)
        self.items: tuple[Note | Bar, ...] = tuple(out)

    @staticmethod
    def _flatten(it, out: list) -> None:
        if isinstance(it, Motif):
            out.extend(it.items)
        elif isinstance(it, (Note, Bar, Mark)):
            out.append(it)
        elif isinstance(it, str):
            out.extend(parse(it))
        elif isinstance(it, (list, tuple)):
            for x in it:
                Motif._flatten(x, out)
        elif isinstance(it, (Pitch, Chord, _Rest)):
            raise TypeError(f"{it!r} has no duration; write {it!r}.q, {it!r}.h, or {it!r} * beats")
        else:
            raise TypeError(f"can't put {it!r} in a motif")

    # --- inspection ---------------------------------------------------------

    @property
    def notes(self) -> list[Note]:
        return [n for n in self.items if isinstance(n, Note)]

    @property
    def dur(self) -> Fraction:
        return sum((n.dur for n in self.notes), Fraction(0))

    @property
    def pitches(self) -> list[Pitch]:
        """Every sounding pitch in order (chords contribute all their pitches)."""
        return [p for n in self.notes for p in n.pitches]

    @property
    def durations(self) -> list[Fraction]:
        return [n.dur for n in self.notes]

    def __len__(self) -> int:
        return len(self.notes)

    def __iter__(self):
        return iter(self.notes)

    def __getitem__(self, i):
        if isinstance(i, slice):
            return Motif(*self.notes[i])
        return self.notes[i]

    def __eq__(self, other) -> bool:
        return isinstance(other, Motif) and other.items == self.items

    def __hash__(self) -> int:
        return hash(self.items)

    def __repr__(self) -> str:
        return f"M({self.text()!r})"

    def text(self) -> str:
        """The motif in string notation; M(m.text()) == m."""
        return " ".join(repr(it) if isinstance(it, Note) else it.token for it in self.items)

    # --- assembly -----------------------------------------------------------

    def __add__(self, other) -> "Motif":
        return Motif(self, other)

    def __radd__(self, other) -> "Motif":
        return Motif(other, self)

    def __mul__(self, n: int) -> "Motif":
        if not isinstance(n, int):
            return NotImplemented
        return Motif(*([self] * n))

    __rmul__ = __mul__

    # --- transformations ----------------------------------------------------

    def map(self, fn: Callable[[Note], Note]) -> "Motif":
        return Motif(*(fn(it) if isinstance(it, Note) else it for it in self.items))

    def map_pitches(self, fn: Callable[[Pitch], Pitch]) -> "Motif":
        return self.map(lambda n: n.map_pitches(fn))

    def transpose(self, n: int, scale=None) -> "Motif":
        """Shift by n semitones, or by n scale steps if a scale/key is given."""
        if scale is None:
            return self.map_pitches(lambda p: p + n)
        return self.map_pitches(lambda p: scale.step(p, n))

    def octave(self, n: int = 1) -> "Motif":
        return self.transpose(12 * n)

    def double(self, *intervals: int) -> "Motif":
        """Add each pitch again at the given intervals: double(-12) for octaves
        below, double(12, 24) for two octaves above."""
        return self.map(lambda n: n if n.is_rest else
                        Note(n.pitches + tuple(p + i for p in n.pitches for i in intervals), n.dur, n.tied, n.art))

    def invert(self, around=None, scale=None) -> "Motif":
        """Mirror pitches around a pitch (default: the first pitch).
        Chromatic by default; diatonic if a scale/key is given."""
        if around is None:
            if not self.pitches:
                return self
            around = self.pitches[0]
        axis = as_pitch(around)
        if scale is None:
            return self.map_pitches(lambda p: Pitch(2 * axis.midi - p.midi))
        ai, _ = scale.index(axis)

        def flip(p: Pitch) -> Pitch:
            i, alter = scale.index(p)
            return scale.at(2 * ai - i, -alter)
        return self.map_pitches(flip)

    def retrograde(self) -> "Motif":
        """Reverse the notes. Dynamics, hairpins, pedal and text marks are
        dropped: they don't have a meaningful reverse."""
        # A tie joins a note to the one after it, so after reversing, each
        # note takes the tie flag of the note that now follows it.
        notes = self.notes
        ties = [n.tied for n in notes]
        flags = iter([ties[i - 1] if i > 0 else False for i in range(len(notes) - 1, -1, -1)])
        return Motif(*(it.with_tied(next(flags)) if isinstance(it, Note) else it
                       for it in reversed(self.items) if not isinstance(it, Mark)))

    def augment(self, factor=2) -> "Motif":
        f = Fraction(factor) if not isinstance(factor, float) else as_duration(factor)
        return self.map(lambda n: n.with_dur(n.dur * f))

    def diminish(self, factor=2) -> "Motif":
        f = Fraction(factor) if not isinstance(factor, float) else as_duration(factor)
        return self.map(lambda n: n.with_dur(n.dur / f))

    def fragment(self, start: int, stop: int | None = None) -> "Motif":
        """Notes start..stop (Python slice semantics: stop excluded)."""
        return self[start:stop]

    def sequence(self, intervals: Iterable[int], scale=None) -> "Motif":
        """The motif followed by copies of itself, each shifted from the
        previous one by the next interval (semitones, or scale steps)."""
        out, cur = [self], self
        for iv in intervals:
            cur = cur.transpose(iv, scale)
            out.append(cur)
        return Motif(*out)

    def rhythm(self, *durs) -> "Motif":
        """Keep the pitches, replace the durations (cycled if fewer given).
        Accepts numbers of quarter notes or another Motif to borrow from."""
        if len(durs) == 1 and isinstance(durs[0], Motif):
            durs = tuple(durs[0].durations)
        if not durs:
            raise ValueError("rhythm() needs at least one duration")
        it = iter(range(len(self.notes)))
        return self.map(lambda n: n.with_dur(durs[next(it) % len(durs)]))

    def with_pitches(self, *pitches) -> "Motif":
        """Keep the rhythm, replace the pitches of non-rest notes (cycled)."""
        if len(pitches) == 1 and isinstance(pitches[0], Motif):
            pitches = tuple(pitches[0].pitches)
        ps = [as_pitch(p) for p in pitches]
        if not ps:
            raise ValueError("with_pitches() needs at least one pitch")
        counter = iter(range(len(self.notes)))
        return self.map(lambda n: n if n.is_rest else Note((ps[next(counter) % len(ps)],), n.dur, n.tied))


M = Motif


# --- string notation ---------------------------------------------------------
#
#   M("E4.q G4.e A4.e B4.h | [C4 E4 G4].h R.q Fs4.e Bb3.e |5 E4*1.5 E4.h~ | E4.q")
#
# A note token is exactly what the views print: PITCH or [PITCH ...] or R,
# then a duration (.q .ed .e3 ... or *1.5 or *(5/3)), then articulations
# (> ^ ' _ @), then an optional ~ tie. Octaves and durations are always
# explicit; nothing carries over from the previous token, so one mistake
# can't shift the notes after it.
#   |  |14           checked barline; start of bar 14
#   p ff sfz ...     dynamics
#   <  >  !          crescendo / diminuendo hairpin; explicit hairpin end
#   ped  *           pedal down (or change); pedal up
#   "con fuoco"      expression text


class NotationError(ValueError):
    pass


_TOKEN = re.compile(r'"[^"]*"|\|\d*|\[[^\]]*\][^\s|\[]*|[^\s|\[]+')
_MARK_TOKENS = {v: k for k, v in Mark.TOKENS.items()}
_NOTE = re.compile(r"""
    (?P<head> R | \[(?P<chord>[^\]]*)\] | [A-Ga-g][#sb]*-?\d )
    (?: \.(?P<code>[a-z0-9]+) | \*(?P<num> \d+(?:\.\d+)? | \(\d+/\d+\) | \d+/\d+ ) )
    (?P<art>[>^'_@]*)
    (?P<tie>~)?
    """, re.X)


def parse(source: str) -> list[Note | Bar | Mark]:
    """Parse string notation into notes, bar anchors and marks."""
    out: list[Note | Bar | Mark] = []
    bar = 1
    for m in _TOKEN.finditer(source):
        tok = m.group()
        if tok.startswith("|"):
            out.append(Bar(int(tok[1:])) if len(tok) > 1 else BAR)
            bar += 1
        elif tok.startswith('"'):
            out.append(Mark("text", tok[1:-1]))
        elif tok in DYNAMICS:
            out.append(Mark("dyn", tok))
        elif tok in _MARK_TOKENS:
            out.append(Mark(_MARK_TOKENS[tok]))
        else:
            try:
                out.append(_parse_note(tok))
            except (ValueError, TypeError) as e:
                caret = " " * m.start() + "^" * len(tok)
                raise NotationError(f"{e}\n  in bar {bar} of this string:\n    {source}\n    {caret}") from None
    return out


def _parse_note(tok: str) -> Note:
    m = _NOTE.fullmatch(tok)
    if not m:
        raise NotationError(f"can't read {tok!r}: expected e.g. E4.q, Fs4.e, [C4 E4 G4].h, R.q or E4*1.5")
    if m["code"] is not None:
        if m["code"] not in DURATIONS:
            raise NotationError(f"unknown duration .{m['code']} in {tok!r}; known: {' '.join(DURATIONS)}")
        dur = DURATIONS[m["code"]]
    else:
        dur = as_duration(Fraction(m["num"].strip("()")))
    if m["head"] == "R":
        if m["tie"]:
            raise NotationError(f"a rest can't be tied: {tok!r}")
        return Note((), dur, art=m["art"])
    if m["chord"] is not None:
        names = m["chord"].split()
        if not names:
            raise NotationError(f"empty chord in {tok!r}")
        pitches = [Pitch.parse(n) for n in names]
    else:
        pitches = [Pitch.parse(m["head"])]
    return Note(pitches, dur, bool(m["tie"]), m["art"])
