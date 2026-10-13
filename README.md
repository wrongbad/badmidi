# badmidi

Music as code. Motifs are values, development is functions applied to them,
and the score comes back to you as text you can check: a melody-major view,
a harmony-major grid, a validator. Out the other end: sheet music (LilyPond),
MIDI and audio. Pure stdlib; LilyPond and fluidsynth for PDF and WAV.

```python
from badmidi import *

theme  = M("E4.q G4.e A4.e B4.h")
answer = theme.invert(around=A4).transpose(5)
bridge = theme.augment(2).fragment(0, 2).sequence([-1, -1], scale=key("E minor"))

score = Score("Sketch", meter=(4, 4), tempo=80, key="E minor")
score.part("violin").at(1, theme, answer, Bar(3), bridge)
score.part("cello").at(3, theme.octave(-2))
score.part("viola").at(5, "B3.h [E4 G4].h | Fs4.w~ | Fs4.h R.h |8")
```

```
badmidi sketch.py                  # melody-major view (default)
badmidi sketch.py grid --bars 5-8  # harmony-major view, with chords + roman numerals
badmidi sketch.py check            # validation + voice-leading notes
badmidi sketch.py midi             # -> sketch.mid
badmidi sketch.py wav              # -> sketch.wav (fluidsynth + GM soundfont)
badmidi sketch.py pdf              # -> sketch.pdf sheet music (LilyPond), plus sketch.ly
badmidi sketch.py png              # -> page images
badmidi sketch.py ly               # print the LilyPond source
badmidi sketch.py all              # check + melody + grid + .mid
```

`python -m badmidi ...` works without installing. The piece file must define
a `Score` called `score` (or pass `--score NAME`).

## Workflow: why there's no need to look at the PDF

1. Edit `piece.py`; run `check` until clean (bar anchors, ranges, overlaps,
   hairpins, parallels and crossings).
2. Run `pdf`. Engraving is *proven*, not eyeballed: LilyPond also writes MIDI
   from the same source, and every note in it must match the score (pitch,
   onset, length; staccato notes on onset and pitch). Any LilyPond warning,
   or any difference, is an error that names the note and bar.
3. Listen to the `wav`.

Engraving conventions are rules in the exporter, not things to check by eye:
an 8va/8vb sign for bars far off the staff, text set beside a coinciding
dynamic ("p dolce"), duplicate registration labels merged, bracket pedals,
octave-treble clef for tenor. The exporter itself is covered by
`python -m unittest discover tests`, which also engraves and verifies every example.

## Notes: two spellings of one notation

Notes can be Python values or tokens in a string. A token is spelled exactly
like the Python value, and like the views print it, so output can be pasted
back in as input.

| Python                    | string             | means                                   |
|---------------------------|--------------------|-----------------------------------------|
| `C4`, `Fs4`, `Bb3`        | same, or `F#4`     | pitches; C4 = middle C, `s`/`#` sharp, `b` flat |
| `E4.q`                    | `E4.q`             | quarter: `w h q e s t` (whole ... 32nd) |
| `E4.qd`, `E4.e3`          | `E4.qd`, `E4.e3`   | dotted quarter; eighth-note triplet     |
| `E4 * 1.5`                | `E4*1.5`, `E4*(5/3)` | any length in quarter notes           |
| `R.q`, `R * 3`            | `R.q`, `R*3`       | rests                                   |
| `(C4 & E4 & G4).h`        | `[C4 E4 G4].h`     | chord                                   |
| `E4.h.tie`                | `E4.h~`            | tie into the next note of the same pitch |
| `BAR`, `Bar(14)`          | `\|`, `\|14`       | checked barline; start of bar 14        |
| `E4.q.accent` ...         | `E4.q>`            | articulations: `>` accent, `^` marcato, `'` staccato, `_` tenuto, `@` fermata |
| `E4 + 7`, `B4 - E4`       |                    | pitch + semitones; interval in semitones |

Strings have no hidden state: every note has its own octave and duration,
and nothing carries over from the previous token. That makes them less terse
than ABC or LilyPond, but a typo can only break the note it's in. Parse errors
point at the token and say which bar of the string it's in. Whitespace is free,
so voices can be lined up bar by bar (see `examples/chorale.py`).

Use strings for note-level passages and Python for ideas and their development.
They mix freely: `vla.at(5, "E4.w |", answer.octave(-1), "|7")`.

## Markings, as on a printed score

Markings are anchored in time like notes, not attached to notes as MIDI
values. They go inline in a motif (and travel with it) or at a position:

```python
rh.at(19, 'p "cantabile" C5.hd Eb5.q | Ab5.h < G5.q F5.q | F5.h f Eb5.q Db5.q |')
lh.at(19, "ped Ab1.e Eb2.e Ab2.e C3.e Eb3.e C3.e Ab2.e Eb2.e | ped ... | *")
rh.mark(27, '"cresc. poco a poco"', "<")      # no notes: bar 27, beat 1
rh.mark(6, ">", beat=3)
```

