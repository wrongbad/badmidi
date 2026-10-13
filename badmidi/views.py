"""Text views of a score.

melody(): melody-major. Each part is a horizontal line, bars in aligned columns.
          Each row is valid string notation: paste it into M("...") or part.at().
grid():   harmony-major. Time runs down, parts run across, one row per onset,
          with the sounding chord, its roman numeral and its set class.
check():  is the score what you meant to write: bar counts, overlaps, ranges.
lens():   what the voices are doing: dissonances named by how they move,
          parallels, crossings. Descriptive, not prescriptive.
"""
from __future__ import annotations

import bisect
from fractions import Fraction

from .core import DURATIONS, Bar, Mark, Note, dur_suffix, fmt_number, pc_name, spelling
from .score import Part, Score

# --- formatting --------------------------------------------------------------


def fmt_beat(beat: Fraction) -> str:
    """3 -> '3', 5/2 -> '2.5', 7/3 -> '2+1/3'."""
    if beat.denominator == 1 or beat.denominator & (beat.denominator - 1) == 0:
        return fmt_number(beat)
    whole = beat.numerator // beat.denominator
    frac = beat - whole
    return f"{whole}+{frac.numerator}/{frac.denominator}"


def fmt_pos(score: Score, t: Fraction) -> str:
    bar, beat = score.position(t)
    return f"{bar}:{fmt_beat(beat)}"


_REST_UNITS = sorted((d for k, d in DURATIONS.items() if "3" not in k), reverse=True)


def _rest_tokens(d: Fraction) -> list[str]:
    """Spell a rest of arbitrary length as standard values, largest first."""
    out = []
    for unit in _REST_UNITS:
        while d >= unit:
            out.append("R" + dur_suffix(unit))
            d -= unit
    if d > 0:
        out.append("R" + dur_suffix(d))
    return out


def _select(score: Score, parts) -> list[Part]:
    if not parts:
        return score.ordered_parts()
    names = [parts] if isinstance(parts, str) else list(parts)
    return [score[n] for n in names]


def _bar_range(score: Score, bars) -> tuple[int, int]:
    if bars is None:
        return 1, score.bars
    if isinstance(bars, int):
        return bars, bars
    return bars[0], bars[1]


def _header(score: Score) -> str:
    title = score.title or "untitled"
    return f"{title}  ({score.meter_at(1).text}, {score.key.name}, q={fmt_number(Fraction(score.tempo))})"


def _bar_label(score: Score, bar: int) -> str:
    """'9' or, where the meter changes, '9 3/4'."""
    m = score.meter_at(bar)
    return f"{bar} {m.text}" if bar > 1 and m != score.meter_at(bar - 1) else str(bar)


# --- melody-major ------------------------------------------------------------


def _bar_cells(score: Score, part: Part, nbars: int) -> list[list[str]]:
    """Tokens per bar for one part, markings included; notes crossing a
    barline are split and tied (~)."""
    starts = score.barlines(nbars)
    total = starts[-1]
    placed: list[list[tuple[Fraction, int, str]]] = [[] for _ in range(nbars)]
    for t, m in part.marks(Mark):
        b = min(bisect.bisect_right(starts, t) - 1, nbars - 1)
        placed[b].append((t, 2 if t >= starts[b + 1] else 0, m.token))
    timeline: list[tuple[Fraction, Fraction, Note | None]] = []
    cur = Fraction(0)
    for t, n in part.events(merge_ties=False):  # show ties as written
        if t > cur:
            timeline.append((cur, t - cur, None))
        timeline.append((t, n.dur, n))
        cur = max(cur, t + n.dur)
    if cur < total:
        timeline.append((cur, total - cur, None))

    for start, dur, note in timeline:
        s, left = start, dur
        while left > 0:
            b = bisect.bisect_right(starts, s) - 1
            if b >= nbars:
                break
            seg = min(left, starts[b + 1] - s)
            if note is None:
                placed[b].append((s, 1, " ".join(_rest_tokens(seg))))
            else:
                last = seg == left
                # attack articulations on the first piece, a fermata on the last
                art = "".join(c for c in note.art if (c == "@" and last) or (c != "@" and s == start))
                tie = not last or note.tied
                head = "R" if note.is_rest else note.head()
                length = note.suffix() if seg == note.dur else dur_suffix(seg)
                placed[b].append((s, 1, head + length + art + ("~" if tie else "")))
            s += seg
            left -= seg
    return [[tok for _, _, tok in sorted(bar, key=lambda x: (x[0], x[1]))] for bar in placed]


