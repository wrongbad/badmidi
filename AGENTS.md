# AGENTS.md: composing with badmidi

Everything you need to write, check, hear and engrave a piece without reading
the source. The README says what the project is for; this file says how to
use it.

## Setup

```
python -m badmidi piece.py check          # works from the repo root without installing
pip install -e .                          # optional: gives the `badmidi` command
python -m unittest discover tests         # the suite; engraves and verifies every example
```

Pure stdlib Python ≥ 3.10. `pdf`/`png` need `lilypond`; `wav` needs
`fluidsynth` and a General MIDI soundfont (MuseScore's is found
automatically, or set `BADMIDI_SOUNDFONT=/path/to/font.sf2`).

## The loop

A piece is a Python file that builds a `Score` named `score`.

1. Write or edit `piece.py`.
2. `badmidi piece.py check`: fix every ERROR. Errors are about notation, not
   taste: miscounted bars, wrong bar anchors, overlapping notes in one part.
   Fix the first error in a part first; the rest are often the same miscount.
3. `badmidi piece.py grid --bars 9-16`: read the harmony. Every row is an
   onset, labelled with chord symbol, roman numeral and set class.
4. `badmidi piece.py lens --bars 9-16`: read the counterpoint: each
   dissonance named by how it moves, plus parallels and crossings. It's a
   description, not a list of things to fix. Decide for yourself.
5. `badmidi piece.py pdf`: engraves and proves it. LilyPond's own MIDI of
   the engraving must match the score note for note, and any LilyPond warning
   fails the run. If it says "verified", the PDF is right and you don't need
   to look at it. (`png` writes page images if you want to look anyway.) The
   LilyPond source is left as `piece.ly` only when something fails, for
   debugging; `badmidi piece.py ly` prints it any time.
6. `badmidi piece.py wav` and `midi`.

You can't hear the audio, so do your listening through `grid` and `lens`.
When you report on a piece, say which checks you ran, and say that the audio
is unheard.

## Skeleton

```python
"""Title -- for instrument(s).

    1-8    what happens in these bars
    9-16   ...
"""
from badmidi import *

K = key("D minor")
score = Score("Title", composer="badmidi", meter=(4, 4), key=K, tempo=72,
              tempo_text="Andante")
rh, lh = score.piano()                     # or score.part("violin"), score.organ(), ...

# --- material: name the ideas, develop them by transformation ---------------
theme = M("D4.q F4.q A4.h | G4.q F4.e E4.e D4.h |")
answer = theme.transpose(4, scale=K)

# --- placement: every passage at an explicit bar ------------------------------
rh.at(1, theme, answer, Bar(5))
lh.at(1, "D3.w | A2.w | D3.w | A2.w |5")

# --- markings, tempo -----------------------------------------------------------
rh.mark(1, "p", '"dolce"')
score.rit(7, 9, to=60)
```

Read the examples in `examples/` for full pieces (see the end of this file).

## Notation: one spelling for Python and strings

A token in a string is spelled exactly like the Python value and like the
views print it, so view output can be pasted back as input.

| Python | string | meaning |
|---|---|---|
| `C4`, `Fs4`, `Bb3` | same, or `F#4` | pitch; C4 = middle C; `s`/`#` sharp, `b` flat |
| `E4.q` | `E4.q` | `w h q e s t` = whole … 32nd |
| `E4.qd` | `E4.qd` | dotted |
| `E4.e3` | `E4.e3` | triplet eighth |
| `E4.s5`, `E4.e7` | same | any tuplet: n in the time of the power of two below n |
| | `E4.q5:3`, `E4.q2:3` | explicit ratio (5 in 3; a duplet in 6/8); printed and engraved as written |
| `E4 * 1.5` | `E4*1.5`, `E4*(5/3)` | any length in quarter notes |
| `R.q`, `R * 3` | `R.q`, `R*3` | rest |
| `(C4 & E4 & G4).h` | `[C4 E4 G4].h` | chord |
| `E4.h.tie` | `E4.h~` | tie into the next note of the same pitch |
| `E4.q.accent` … | `E4.q>` `^` `'` `_` `@` | accent, marcato, staccato, tenuto, fermata |
| `BAR`, `Bar(14)` | `\|`, `\|14` | checked barline; "this is the start of bar 14" |
| `E4 + 7`, `B4 - E4` | | pitch + semitones; interval in semitones |

Each token is complete in itself: its own octave and duration, nothing
carried over from the previous one. Whitespace is free, so you can line
voices up bar by bar (`examples/chorale.py`). A parse error names the token
and the bar of the string it's in. Use strings for note-level passages and
Python values for ideas you'll transform; they mix freely:
`vla.at(5, "E4.w |", answer.octave(-1), "|7")`.

