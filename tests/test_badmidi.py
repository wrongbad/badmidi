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
from badmidi import (A4, B3, B4, Bb3, C4, C5, D3, D5, E4, E5, Fs4, G4, G5, M, R, Score,
                     key, spelling)
from badmidi.cli import load_score
from badmidi.core import NotationError, Pitch
from badmidi.lilypond import EngraveError, engrave, lilypond, score_notes, verify
from badmidi.midi import midi_bytes, read_notes
from badmidi.perform import Dynamics, LEVELS, HAIRPIN_STEP, PEDAL_LIFT, pedal_events, tempo_map
from badmidi.views import _bar_cells, _issues, has_errors

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def issues(score, level=None):
    return [i for i in _issues(score) if level is None or i[0] == level]


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

    def test_transposition_is_spelled_as_an_interval(self):
        subject = M("C3.h G3.q A3.q | F3.qd E3.e D3.e E3.e C3.q |")
        self.assertEqual(subject.transpose(6).text(),
                         "Fs3.h Cs4.q Ds4.q | B3.qd As3.e Gs3.e As3.e Fs3.q |")
        self.assertEqual(M("E4.q G4.q").transpose(3).text(), "G4.q Bb4.q")
        self.assertEqual(M("C4.q G4.q A4.q F4.q").invert(around=A4).text(), "Fs5.q B4.q A4.q Cs5.q")
        self.assertEqual(M("Cs4.q D4.q").transpose(4, scale=key("A major")).text(), "Gs4.q A4.q")
        self.assertEqual(M("Ab3.q").unbarred(), M("Ab3.q |").unbarred())

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
        self.assertIn("bar 2 has 3.5 beats, expected 4 beats: an eighth (.e) too short", errs[0][3])

    def test_second_voice_on_a_staff(self):
        s = Score()
        rh, _ = s.piano()
        rh.at(1, "C5.w")
        rh.at(1, "E4.h F4.h")
        self.assertIn("rh.voice(name)", issues(s, "ERROR")[0][3])
        alto = rh.voice("alto")
        self.assertEqual((alto.staff, alto.group, alto.channel, alto.instrument), ("rh", "Piano", "Piano", "piano"))
        s2 = Score()
        r2, _ = s2.piano()
        r2.at(1, "C5.w")
        r2.voice("alto").at(1, "E4.h F4.h")
        self.assertEqual(issues(s2, "ERROR"), [])

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
        self.assertTrue(any("runs to the end" in i[3] for i in issues(s, "NOTE")))
        self.assertTrue(any("no pedal down" in m for m in msgs))

    def test_parallel_fifths_are_noted(self):
        s = Score()
        s.part("upper", "violin").at(1, "G4.q A4.q")
        s.part("lower", "cello").at(1, "C3.q D3.q")
        self.assertEqual([o.kind for o in s.observe()], ["parallel fifths"])
        self.assertEqual(issues(s, "ERROR") + issues(s, "WARN"), [])   # an observation, not a problem

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


