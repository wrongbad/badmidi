"""badmidi piece.py [view] -- run a piece script and show or export its score.

    badmidi piece.py                     melody-major view (default)
    badmidi piece.py grid --bars 5-8     harmony-major view of bars 5..8
    badmidi piece.py check               is it what you meant? bar counts, overlaps, ranges
    badmidi piece.py lens --bars 9-16    what the voices are doing: passing notes,
                                         suspensions, parallels, crossings (--kinds susp,parallel)
    badmidi piece.py midi [-o out.mid]   write a MIDI file
    badmidi piece.py wav  [-o out.wav]   render audio with fluidsynth
    badmidi piece.py ly                  print LilyPond source
    badmidi piece.py pdf  [-o out.pdf]   engrave sheet music with LilyPond
    badmidi piece.py png  [-o out.png]   engrave to PNG page images
    badmidi piece.py all                 check, melody, grid, and write .mid
"""
from __future__ import annotations

import argparse
import os
import runpy
import sys
from fractions import Fraction

from .core import duration
from .score import Score


def load_score(path: str, name: str | None = None) -> Score:
    ns = runpy.run_path(path, run_name="__badmidi__")
    if name:
        if not isinstance(ns.get(name), Score):
            sys.exit(f"{path}: no Score named {name!r}")
        return ns[name]
    if isinstance(ns.get("score"), Score):
        return ns["score"]
    found = [v for k, v in ns.items() if isinstance(v, Score) and not k.startswith("_")]
    if len(found) != 1:
        sys.exit(f"{path}: define a variable named `score` (found {len(found)} Score objects)")
    return found[0]


def _bars(text: str | None):
    if not text:
        return None
    a, _, b = text.partition("-")
    return int(a), int(b or a)


def _step(text: str | None):
    if not text:
        return None
    try:
        return duration(text)
    except ValueError:
        return Fraction(text)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="badmidi", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("piece", help="python file that builds a Score")
    ap.add_argument("view", nargs="?", default="melody",
                    choices=["melody", "grid", "check", "lens", "midi", "wav", "ly", "pdf", "png", "all"])
    ap.add_argument("-o", "--out", help="output path for midi/wav (default: next to the piece)")
    ap.add_argument("--bars", help="bar range, e.g. 5-8 or 12")
    ap.add_argument("--parts", help="comma-separated part names to show")
    ap.add_argument("--width", type=int, default=4, help="bars per line in the melody view")
    ap.add_argument("--step", help="grid: also add a row every STEP (e.g. e, s, 0.5)")
    ap.add_argument("--score", help="name of the Score variable, if not `score`")
    ap.add_argument("--soundfont", help="soundfont for wav rendering")
    ap.add_argument("--kinds", help="lens: only observations naming these, e.g. susp,parallel")
    args = ap.parse_args(argv)

    score = load_score(args.piece, args.score)
    parts = args.parts.split(",") if args.parts else None
    bars = _bars(args.bars)
    stem = os.path.splitext(args.piece)[0]

    if args.view in ("check", "all"):
        print(score.check())
    if args.view == "lens":
        print(score.lens(bars=bars, parts=parts, kinds=args.kinds.split(",") if args.kinds else None))
    if args.view in ("melody", "all"):
        print(score.melody(bars=bars, parts=parts, width=args.width))
    if args.view in ("grid", "all"):
        print(score.grid(bars=bars, parts=parts, step=_step(args.step)))
    if args.view in ("midi", "all"):
        out = args.out if args.view == "midi" and args.out else stem + ".mid"
        score.write_midi(out)
        print(f"wrote {out}")
    if args.view == "wav":
        out = args.out or stem + ".wav"
        score.render_wav(out, args.soundfont)
        print(f"wrote {out}")
    if args.view == "ly":
        print(score.lilypond())
    if args.view in ("pdf", "png"):
        out = args.out or stem + "." + args.view
        from .lilypond import EngraveError
        try:
            score.engrave(out, args.view)
        except EngraveError as e:
            sys.exit(str(e))
        print(f"engraved {os.path.splitext(out)[0]}.{args.view}; verified: all notes match the score")
    return 0


if __name__ == "__main__":
    sys.exit(main())