**Put `|` in every string and `|N` at section ends.** That is how `check`
catches a miscounted bar, which is the most common mistake. In practice it
happens all the time, especially with dotted values and tuplets.

## Markings

Markings sit in time like notes. Write them inline (they travel with the
motif) or place them with `mark()`:

```python
rh.at(19, 'p "cantabile" C5.hd Eb5.q | Ab5.h < G5.q F5.q | F5.h f Eb5.q Db5.q |')
lh.at(19, "ped Ab1.e Eb2.e ... | ped ... | *")
rh.mark(27, '"cresc. poco a poco"', "<")      # bar 27, beat 1
rh.mark(6, ">", beat=3)
```

| string | Python | |
|---|---|---|
| `ppp` … `fff`, `sf` `sfz` `fp` `rfz` | `dyn("p")` | dynamics |
| `<` `>` | `CRESC`, `DIM` | hairpin, running to the next dynamic (or to the end) |
| `!` | `HAIRPIN_END` | end a hairpin with no new dynamic |
| `ped` `*` | `PED`, `PED_UP` | pedal down (or change); up |
| `"con fuoco"` | `text("con fuoco")` | expression text; next to a dynamic it prints as "p dolce" |

Parts in one group (a piano's hands, an accordion's manuals) share dynamics
and pedal, so mark them on one part only.

Registration (organ stops, accordion reeds) is printed above the staff and
can switch the playback program: `rh.registration(17, "Gt.: + Mixture", "rock organ")`;
leave out the program to keep the current sound.

## Score, parts, time

```python
score = Score(title, meter=(4, 4), tempo=100, key="C major", tempo_text=None, composer=None)
p = score.part("violin")                       # instrument taken from the name
p = score.part("melody", "flute")              # or given
p = score.part("rh", "reed organ", group="Accordion", clef="treble", range=(E3, A6))
rh, lh = score.piano()                         # grand staff, one MIDI channel
alto = rh.voice("alto")                        # a second line on rh's staff, same instrument and channel
rh, lh, ped = score.organ()                    # two manuals + pedal with a 16' coupler
```

Part keywords:
- `group`: braced together, sharing dynamics and pedal.
- `staff`: share a staff as voices.
- `clef`: `"treble"`, `"bass"`, `'"treble_8"'`.
- `range`: overrides the instrument's range for warnings.
- `balance`: a velocity offset, to bring out a line.
- `couplers=(0, -12)`: extra octaves in playback.
- `channel`: share a MIDI channel.
- `pan`.

Instruments:
- **keyboards:** piano, harpsichord, celesta, organ, pedal, drawbar organ, percussive organ, rock organ, reed organ
- **pitched percussion:** glockenspiel, vibraphone, marimba
- **plucked:** guitar, bass guitar, harp
- **strings:** violin, viola, cello, contrabass, strings
- **voices:** choir, soprano, alto, tenor, bass
- **brass:** trumpet, trombone, tuba, horn
- **woodwinds:** oboe, english horn, bassoon, clarinet, piccolo, flute, recorder

For anything else, use the nearest sound and set `range=` (the fantasia's
free-bass accordion is a reed organ with accordion ranges).

Placing music:

```python
p.at(5, theme)                    # bar 5, beat 1
p.at(5, theme, beat=3)            # beat 3 (beats are the meter's: eighths in 7/8)
p.at(5, a, b, "E4.w |", Bar(9))   # several arguments run on, one after another
p.then(answer)                    # straight after the last placement
```

Each argument to `at()`/`then()` is checked on its own. A motif that starts
mid-bar (a stretto entry, a canon at the half bar) keeps its own barlines,
checked as whole bars from where it starts, so this is fine if `answer` is
two whole bars: `bass.at(17, answer, "E2.h | Fs2.h G2.h |", beat=3)`.
Numbered anchors (`|23`, `Bar(23)`) are always absolute. To drop a motif's
barlines entirely: `m.unbarred()`.

A part is one line: its notes can't overlap. For two voices on one staff
(a fugue in the right hand, a held note under a moving one) give the second
voice its own part with `rh.voice("alto")`.

Tempo and meter are score-level:

```python
score.tempo_mark(19, "poco meno mosso", 88)
score.rit(45, 47, to=66)                   # also accel(); a position is a bar or (bar, beat)
score.meter_change(9, "3/4")               # also (3, 4), "6/8"
score.meter_change(13, "2+2+3/8")          # additive: printed 2+2+3 over 8, grouped that way
score.free_bar(20, 11)                     # unmetered bar of 11 quarters; then the meter resumes
```