class TestMeters(unittest.TestCase):
    def setUp(self):
        self.s = Score(meter=(4, 4))
        self.s.meter_change(2, "3/4").meter_change(3, "2+2+3/8").free_bar(4, 9).meter_change(6, (6, 8))

    def test_time_across_changes(self):
        s = self.s
        self.assertEqual([s.bar_start(b) for b in range(1, 8)], [0, 4, 7, Fraction(21, 2), Fraction(39, 2), 23, 26])
        self.assertEqual(s.time(3, 3), 8)                       # eighth-note beats in 7/8
        self.assertEqual(s.position(Fraction(23)), (6, 1))
        self.assertEqual(s.meter_at(5).text, "2+2+3/8")          # the meter resumes after a free bar
        with self.assertRaises(ValueError):
            s.time(2, 4)                                         # no beat 4 in 3/4

    def test_metric_levels(self):
        s = self.s
        self.assertEqual(s.metric_level(s.time(3)), 3)
        self.assertEqual(s.metric_level(s.time(3, 3)), 2)        # an additive group starts
        self.assertEqual(s.metric_level(s.time(3, 2)), 0)
        self.assertEqual(s.metric_level(s.time(6, 4)), 2)        # 6/8: the second dotted quarter
        self.assertEqual(Score().metric_level(Fraction(2)), 2)   # beat 3 of 4/4
        self.assertEqual(Score().metric_level(Fraction(1)), 1)       # every beat is a pulse in 4/4
        self.assertEqual(Score().metric_level(Fraction(1, 2)), -1)

    def test_check_counts_each_bar_in_its_own_meter(self):
        self.s.part("violin").at(1, "C5.w | D5.h E5.q | F5.e G5.e A5.e G5.e F5.q |")
        self.assertIn("bar 3 has 6 beats, expected 7 beats", issues(self.s, "ERROR")[0][3])

    def test_views_and_outputs_show_meters(self):
        s = self.s
        s.part("violin").at(1, "C5.w | D5.h E5.q | F5.e G5.e A5.e G5.e F5.qd |", "C5.q " * 9 + "|",
                            "G5.q G5.q G5.qd | C5.qd D5.qd |7")
        self.assertEqual(issues(s, "ERROR"), [])
        self.assertIn("3 2+2+3/8", s.melody())
        self.assertIn("-- 4 free", s.grid())
        ly = lilypond(s)
        for snippet in ["\\time 3/4", "\\compoundMeter #'((2 2 3 8))", "measureLength = #(ly:make-moment 9/4)",
                        '\\bar ""', "\\time 6/8"]:
            self.assertIn(snippet, ly)
        self.assertEqual(midi_bytes(s).count(bytes([0xFF, 0x58])), 6)

    def test_entry_mid_bar_keeps_its_own_barlines(self):
        subject = M("C4.h G4.q A4.q | F4.qd E4.e D4.e E4.e C4.q |")
        s = Score()
        s.part("violin").at(1, subject, "E4.h |", beat=3)          # enters at the half bar
        self.assertEqual(issues(s, "ERROR"), [])
        bad = Score()
        bad.part("violin").at(1, M("C4.h G4.q | F4.w |"), beat=3)  # its first bar is short
        self.assertTrue(issues(bad, "ERROR"))

    @unittest.skipUnless(shutil.which("lilypond"), "lilypond not installed")
    def test_meters_and_tuplets_engrave(self):
        s = self.s
        s.part("violin").at(1, "C5.s5 D5.s5 E5.s5 F5.s5 G5.s5 A5.e3 G5.e3 F5.e3 E5.e7 D5.e7 C5.e7 B4.e7 C5.e7 D5.e7 E5.e7 |",
                            "C5.q5:3 D5.q5:3 E5.q5:3 F5.q5:3 G5.q5:3 |", "F5.e G5.e A5.e G5.e F5.qd |",
                            "C5.q " * 9 + "|", "G5.q G5.q G5.qd | C5.qd D5.qd |7")
        with tempfile.TemporaryDirectory() as tmp:
            engrave(s, str(Path(tmp) / "m.pdf"))
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["m.pdf"])   # no stray .ly


class TestTuplets(unittest.TestCase):
    def test_codes(self):
        self.assertEqual(bm.duration("s5"), Fraction(1, 5))
        self.assertEqual(bm.duration("e7"), Fraction(2, 7))
        self.assertEqual(bm.duration("q5:3"), Fraction(3, 5))
        self.assertEqual(bm.duration("e3"), Fraction(1, 3))
        self.assertEqual(C4.s5, M("C4.s5")[0])
        with self.assertRaises(ValueError):
            bm.duration("q4")

    def test_round_trip(self):
        m = M("C4.s5 D4.e7 E4.q5:3 F4*(2/9)")
        self.assertEqual(M(m.text()), m)
        self.assertEqual(m.text(), "C4.s5 D4.e7 E4.q5:3 F4.s9")

    def test_written_ratio_is_kept(self):
        m = M("C4.q5:3 D4.q5:3 E4.q5:3 F4.q5:3 G4.q5:3")
        self.assertEqual(m.notes[0].tuplet, (5, 3))
        self.assertEqual(m.augment(2).text().split()[0], "C4.h5:3")
        self.assertEqual(m.rhythm(1).text().split()[0], "C4.q")       # plain lengths need no tuplet
        self.assertEqual(M("C4*(3/5)").text(), "C4.q5:3")
        s = Score(meter=(3, 4))
        s.part("violin").at(1, m, "|")
        self.assertIn("\\tuplet 5/3 { c'4", lilypond(s))

    def test_lilypond_brackets(self):
        s = Score()
        s.part("violin").at(1, "C5.s5 " * 5 + "C5.e7 " * 7 + "C5.q |")
        ly = lilypond(s)
        self.assertEqual(ly.count("\\tuplet 5/4"), 1)
        self.assertEqual(ly.count("\\tuplet 7/4"), 1)


