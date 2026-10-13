"""badmidi: music as code.

    from badmidi import *

    theme  = M(E4.q, G4.e, A4.e, B4.h)
    answer = theme.invert(around=A4).transpose(5)

    score = Score("Sketch", meter=(4, 4), tempo=80, key="E minor")
    score.part("violin").at(1, theme, answer)
    print(score.melody())
"""
from .core import (ARTICULATIONS, BAR, CRESC, DIM, DURATIONS, DYNAMICS, HAIRPIN_END,
                   PED, PED_UP, Bar, Chord, M, Mark, Motif, Note, Pitch, R, as_pitch, dyn,
                   spelling, text)
from .notes import *  # noqa: F401,F403  C4, Fs4, Bb3, ...
from .notes import __all__ as _note_names
from .scale import MODES, Scale, key
from .score import INSTRUMENTS, Part, Score

__all__ = ["ARTICULATIONS", "BAR", "Bar", "CRESC", "Chord", "DIM", "DURATIONS", "DYNAMICS",
           "HAIRPIN_END", "INSTRUMENTS", "M", "MODES", "Mark", "Motif", "PED", "PED_UP", "dyn", "text",
           "Note", "Part", "Pitch", "R", "Scale", "Score", "as_pitch", "key", "spelling",
           *_note_names]