Time is in quarter notes, as exact `Fraction`s.
- `score.time(bar, beat)` gives the time of a bar and beat, and `score.position(t)` gives `(bar, beat)` back.
- `score.where(t)` formats a time as `"12:3"`.
- `score.bar_start(bar)` and `score.meter_at(bar)` give each bar's start and meter.
- `score.metric_level(t)`: 3 is a downbeat, 2 another strong beat, 1 a pulse, 0 a beat, -1 between beats.

Strong beats are:
- the downbeat
- beat 3 of a four-beat bar
- every group start in additive and compound meters
- every beat in half-note meters

## Motifs

`M(...)` takes strings, notes, motifs and lists, flattened. `a + b`
concatenates; `m * 3` repeats; `m[0]`, `m[:2]` index notes; `m.text()` and
`repr(m)` give string notation back; `m.dur`, `m.pitches`, `m.notes`.

| transformation | |
|---|---|
| `transpose(n)` / `transpose(n, scale=K)` | semitones (spelled as one interval) / scale steps (alterations kept) |
| `octave(n)` | n octaves (keeps written spelling) |
| `invert(around=A4)` / `invert(around=E4, scale=K)` | chromatic / diatonic mirror |
| `unbarred()` | the same music without its barline anchors |
| `retrograde()` | reversed (drops dynamics, hairpins, pedal, text) |
| `augment(2)`, `diminish(2)` | scale durations |
| `fragment(0, 2)` | notes 0..1 |
| `sequence([-1, -1], scale=K)` | the motif, then copies each shifted from the last |
| `double(-12)`, `double(12, 24)` | add the pitches again at intervals |
| `rhythm(1, .5, .5)` / `rhythm(other)` | new durations, same pitches (cycled) |
| `with_pitches(E4, G4)` / `with_pitches(other)` | new pitches, same rhythm (cycled) |
| `map(fn)`, `map_pitches(fn)` | anything else |

```python
isorhythm("C4 D4 F4 G4 A4", [1, .5, .5, 2])    # color over talea, until both cycles end together
isorhythm(theme, M("C4.q R.e C4.e C4.h"), notes=12)   # a rest in the talea uses up no pitch
```

Keys: `key("E minor")`, `key("Bb major")`, `key("D dorian")`, `key("F#m")`
(also phrygian, lydian, mixolydian, locrian, harmonic/melodic minor).

**Spelling.** Pitches you write keep your spelling, and transformations
spell the way a musician would:
- A chromatic `transpose(n)` spells the whole motif as one interval, whichever
  needs fewer accidentals: C G A F up 6 is F# C# D# B (an augmented fourth),
  not Gb Db Eb Cb.
- `invert()` mirrors letter names around the axis.
- Diatonic steps are spelled as the scale spells them.
- Octave shifts keep your spelling.

Only bare arithmetic (`E4 + 7`) and chords named by pitch class fall back to
the score's key.

A chromatic inversion around a point between two notes: invert around a
note, then transpose, e.g. `invert(around=A4).transpose(-9)` mirrors C↔A.

## Views

`badmidi piece.py VIEW [--bars 5-8] [--parts rh,lh]`

- **melody** (default): one line per part, bars in aligned columns, markings
  inline, bars labelled where the meter changes. Every row is valid string
  notation.
- **grid**: time down, parts across. `|` means still sounding, `.` silent;
  `--step e` adds a fixed grid. Each row ends with chord symbol, roman numeral
  (when the chord is tonal) and set class:
  `E+  II+  3-12 (048) augmented`.
- **check**: notation only. Errors: bar anchors, overlaps. Warnings: ranges,
  stray pedal lifts. Notes: an incomplete last bar, a hairpin that runs to the end.
- **lens**: what the voices are doing (below). `--kinds susp,parallel` filters.
- **pdf / png / ly**: engraving (see the loop).
- **midi / wav / all**.

In Python these are `score.melody()`, `score.grid()`, `score.check()` and
`score.lens()`, and `score.observe()` returns the lens as `Observation`
objects with `.t`, `.where`, `.kind` and `.detail`.

## The lens

The lens describes and never prescribes. It names dissonances (seconds,
sevenths, tritones, a fourth above the bass) by how the dissonant note
moves:

| kind | |
|---|---|
| passing / neighbour | stepped into and out of, onward / back |
| appoggiatura | leapt into, stepped out of |
| escape tone | stepped into, leapt out of |
| anticipation | stepped into, then repeated |
| free dissonance | leapt into and out of |
| unresolved | nothing follows (a rest, the end) |
| suspension `m7->M6` | held into a strong beat, then down a step, with the figures |
| retardation | held, then up a step |
| held dissonance | held into a strong beat and not moved by step |
| accented … | the above, on a strong beat |
| parallel fifths / octaves, voices cross | the top of a part against the bottom of each part below it |