def melody(score: Score, bars=None, parts=None, width: int = 4) -> str:
    first, last = _bar_range(score, bars)
    sel = _select(score, parts)
    with spelling(score.key):
        cells = {p.name: _bar_cells(score, p, max(last, score.bars)) for p in sel}
    nw = max([len(p.name) for p in sel] + [3])
    lines = [_header(score), ""]
    for chunk_start in range(first, last + 1, width):
        chunk = range(chunk_start, min(chunk_start + width, last + 1))
        texts = {name: [" ".join(c[b - 1]) for b in chunk] for name, c in cells.items()}
        widths = [max([len(_bar_label(score, b))] + [len(texts[p.name][i]) for p in sel]) for i, b in enumerate(chunk)]
        lines.append((f"{'bar':<{nw}} | " + " | ".join(_bar_label(score, b).ljust(w)
                                                      for b, w in zip(chunk, widths))).rstrip())
        for p in sel:
            lines.append(f"{p.name:<{nw}} | " + " | ".join(t.ljust(w) for t, w in zip(texts[p.name], widths)) + " |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# --- chord naming ------------------------------------------------------------

# (intervals above root, chord-symbol suffix, roman-numeral suffix, minor-ish?)
CHORDS = [
    ((0, 4, 7), "", "", False), ((0, 3, 7), "m", "", True),
    ((0, 3, 6), "dim", "°", True), ((0, 4, 8), "+", "+", False),
    ((0, 4, 7, 10), "7", "7", False), ((0, 4, 7, 11), "maj7", "maj7", False),
    ((0, 3, 7, 10), "m7", "7", True), ((0, 3, 6, 10), "m7b5", "ø7", True),
    ((0, 3, 6, 9), "dim7", "°7", True), ((0, 3, 7, 11), "mMaj7", "maj7", True),
    ((0, 4, 10), "7", "7", False), ((0, 3, 10), "m7", "7", True), ((0, 4, 11), "maj7", "maj7", False),
    ((0, 5, 7), "sus4", "sus4", False), ((0, 2, 7), "sus2", "sus2", False),
    ((0, 7), "5", "5", False),
    ((0, 4), "", "", False), ((0, 3), "m", "", True),  # root + third: read as the implied triad
]
ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII"]
INVERSIONS_TRIAD = {3: "6", 4: "6", 6: "64", 7: "64", 8: "64"}
INVERSIONS_7TH = {3: "65", 4: "65", 6: "43", 7: "43", 8: "43", 9: "42", 10: "42", 11: "42"}


def name_chord(midis: list[int], score: Score) -> tuple[str, str]:
    """('B7/D#', 'V65') for a list of sounding MIDI pitches; ('', '') if silent."""
    if not midis:
        return "", ""
    bass = min(midis) % 12
    pcs = {m % 12 for m in midis}
    if len(pcs) == 1:
        return f"({pc_name(bass)})", ""
    roots = [bass] + sorted(pcs - {bass})
    for ivs, sym, rn_sfx, minorish in CHORDS:
        for root in roots:
            if {(pc - root) % 12 for pc in pcs} == set(ivs):
                name = pc_name(root) + sym
                if root != bass:
                    name += "/" + pc_name(bass)
                return name, _roman(root, bass, ivs, rn_sfx, minorish, score)
    return "{" + " ".join(pc_name(pc) for pc in sorted(pcs, key=lambda p: (p - bass) % 12)) + "}", ""


def _roman(root, bass, ivs, sfx, minorish, score) -> str:
    if sfx == "5":
        return ""
    deg, alter = score.key.degree(root)
    rn = ROMAN[deg].lower() if minorish else ROMAN[deg]
    rn = {-1: "b", 0: "", 1: "#"}[alter] + rn
    inv = (bass - root) % 12
    if inv and not sfx.startswith("sus"):
        if len(ivs) == 4 or sfx in ("7", "ø7", "°7", "maj7"):
            fig = INVERSIONS_7TH.get(inv, "")
            sfx = sfx.replace("7", fig) if fig else sfx
        else:
            sfx += INVERSIONS_TRIAD.get(inv, "")
    return rn + sfx


def harmony_label(midis: list[int], score: Score) -> tuple[str, str, str]:
    """Every reading of the sounding pitches at once: a chord symbol (or the
    pitch classes over the bass), a roman numeral in the score's key where
    one applies, and the set class."""
    from .analysis import set_label
    sym, rn = name_chord(midis, score)
    return sym, rn, set_label(midis) if len({m % 12 for m in midis}) > 1 else ""


# --- harmony-major -----------------------------------------------------------


def _sounding(evs: list[tuple[Fraction, Note]], starts: list[Fraction], t: Fraction):
    """The (start, note) sounding at t in a part, or None."""
    i = bisect.bisect_right(starts, t) - 1
    # Normally only evs[i] can cover t; look a little further back in case
    # placements overlap (check() reports that as an error).
    for j in range(i, max(i - 8, -1), -1):
        s, n = evs[j]
        if s + n.dur > t:
            return s, n
    return None


def grid(score: Score, bars=None, parts=None, step=None, chords: bool = True) -> str:
    first, last = _bar_range(score, bars)
    sel = _select(score, parts)
    t0, t1 = score.time(first), score.time(last + 1)
    evs = {p.name: p.events() for p in score.parts}
    starts = {name: [s for s, _ in e] for name, e in evs.items()}

    times = {score.time(b) for b in range(first, last + 1)}
    for p in sel:
        for s, n in evs[p.name]:
            times.update((s, s + n.dur))
    if step:
        st = Fraction(step)
        times.update(t0 + k * st for k in range(int((t1 - t0) / st)))
    rows_t = sorted(t for t in times if t0 <= t < t1)

    with spelling(score.key):
        rows = []
        for t in rows_t:
            cells = []
            for p in sel:
                hit = _sounding(evs[p.name], starts[p.name], t)
                if hit is None or hit[1].is_rest:
                    cells.append(".")
                elif hit[0] == t:
                    cells.append(repr(hit[1]))
                else:
                    cells.append("|")
            label = ("", "", "")
            if chords:
                midis = []
                for p in score.parts:
                    hit = _sounding(evs[p.name], starts[p.name], t)
                    if hit and not hit[1].is_rest:
                        midis.extend(x.midi for x in hit[1].pitches)
                label = harmony_label(midis, score)
            rows.append((t, fmt_pos(score, t), cells, label))

    pw = max([len(r[1]) for r in rows] + [5])
    cw = [max([len(p.name)] + [len(r[2][i]) for r in rows]) for i, p in enumerate(sel)]
    sw = max([len(r[3][0]) for r in rows] + [5])
    rw = max([len(r[3][1]) for r in rows] + [2])
    head = f"{'pos':<{pw}}  " + "  ".join(p.name.ljust(w) for p, w in zip(sel, cw))
    if chords:
        head += f"  | {'chord':<{sw}}  {'rn':<{rw}}  set"
    lines = [_header(score), "", head]
    for t, pos, cells, (sym, rn, pcset) in rows:
        if score.is_barline(t):
            bar = _bar_label(score, score.position(t)[0])
            lines.append(f"-- {bar} " + "-" * max(0, len(head) - len(bar) - 4))
        row = f"{pos:<{pw}}  " + "  ".join(c.ljust(w) for c, w in zip(cells, cw))
        if chords:
            row += f"  | {sym:<{sw}}  {rn:<{rw}}  {pcset}"
        lines.append(row.rstrip())
    return "\n".join(lines) + "\n"


# --- validation & analysis ---------------------------------------------------


def _beats(score: Score, quarters: Fraction, bar: int) -> str:
    n = quarters / score.meter_at(bar).beat_len
    return f"{fmt_number(n)} beat{'' if n == 1 else 's'}"


NOTE_NAMES = {Fraction(4): "a whole note", Fraction(2): "a half note", Fraction(1): "a quarter",
              Fraction(1, 2): "an eighth", Fraction(1, 4): "a sixteenth", Fraction(1, 8): "a 32nd"}


def _amount(d: Fraction) -> str:
    """A length as a musician says it: 'an eighth (.e)', 'a dotted quarter (.qd)'."""
    for v, name in NOTE_NAMES.items():
        if d == v:
            return f"{name} ({dur_suffix(d)})"
        if d == v * Fraction(3, 2):
            return f"a dotted {name.split(' ', 1)[1]} ({dur_suffix(d)})"
    return f"{fmt_number(d)} quarter{'s' if d != 1 else ''} ({dur_suffix(d)})"


def _enters_mid_bar(score: Score, start: Fraction, motif) -> bool:
    """A motif that starts off a barline, and whose barlines each fall one
    whole bar further on counting from its own start, is an entry displaced
    against the metre (a stretto, a canon at the half bar). Its barlines
    describe its own bars, so they aren't held to the score's."""
    if score.is_barline(start):
        return False
    b0, t, k = score.position(start)[0], Fraction(0), 0
    expected = score.meter_at(b0).bar_len
    for it in motif.items:
        if isinstance(it, Note):
            t += it.dur
        elif isinstance(it, Bar) and it.number is None:
            if t != expected:
                return False
            k += 1
            expected += score.meter_at(b0 + k).bar_len
    return k > 0


def _anchor_issues(score: Score, p: Part):
    """Check each barline anchor against the one before it, so a miscounted
    bar is reported once, where it happens. After an error the check resyncs
    to the barline the writer evidently meant, instead of flagging every
    later anchor in the same placement as off by the same amount."""
    for start, motif in p.placements:
        displaced = _enters_mid_bar(score, start, motif)
        t, drift, prev = start, Fraction(0), start  # drift: error carried by earlier bad bars
        for it in motif.items:
            if isinstance(it, Note):
                t += it.dur
                continue
            if not isinstance(it, Bar) or (displaced and it.number is None):
                continue
            pos, prev_pos = t - drift, prev - drift
            if not score.is_barline(pos):
                b1 = score.position(prev_pos)[0]
                here = score.position(pos)[0]
                below, above = score.bar_start(here), score.bar_start(here + 1)
                nearest = max(above if above - pos < pos - below else below, score.bar_start(b1 + 1))
                bars = score.position(nearest)[0] - b1
                which = f"bar {b1} has" if bars == 1 else f"bars {b1}-{b1 + bars - 1} have"
                expected = nearest - prev_pos
                off = (t - prev) - expected
                yield ("ERROR", prev, p.name, f"{which} {_beats(score, t - prev, b1)}, expected "
                       f"{_beats(score, expected, b1)}: {_amount(abs(off))} too {'long' if off > 0 else 'short'} "
                       f"(the barline written at {fmt_pos(score, t)} should be at {fmt_pos(score, prev + expected)})")
                drift += pos - nearest
                pos = nearest
            if it.number is not None and pos != score.time(it.number):
                yield ("ERROR", t, p.name, f"Bar({it.number}) anchor is at the start of bar {score.position(pos)[0]}, "
                       f"not bar {it.number}")
            prev = t


def _marking_issues(score: Score, p: Part):
    """Hairpins that never reach an end, and pedal lifts with no pedal down."""
    hairpin, down = None, False
    for t, m in p.marks(Mark):
        if m.kind in ("cresc", "dim"):
            hairpin = (t, m)
        elif m.kind == "end" or (m.kind == "dyn" and m.value not in ("sf", "sfz", "rfz")):
            if m.kind == "end" and hairpin is None:
                yield ("WARN", t, p.name, "hairpin end (!) with no hairpin open")
            hairpin = None
        elif m.kind == "ped":
            down = True
        elif m.kind == "pedup":
            if not down:
                yield ("WARN", t, p.name, "pedal lift (*) with no pedal down")
            down = False
    if hairpin:
        yield ("NOTE", hairpin[0], p.name, f"hairpin {hairpin[1].token} runs to the end of the piece "
               f"(no dynamic or ! after it)")


def _issues(score: Score) -> list[tuple[str, Fraction, str, str]]:
    """(level, time, where, message) for everything check() reports."""
    out = []
    for p in score.parts:
        out.extend(_anchor_issues(score, p))
        out.extend(_marking_issues(score, p))
        # overlaps and range
        lo, hi = p.range
        end, prev = Fraction(0), None
        for t, n in p.events():
            if n.is_rest:
                continue
            if t < end:
                out.append(("ERROR", t, p.name, f"{n!r} overlaps {prev!r}, which sounds until {fmt_pos(score, end)} "
                            f"(a part is one line; for a second voice on this staff use {p.name}.voice(name))"))
            if t + n.dur > end:
                end, prev = t + n.dur, n
            for x in n.pitches:
                if x < lo or x > hi:
                    out.append(("WARN", t, p.name, f"{x} is {'below' if x < lo else 'above'} the {p.instrument} range {lo}..{hi}"))
    if not score.is_barline(score.end):
        out.append(("NOTE", score.end, "-", f"last bar ({score.bars}) is incomplete: music ends at {fmt_pos(score, score.end)}"))
    order = {"ERROR": 0, "WARN": 1, "NOTE": 2}
    out.sort(key=lambda x: (order[x[0]], x[1]))
    return out


def lens(score: Score, bars=None, parts=None, kinds=None) -> str:
    """What the voices are doing, bar by bar: dissonances named by how they
    move (passing, suspension m7->M6, appoggiatura ...), parallel fifths and
    octaves, crossings. Descriptive only; see analysis.observe(). `kinds`
    keeps only observations whose name contains one of the given words."""
    from .analysis import observe
    first, last = _bar_range(score, bars)
    t0, t1 = score.time(first), score.time(last + 1)
    obs = [o for o in observe(score) if t0 <= o.t < t1
           and (not parts or any(n in o.where.split("/") for n in parts))
           and (not kinds or any(k in o.kind for k in kinds))]
    lines = [_header(score), ""]
    if not obs:
        return "\n".join(lines + ["(nothing to note: consonant throughout)"]) + "\n"
    pw = max(len(fmt_pos(score, o.t)) for o in obs)
    ww = max(len(o.where) for o in obs)
    kw = max(len(o.kind) for o in obs)
    bar = None
    for o in obs:
        b = score.position(o.t)[0]
        if b != bar:
            label = _bar_label(score, b)
            lines.append(f"-- {label} " + "-" * max(0, 40 - len(label)))
            bar = b
        lines.append(f"{fmt_pos(score, o.t):<{pw}}  {o.where:<{ww}}  {o.kind:<{kw}}  {o.detail}")
    return "\n".join(lines) + "\n"


def check(score: Score) -> str:
    """Is the score what you meant to write? Errors (bar anchors, overlaps),
    warnings (instrument ranges, unclosed hairpins, stray pedal lifts) and
    notes (an incomplete last bar). Musical observations are in lens()."""
    issues = _issues(score)
    secs = score.seconds(score.end)
    lines = [_header(score),
             f"{score.bars} bars, {len(score.parts)} parts, {int(secs // 60)}:{int(secs % 60):02d}", ""]
    if not issues:
        lines.append("ok: no problems found")
    ww = max([len(w) for _, _, w, _ in issues] + [4])
    pw = max([len(fmt_pos(score, t)) for _, t, _, _ in issues] + [3])
    for level, t, where, msg in issues:
        lines.append(f"{level:<5}  {fmt_pos(score, t):<{pw}}  {where:<{ww}}  {msg}")
    counts = {lv: sum(1 for x in issues if x[0] == lv) for lv in ("ERROR", "WARN", "NOTE")}
    if issues:
        lines += ["", ", ".join(f"{v} {k.lower()}{'s' if v != 1 else ''}" for k, v in counts.items())]
    return "\n".join(lines) + "\n"


def has_errors(score: Score) -> bool:
    return any(level == "ERROR" for level, *_ in _issues(score))
