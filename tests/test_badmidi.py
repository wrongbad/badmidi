"""badmidi test suite.  Run with:  python -m unittest discover tests

Covers the notation (pitches, durations, string parser, transformations,
spelling), the score model (time, anchors, ties, checks), the performance
layer (dynamics, tempo, pedal, couplers), the MIDI and LilyPond writers, and
the example pieces (they must pass check and survive a melody-view round trip).
"""
import shutil
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

import badmidi as bm
from badmidi import (A4, B3, B4, Bb3, C4, C5, D3, D5, E4, E5, G4, G5, M, R, Score,
                     key, spelling)
from badmidi.cli import load_score
from badmidi.core import NotationError, Pitch
from badmidi.lilypond import EngraveError, engrave, lilypond, score_notes, verify
from badmidi.midi import midi_bytes, read_notes
from badmidi.perform import Dynamics, LEVELS, HAIRPIN_STEP, PEDAL_LIFT, pedal_events, tempo_map
from badmidi.views import _bar_cells, _issues, has_errors

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def issues(score, level=None, voice_leading=False):
    return [i for i in _issues(score, voice_leading) if level is None or i[0] == level]


class TestPitches(unittest.TestCase):
    def test_constants_and_arithmetic(self):
        self.assertEqual(E4.midi, 64)
        self.assertEqual(E4 + 7, B4)
        self.assertEqual(B4 - E4, 7)
        self.assertEqual(Pitch.parse("F#4").midi, 66)
        self.assertEqual(Pitch.parse("Fs4"), Pitch.parse("Gb4"))

    def test_written_spelling_is_kept(self):
        self.assertEqual(repr(Bb3), "Bb3")
        self.assertEqual(Pitch.parse("B#3").midi, 60)
        self.assertEqual(Pitch.parse("B#3").name, "B#3")
        self.assertEqual(Pitch.parse("Cb4").name, "Cb4")
        self.assertEqual(repr(M("Ds4.q As3.q").octave(1).pitches), "[Ds5, As4]")   # octaves keep it
        self.assertEqual(Pitch.parse("Ds4") + 3, Pitch.parse("Fs4"))
        self.assertIsNone((Pitch.parse("Ds4") + 3).spell)                          # other intervals don't

    def test_key_spelling_of_computed_pitches(self):
        with spelling(key("C minor")):
            self.assertEqual(str(C4 + 6), "F#4")
            self.assertEqual(str(C4 + 1), "Db4")
            self.assertEqual(str(C4 + 11), "B4")
        self.assertEqual(key("C minor").names,
                         ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"])
        self.assertIn("F##", key("G# minor").names)

    def test_key_signatures(self):
        self.assertEqual(key("Bb major").signature, -2)
        self.assertEqual(key("F# minor").signature, 3)
        self.assertEqual(key("D dorian").signature, 0)
        self.assertTrue(key("Em").minor)


class TestDurations(unittest.TestCase):
    def test_codes(self):
        self.assertEqual(E4.q.dur, 1)
        self.assertEqual(E4.qd.dur, Fraction(3, 2))
        self.assertEqual(E4.e3.dur, Fraction(1, 3))
        self.assertEqual((E4 * 1.5).dur, Fraction(3, 2))
        self.assertEqual(E4.q.dot.dur, Fraction(3, 2))

    def test_pitch_without_duration_is_an_error(self):
        with self.assertRaises(TypeError):
            M(E4, G4.q)


class TestParser(unittest.TestCase):
    def test_strings_equal_python(self):
        self.assertEqual(M("E4.q G4.e A4.e B4.h"), M(E4.q, G4.e, A4.e, B4.h))
        self.assertEqual(M("[C4 E4 G4].h").notes[0].pitches, (C4, E4, G4))
        self.assertEqual(M("R.q").notes[0].is_rest, True)

    def test_ties_and_articulations(self):
        n = M("E4.q>'~").notes[0]
        self.assertTrue(n.tied)
        self.assertEqual(n.art, ">'")
        self.assertEqual(E4.q.accent.staccato, n.with_tied(False))

    def test_marks(self):
        kinds = [(m.kind, m.value) for m in M('p < E4.q ! "dolce" ped E4.q *').items if isinstance(m, bm.Mark)]
        self.assertEqual(kinds, [("dyn", "p"), ("cresc", None), ("end", None),
                                 ("text", "dolce"), ("ped", None), ("pedup", None)])

    def test_text_and_repr_round_trip(self):
        m = M('p "con fuoco" E4.q> G4.e\' A4.e < B4.h_~ | B4.q ff ped [C4 E4].h^ * R.q@ ! |14')
        self.assertEqual(M(m.text()), m)
        self.assertEqual(eval(repr(m), vars(bm)), m)

    def test_errors_point_at_the_token(self):
        for bad in ["E4.x", "H4.q", "R.q~", "E4", "[ ].h", "E4.q%"]:
            with self.assertRaises(NotationError, msg=bad):
                M(bad)
        with self.assertRaises(NotationError) as cm:
            M("E4.q | H4.q")
        self.assertIn("in bar 2", str(cm.exception))


class TestTransformations(unittest.TestCase):
    theme = M("E4.q G4.e A4.e B4.h")

    def test_invert_transpose(self):
        self.assertEqual(self.theme.invert(around=A4).transpose(5).pitches,
                         [G5, E5, D5, C5])

    def test_diatonic(self):
        self.assertEqual(self.theme.transpose(2, scale=key("E minor")).text(), "G4.q B4.e C5.e D5.h")
        self.assertEqual(self.theme.invert(scale=key("E minor")).text(), "E4.q C4.e B3.e A3.h")

    def test_sequence_augment_fragment(self):
        seq = M("E4.q").sequence([-1, -1], scale=key("E minor"))
        self.assertEqual(seq.text(), "E4.q D4.q C4.q")
        self.assertEqual(self.theme.augment(2).dur, 8)
        self.assertEqual(self.theme.fragment(0, 2).text(), "E4.q G4.e")

    def test_retrograde_moves_ties_and_drops_marks(self):
        r = M("p C4.q D4.h~ D4.e E4.e").retrograde()
        self.assertEqual(r.text(), "E4.e D4.e~ D4.h C4.q")

    def test_double(self):
        self.assertEqual(M("C5.q R.q").double(-12).text(), "[C4 C5].q R.q")

    def test_rhythm_and_pitches(self):
        self.assertEqual(self.theme.rhythm(1).durations, [1, 1, 1, 1])
        self.assertEqual(self.theme.with_pitches(C4).pitches, [C4] * 4)


class TestScore(unittest.TestCase):
    def test_time_and_position(self):
        s = Score(meter=(3, 4))
        self.assertEqual(s.time(2, 2), 4)
        self.assertEqual(s.position(Fraction(4)), (2, 2))
        self.assertEqual(s.time(1, 2.5), Fraction(3, 2))

    def test_miscount_is_reported_once_and_locally(self):
        s = Score()
        s.part("violin").at(1, "E4.q G4.e A4.e B4.h | C5.h B4.e A4.q | G4.w |4")
        errs = issues(s, "ERROR")
        self.assertEqual(len(errs), 1)
        self.assertIn("bar 2 has 3.5 beats, expected 4 beats", errs[0][3])

    def test_wrong_bar_number(self):
        s = Score()
        s.part("violin").at(1, "E4.w | C5.w |4")
        self.assertIn("not bar 4", issues(s, "ERROR")[0][3])

    def test_pickup_placement_is_fine(self):
        s = Score()
        s.part("violin").at(1, "E4.q G4.q | A4.w |3", beat=3)
        self.assertEqual(issues(s, "ERROR"), [])

    def test_overlap_and_range(self):
        s = Score()
        s.part("violin").at(1, "C5.w").at(1, "E5.h", beat=3).at(2, "C3.q")
        self.assertTrue(any("overlaps" in i[3] for i in issues(s, "ERROR")))
        self.assertTrue(any("below the violin range" in i[3] for i in issues(s, "WARN")))

    def test_ties_merge_into_one_sounding_event(self):
        s = Score()
        p = s.part("violin").at(1, "E4.w~ | E4.q")
        self.assertEqual([(t, n.dur) for t, n in p.events()], [(0, 5)])
        self.assertEqual(len(p.events(merge_ties=False)), 2)

    def test_marking_warnings(self):
        s = Score()
        s.part("violin").at(1, "p < E4.w | * E4.w")
        msgs = [i[3] for i in issues(s, "WARN")]
        self.assertTrue(any("never closed" in m for m in msgs))
        self.assertTrue(any("no pedal down" in m for m in msgs))

    def test_parallel_fifths_are_noted(self):
        s = Score()
        s.part("upper", "violin").at(1, "G4.q A4.q")
        s.part("lower", "cello").at(1, "C3.q D3.q")
        self.assertTrue(any("parallel fifths" in i[3] for i in _issues(s, True)))

    def test_staff_order(self):
        s = Score()
        rh, lh = s.piano()
        inner = s.part("rh2", "piano", group="Piano", staff="rh")
        self.assertEqual(s.ordered_parts(), [rh, inner, lh])


class TestPerformance(unittest.TestCase):
    def test_hairpin_ramps_to_next_dynamic(self):
        s = Score()
        rh, _ = s.piano()
        rh.at(1, "p E4.q < E4.q E4.q E4.q | f E4.w")
        d = Dynamics(rh)
        self.assertEqual(d.level(Fraction(0)), LEVELS["p"])
        self.assertEqual(d.level(Fraction(1)), LEVELS["p"])
        self.assertAlmostEqual(d.level(Fraction(5, 2)), (LEVELS["p"] + LEVELS["f"]) / 2)
        self.assertEqual(d.level(Fraction(4)), LEVELS["f"])

    def test_open_hairpin(self):
        s = Score()
        p = s.part("violin").at(1, "p < E4.w ! E4.w")
        self.assertEqual(Dynamics(p).level(Fraction(6)), LEVELS["p"] + HAIRPIN_STEP)

    def test_dynamics_shared_by_group(self):
        s = Score()
        rh, lh = s.piano()
        rh.at(1, "ff E4.w")
        lh.at(1, "C3.w")
        self.assertEqual(Dynamics(lh).level(Fraction(0)), LEVELS["ff"])

    def test_tempo_and_fermata(self):
        s = Score(tempo=120)
        s.part("violin").at(1, "E4.w | E4.w@")
        self.assertAlmostEqual(s.seconds(Fraction(4)), 2.0)
        self.assertAlmostEqual(s.seconds(Fraction(8)), 6.0)    # the fermata bar takes twice as long

    def test_rit(self):
        s = Score(tempo=120)
        s.part("violin").at(1, "E4.w | E4.w | E4.w")
        s.rit(2, 3, to=60)
        tm = tempo_map(s)
        self.assertEqual(tm[0], (0, 120.0))
        self.assertEqual(tm[-1], (8, 60.0))
        self.assertGreater(s.seconds(Fraction(8)), 4.0)

    def test_pedal_changes(self):
        s = Score()
        _, lh = s.piano()
        lh.at(1, "ped C3.w | ped C3.w | *")
        self.assertEqual(pedal_events(lh), [(0, 127), (4, 0), (4 + PEDAL_LIFT, 127), (8, 0)])


class TestOutput(unittest.TestCase):
    def test_midi_structure(self):
        s = Score()
        s.part("violin").at(1, "E4.w")
        data = midi_bytes(s)
        self.assertEqual(data[:4], b"MThd")
        self.assertEqual(int.from_bytes(data[10:12], "big"), 2)   # conductor + 1 part

    def test_couplers_sound_extra_octaves(self):
        s = Score()
        s.part("pedal", "pedal", couplers=(0, -12)).at(1, "D3.w")
        data = midi_bytes(s)
        self.assertIn(bytes([0x90, D3.midi]), data)
        self.assertIn(bytes([0x90, D3.midi - 12]), data)

    def test_registration_changes_program(self):
        s = Score()
        p = s.part("organ").at(1, "C4.w | C4.w")
        p.registration(2, "Sw.", "percussive organ")
        self.assertIn(bytes([0xC0, 17]), midi_bytes(s))

    def test_lilypond_notation(self):
        s = Score("t", key="C minor")
        rh, lh = s.piano()
        rh.at(1, 'p C5.q> D5.e3 Eb5.e3 F5.e3 < G5.h~ | G5.w@ f')
        lh.at(1, "ped C3.w | * C3.w")
        s.rit(2, 3, to=60)
        ly = lilypond(s)
        for snippet in ["\\key c \\minor", "\\tuplet 3/2", "->", "~", "\\fermata", "\\p",
                        "\\<", "\\f", "\\sustainOn", "\\sustainOff", "\\startTextSpan",
                        "\\new PianoStaff", '\\bar "|."']:
            self.assertIn(snippet, ly, snippet)

    def test_triplets_bracketed_per_beat(self):
        s = Score()
        s.part("violin").at(1, " ".join(["G4.e3"] * 6) + " G4.h |")
        ly = lilypond(s)
        self.assertEqual(ly.count("\\tuplet 3/2"), 2)

    def test_lilypond_splits_notes_at_barlines(self):
        s = Score()
        s.part("violin").at(1, "R.h E4.w R.h")
        self.assertIn("e'2~ | e'2", lilypond(s).replace("\n", " ").replace("    ", ""))

    def test_organ_layout(self):
        s = Score()
        man1, man2, ped = s.organ()
        man1.at(1, "C5.w")
        man2.at(1, "C4.w")
        ped.at(1, "C3.w")
        ly = lilypond(s)
        self.assertIn('instrumentName = "Ped."', ly)
        self.assertLess(ly.index("\\new PianoStaff"), ly.index('instrumentName = "Ped."'))


class TestEngravingRules(unittest.TestCase):
    def test_ottava_for_far_off_bars(self):
        s = Score()
        _, lh = s.piano()
        lh.at(1, "[C1 C2].w | C3.w")
        ly = lilypond(s)
        self.assertIn("\\ottava #-1", ly)
        self.assertIn("\\ottava #0", ly)

    def test_duplicate_registrations_merge(self):
        s = Score()
        rh, lh, ped = s.organ()
        alto = s.part("alto", "organ", group="Organ", staff="rh")
        rh.at(1, "C5.w").registration(1, "Gt.")
        alto.at(1, "C4.w").registration(1, "Gt.")
        self.assertEqual(lilypond(s).count('"Gt."'), 1)

    def test_text_beside_dynamic(self):
        s = Score()
        s.part("violin").at(1, 'p "dolce" E4.w')
        self.assertIn('#:dynamic "p" #:normal-text #:italic "dolce"', lilypond(s))


class TestVerification(unittest.TestCase):
    def test_reader_reads_our_own_midi(self):
        sc = load_score(str(EXAMPLES / "prelude.py"))
        self.assertEqual(read_notes(midi_bytes(sc)), score_notes(sc))   # no couplers or staccato there

    def test_verify_reports_differences(self):
        s = Score()
        s.part("violin").at(1, "E4.w")
        other = Score()
        other.part("violin").at(1, "F4.w")
        self.assertEqual(verify(s, midi_bytes(s)), [])
        problems = verify(s, midi_bytes(other))
        self.assertEqual(len(problems), 2)
        self.assertIn("missing from the engraving: E4 at 1:1", problems[0])

    @unittest.skipUnless(shutil.which("lilypond"), "lilypond not installed")
    def test_examples_engrave_and_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            for f in sorted(EXAMPLES.glob("*.py")):
                with self.subTest(piece=f.name):
                    engrave(load_score(str(f)), str(Path(tmp) / (f.stem + ".pdf")))   # raises on any mismatch


class TestExamples(unittest.TestCase):
    def test_examples_check_clean_and_round_trip(self):
        files = sorted(EXAMPLES.glob("*.py"))
        self.assertTrue(files)
        for f in files:
            with self.subTest(piece=f.name):
                sc = load_score(str(f))
                self.assertFalse(has_errors(sc))
                for p in sc.parts:
                    text = " | ".join(" ".join(c) for c in _bar_cells(sc, p, sc.bars))
                    copy = Score(sc.title, sc.meter, sc.tempo, sc.key).part(p.name, p.instrument).at(1, text)
                    sounding = lambda part: [(t, n.pitches, n.dur, n.art) for t, n in part.events() if not n.is_rest]
                    self.assertEqual(sounding(p), sounding(copy), p.name)
                    marks = lambda part: [(t, m) for t, m in part.marks(bm.Mark)]
                    self.assertEqual(marks(p), marks(copy), p.name)


if __name__ == "__main__":
    unittest.main()