Use it to see what you made: whether the canon really lands its
suspensions, where the bass and soprano move in fifths, whether a
"dissonant" passage is all passing motion. Then choose. It applies no
style's rules and has no idea which ones you want.

Pitch-class sets work on pitches or integers:

```python
prime_form([C4, E4, Gs4])        # (0, 4, 8)   Rahn's algorithm
set_label([0, 4, 7, 6, 10, 1])   # '6-30 (013679) Petrushka'   Forte number, prime form, nickname
interval_vector([0, 1, 4, 6])    # (1, 1, 1, 1, 1, 1)
normal_order([9, 0, 4])          # (9, 0, 4)
```

## Stretto search

```python
found = stretti(subject, intervals=(12, 7, 5, -12), offsets=None, scale=None,
                meter=(4, 4), follower=None)
print(found)              # every offset × interval, with what the lens sees in the overlap
calm = [s for s in found if not s.count("parallel") and s.count("free") == 0]
calm[0].place(soprano, alto, 17)       # subject at bar 17 in the soprano, the copy in the alto
```

- offsets are in quarter notes; by default every beat while the voices overlap.
- with `scale=`, intervals are scale steps.
- `follower=lambda m: m.invert(scale=K)` searches for stretti of the inversion,
  and any transformation works.
- each result has `.offset`, `.interval`, `.leader`, `.follower`,
  `.observations`, `.summary()`, `.count(kind)` and `.place(a, b, bar, beat)`.

## Things that bite

- **Miscounting a bar** is the usual error, and no tool can prevent it. Put
  `|` in every string and `|N` at section ends, and `check` reports each
  miscount once with the fix:
  "bar 5 has 8 beats, expected 7 beats: an eighth (.e) too long (the barline
  written at 6:2 should be at 6:1)". Beats are the meter's own (eighths in
  7/8), and a free bar's beats are quarters.
- `retrograde()` drops dynamics, hairpins, pedal and text, because they have
  no meaningful reverse. Put them back with `mark()`.
- `invert(around=...)` needs a pitch for its axis. To mirror around the point
  between two notes, invert around one and transpose (see Spelling).

## Adding an example

Examples in `examples/` are part of the test suite. Each must define
`score`, pass `check` with no errors, engrave and verify, and survive a
round trip through the melody view. Start it with a docstring that lists
what happens in which bars, and the commands worth running. Keep the `.py`,
`.pdf` and `.mid` (`.wav` is git-ignored); delete any `png` pages you made
to look at. Run `python -m unittest discover tests`.

| example | shows |
|---|---|
| `chorale.py` | four voices lined up bar by bar in strings; read it with `grid` |
| `round.py` | one motif at staggered entries; an augmented canon voice |
| `theme_and_answer.py` | a quartet developed from one four-note idea by transformation |
| `prelude.py` | piano: figuration functions, pedal, dynamics, tempo changes |
| `funk_chaconne.py` | organ: a ground bass sequenced into variations, a fugue, registration |
| `hexachord_fantasia.py` | free-bass accordion: cantus firmus, canon at the 7th, a tritone-answer ricercar with stretto entries mid-bar, divisions on a ground, set-class harmony |
| `bent_chaconne.py` | violin and two cellos: a ground drifting against itself by isorhythm, a 7/8 variation, a mirror variation by inversion, a mensuration canon of the ground, a free-bar cadenza |
| `wandering_ricercar.py` | clarinet, tenor and baritone sax: modal imitation chosen with `stretti`, generated fauxbourdon in several modes, a galliard on chromatic-mediant chords, additive meters and hemiola throughout |

## Where things live

```
badmidi/core.py      Pitch, Chord, Note, R, Bar, Mark, Motif and its transformations,
                     the string parser, duration codes, isorhythm
badmidi/scale.py     key(), Scale: diatonic steps, signatures, spelling, degrees
badmidi/notes.py     C0..G9 constants
badmidi/score.py     Score, Part, Meter, the instrument table, time and meter maps
badmidi/views.py     melody, grid, check, lens; chord naming
badmidi/analysis.py  observe() (the lens), pitch-class sets, stretti()
badmidi/perform.py   markings -> playback: dynamics, hairpins, accents, tempo map, pedal
badmidi/midi.py      Standard MIDI File writer and reader
badmidi/lilypond.py  LilyPond export, rendering, and verification against LilyPond's MIDI
badmidi/render.py    wav through fluidsynth
badmidi/cli.py       the badmidi command
```

What's printed and what's played are separate. Changing `perform.py`
(velocities, ramps, staccato length, fermata holds, pedal timing) never
changes the score.