class TestAnalysis(unittest.TestCase):
    def test_set_classes(self):
        self.assertEqual(bm.prime_form({0, 4, 7}), (0, 3, 7))
        self.assertEqual(bm.prime_form([C4, E4, G4 + 1]), (0, 4, 8))
        self.assertEqual(bm.prime_form({0, 1, 3, 6, 7, 9}), (0, 1, 3, 6, 7, 9))
        self.assertEqual(bm.interval_vector({0, 1, 4, 6}), (1, 1, 1, 1, 1, 1))
        self.assertEqual(bm.set_label([C4, E4, G4, Fs4 + 12, Fs4 + 16, Fs4 + 19]), "6-30 (013679) Petrushka")
        self.assertEqual(bm.set_label([C4, G4]), "ic5")

    def lens(self, upper, lower, meter=(4, 4)):
        s = Score(meter=meter)
        s.part("upper", "violin").at(1, upper)
        s.part("lower", "cello").at(1, lower)
        return [(s.where(o.t), o.where, o.kind) for o in s.observe()]

    def test_dissonances_are_named_by_how_they_move(self):
        self.assertEqual(self.lens("E4.q F4.q G4.h", "C3.w"), [("1:2", "upper", "passing")])
        self.assertEqual(self.lens("E4.q F4.q E4.h", "C3.w"), [("1:2", "upper", "neighbour")])
        self.assertEqual(self.lens("C4.q F4.q E4.h", "C3.w"), [("1:2", "upper", "appoggiatura")])
        self.assertEqual(self.lens("E4.q F4.q A4.h", "C3.w"), [("1:2", "upper", "escape tone")])
        self.assertEqual(self.lens("C4.h D4.h", "C3.h C3.h"), [("1:3", "upper", "unresolved")])
        self.assertEqual(self.lens("C4.h G4.q D4.q | G4.w", "C3.w | C3.w"), [("1:4", "upper", "free dissonance")])
        self.assertEqual(self.lens("C4.h D4.h E4.w", "C3.h C3.h C3.w"), [("1:3", "upper", "accented passing")])

    def test_suspensions(self):
        obs = Score()
        obs.part("upper", "violin").at(1, "G4.h C5.h~ | C5.h B4.h |")
        obs.part("lower", "cello").at(1, "C3.h E3.h | D3.w |")
        [o] = obs.observe()
        self.assertEqual((o.kind, o.detail), ("suspension", "C5: m7->M6 with lower D3"))
        held = self.lens("G4.h C5.h~ | C5.h D5.h |", "C3.h E3.h | D3.w |")
        self.assertEqual(held, [("2:1", "upper", "retardation")])

    def test_lens_view(self):
        s = Score()
        s.part("upper", "violin").at(1, "G4.q A4.q E4.q F4.q G4.w |")
        s.part("lower", "cello").at(1, "C3.q D3.q C3.h | C3.w |")
        text = s.lens()
        self.assertIn("parallel fifths", text)
        self.assertIn("passing", text)
        self.assertNotIn("passing", s.lens(kinds=["parallel"]))
        self.assertIn("3-12 (048) augmented", Score().part("v", "piano").at(1, "[C4 E4 Gs4].w").score.grid())
        self.assertIn("Am", Score().part("v", "piano").at(1, "[A3 C4 E4].w").score.grid())

    def test_isorhythm(self):
        m = bm.isorhythm("C4 D4 E4", [1, 2])
        self.assertEqual(m.text(), "C4.q D4.h E4.q C4.h D4.q E4.h")
        m = bm.isorhythm([C4, E4], M("C4.q R.q C4.h>"), notes=3)
        self.assertEqual(m.text(), "C4.q R.q E4.h> C4.q")

    def test_stretti(self):
        subject = M("C4.h G4.q A4.q | F4.qd E4.e D4.e E4.e C4.q |")
        found = bm.stretti(subject, intervals=(12, 7), offsets=[2, 4, 7])
        self.assertEqual([(x.offset, x.interval) for x in found], [(2, 12), (2, 7), (4, 12), (4, 7), (7, 12), (7, 7)])
        self.assertEqual(found[-1].summary(), "consonant throughout")
        self.assertEqual(found[0].follower, M(*subject.notes).transpose(12))
        self.assertIn("what happens", str(found))
        sc = Score()
        a, b = sc.part("a", "violin"), sc.part("b", "viola")
        found[2].place(a, b, 3)
        self.assertEqual(b.events()[0][0], sc.time(4))


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
