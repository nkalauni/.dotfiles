#!/usr/bin/env python3
"""Final-pass export of a figure SVG through the Inkscape CLI.

    finish.py figure.svg -o out/figure1 --formats pdf,png,svg [--dpi 600] [--fit]
              [--keep-text] [--font-replace "DejaVu Sans=Liberation Sans"] [--force]

Defaults: text converted to paths (fonts can't go missing), page area exported as-is
(the SVG's width/height is the physical size), opaque white PNG background.
Writes <stem>.<fmt> for each format and prints the resulting physical size.
Standard library only; needs `inkscape` (1.x) on PATH.
"""
from __future__ import annotations

import argparse
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

FORMATS = {"pdf", "eps", "ps", "png", "svg"}


def run_inkscape(args: list[str]) -> None:
    proc = subprocess.run(["inkscape", *args], capture_output=True, text=True)
    # The AppImage prints harmless banners to stderr; only surface real problems.
    noise = ("AppImage", "_INKSCAPE_GC", "Unable to init server", "Gtk-", "dbus", "glibmm-WARNING")
    errs = [l for l in proc.stderr.splitlines() if l.strip() and not any(n in l for n in noise)]
    if proc.returncode != 0:
        sys.exit("inkscape failed:\n" + "\n".join(errs or [proc.stderr]))
    for line in errs:
        print("inkscape:", line, file=sys.stderr)


def pdf_size_mm(path: Path) -> str:
    data = path.read_bytes()
    m = re.search(rb"/MediaBox\s*\[\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)", data)
    if not m:
        return "size unknown"
    x0, y0, x1, y1 = (float(v) for v in m.groups())
    return f"{(x1 - x0) * 25.4 / 72:.1f} x {(y1 - y0) * 25.4 / 72:.1f} mm"


def png_size(path: Path) -> str:
    data = path.read_bytes()
    w, h = struct.unpack(">II", data[16:24])
    m = re.search(rb"pHYs(.{9})", data[:4096], re.S)
    if m:
        ppu, _, unit = struct.unpack(">IIB", m.group(1))
        if unit == 1 and ppu:
            dpi = ppu * 0.0254
            return f"{w} x {h} px @ {dpi:.0f} dpi = {w / dpi * 25.4:.1f} x {h / dpi * 25.4:.1f} mm"
    return f"{w} x {h} px"


def ps_size_mm(path: Path) -> str:
    m = re.search(rb"%%BoundingBox:\s*([-\d]+)\s+([-\d]+)\s+([-\d]+)\s+([-\d]+)", path.read_bytes()[:8192])
    if not m:
        return "size unknown"
    x0, y0, x1, y1 = (int(v) for v in m.groups())
    return f"{(x1 - x0) * 25.4 / 72:.1f} x {(y1 - y0) * 25.4 / 72:.1f} mm"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input", type=Path)
    p.add_argument("-o", "--output-stem", type=Path, required=True, help="e.g. out/figure1 -> out/figure1.pdf")
    p.add_argument("--formats", default="pdf,png", help=f"comma list of {sorted(FORMATS)}")
    p.add_argument("--dpi", type=int, default=600, help="PNG resolution (also rasterized filters in PDF/EPS)")
    p.add_argument("--fit", action="store_true", help="shrink page to the drawing bounding box first")
    p.add_argument("--margin-mm", type=float, default=0.0, help="margin added around drawing with --fit")
    p.add_argument("--keep-text", action="store_true", help="keep text as editable text (fonts must be embeddable)")
    p.add_argument("--font-replace", action="append", default=[], metavar="OLD=NEW",
                   help="swap a font family in the SVG before export (repeatable)")
    p.add_argument("--transparent", action="store_true", help="PNG without the white background")
    p.add_argument("--force", action="store_true", help="overwrite existing outputs")
    a = p.parse_args()

    if not shutil.which("inkscape"):
        sys.exit("inkscape not found on PATH")
    formats = [f.strip().lower() for f in a.formats.split(",") if f.strip()]
    bad = set(formats) - FORMATS
    if bad:
        sys.exit(f"unsupported format(s): {', '.join(sorted(bad))}")
    outputs = {f: a.output_stem.with_suffix("." + f) for f in formats}
    existing = [str(o) for o in outputs.values() if o.exists()]
    if existing and not a.force:
        sys.exit("refusing to overwrite (pass --force): " + ", ".join(existing))
    if a.input.resolve() in {o.resolve() for o in outputs.values()}:
        sys.exit("an output would overwrite the input; choose a different --output-stem")
    a.output_stem.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        src = a.input
        if a.font_replace or a.fit:
            text = a.input.read_text(encoding="utf-8")
            for pair in a.font_replace:
                old, _, new = pair.partition("=")
                text = text.replace(old, new)
            src = Path(tmp) / "work.svg"
            src.write_text(text, encoding="utf-8")
        if a.fit:
            fit_args = [str(src), "--export-overwrite", "--export-type=svg"]
            if a.margin_mm:
                fit_args.append(f"--export-margin={a.margin_mm}")
            fit_args.append("--actions=select-all:all;fit-canvas-to-selection")
            run_inkscape(fit_args)

        for fmt, out in outputs.items():
            args = [str(src), f"--export-type={fmt}", f"--export-filename={out}",
                    "--export-area-page", f"--export-dpi={a.dpi}"]
            if not a.keep_text and fmt != "png":
                args.append("--export-text-to-path")
            if fmt == "svg":
                args.append("--export-plain-svg")
            if fmt == "pdf":
                args.append("--export-pdf-version=1.5")
            if fmt in ("eps", "ps"):
                args.append("--export-ps-level=3")
            if fmt == "png" and not a.transparent:
                args += ["--export-background=#ffffff", "--export-background-opacity=1"]
            if a.force:
                args.append("--export-overwrite")
            run_inkscape(args)
            if not out.exists() or out.stat().st_size == 0:
                sys.exit(f"inkscape produced no output for {out}")
            size = {"pdf": pdf_size_mm, "png": png_size, "eps": ps_size_mm, "ps": ps_size_mm}.get(fmt)
            print(f"{out}  ({out.stat().st_size / 1024:.0f} KiB{', ' + size(out) if size else ''})")


if __name__ == "__main__":
    main()