| string             | Python                  |                                              |
|--------------------|-------------------------|----------------------------------------------|
| `ppp` ... `fff`, `sf` `sfz` `fp` `rfz` | `dyn("p")` | dynamics                              |
| `<`  `>`           | `CRESC`, `DIM`          | hairpin; runs to the next dynamic (its target) |
| `!`                | `HAIRPIN_END`           | end a hairpin without a new dynamic          |
| `ped`  `*`         | `PED`, `PED_UP`         | pedal down (or change, if already down); up  |
| `"con fuoco"`      | `text("con fuoco")`     | expression text                              |

Tempo is score-level, like the marks above the top staff:

```python
score = Score(..., tempo=100, tempo_text="Allegro agitato")
score.tempo_mark(19, "poco meno mosso", 88)
score.rit(45, 47, to=66)              # also accel(); positions are bar or (bar, beat)
```

`score.piano()` returns the two hands of a grand staff. Parts in one group
(both hands) share dynamics and pedal and print them once, between the
staves. More parts can share a staff as voices:
`score.part("rh2", "piano", group="Piano", staff="rh")`.

## Performance

`perform.py` decides what the markings mean in playback: velocity levels for
each dynamic, linear ramps along hairpins, accents, staccato length, fermata
holds, tempo ramps, pedal timing, a small metric accent. Changing those numbers
never changes the printed score. The only performance setting on a part is
`part.balance`, a velocity offset to bring out a melody.

## Motifs

`M(...)` takes strings, notes, other motifs and lists, flattened. `a + b`
concatenates, `m * 3` repeats. Indexing and slicing work on notes: `theme[0]`,
`theme[:2]`. `repr(m)` and `m.text()` give string notation back.

| transformation                        |                                            |
|---------------------------------------|--------------------------------------------|
| `transpose(n)` / `transpose(n, scale=k)` | semitones / scale steps                 |
| `octave(n)`                           | n octaves                                  |
| `invert(around=A4, scale=None)`       | mirror (chromatic, or diatonic in `scale`) |
| `retrograde()`                        | reverse (drops dynamics/pedal marks)       |
| `augment(2)`, `diminish(2)`           | scale durations                            |
| `fragment(0, 2)`                      | notes 0..1 (Python slice semantics)        |
| `sequence([-1, -1], scale=k)`         | motif, then copies each shifted from the last |
| `double(-12)`, `double(12, 24)`       | add the pitches again at intervals (octaves) |
| `rhythm(1, .5, .5)` / `rhythm(other)` | new durations, same pitches                |
| `with_pitches(E4, G4)` / `(other)`    | new pitches, same rhythm                   |
| `map(fn)`, `map_pitches(fn)`          | anything else                              |

Keys: `key("E minor")`, `key("Bb major")`, `key("D dorian")`, `key("F#m")`.
Pitches print as you wrote them (`Bb3` stays `Bb3`). Computed pitches are
spelled from the key: in C minor you get B and F# rather than Cb and Gb, and
Db for the Neapolitan.

## Placing music: explicit anchors

```python
vc = score.part("cello")            # instrument from the name, or score.part("bass line", "cello")
vc.at(5, theme)                     # bar 5, beat 1
vc.at(5, theme, beat=3)             # bar 5, beat 3
vc.then(answer)                     # straight after the last placement
```

Inside a motif, `|` / `BAR` asserts "a barline falls here" and `|14` /
`Bar(14)` asserts "this is the start of bar 14". `check` measures each bar
against the previous barline. A miscount is reported once, where it happens
("bar 2 has 3.5 beats, expected 4"), and the check then resyncs, so it doesn't
cascade into every later bar.

## Views

- **melody**: one line per part, bars in aligned columns, markings inline. Each
  row is valid string notation; notes crossing a barline are split and tied with `~`.
- **grid**: time runs down, parts run across. A row at every onset (add `--step e`
  for a fixed grid). `|` = still sounding, `.` = silent. The right-hand columns name the
  sounding chord and its roman numeral in the score's key.
- **check**: errors (misplaced bar anchors, overlapping notes in one part), warnings
  (out of instrument range, hairpins never closed, pedal lifts with no pedal down),
  notes (parallel fifths/octaves and crossings between the top of each part and the
  bass of the parts below it; `--no-voice-leading` to skip).
- **pdf / png / ly**: engraved score. Notes are split at barlines and into printable
  values with ties, triplets get brackets, and dynamics sit between the piano staves
  with pedal brackets below.

## Layout

```
badmidi/core.py    Pitch, Chord, Note, R, Bar/BAR, Mark, Motif + transformations, string parser
badmidi/scale.py   Scale / key(): diatonic steps, key signatures, spelling, degrees
badmidi/notes.py   C0..G9 constants
badmidi/score.py   Score, Part, instrument table (GM program + range)
badmidi/views.py   melody, grid, check, chord naming
badmidi/perform.py markings -> playback: dynamics curves, tempo map, pedal
badmidi/midi.py    Standard MIDI File writer
badmidi/lilypond.py sheet music export, rendering, and verification against LilyPond's MIDI
badmidi/render.py  wav via fluidsynth (soundfont: $BADMIDI_SOUNDFONT or MuseScore's)
badmidi/cli.py     the `badmidi` command
examples/          demo pieces
tests/             unittest suite
```
