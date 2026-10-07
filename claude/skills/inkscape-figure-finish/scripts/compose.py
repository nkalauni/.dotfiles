#!/usr/bin/env python3
"""Compose panel SVGs (or PNGs) into one multi-panel figure SVG at an exact physical width.

The output SVG uses millimetres as user units (viewBox matches width/height in mm), so
positions and sizes below are all in mm. Each panel is embedded as a nested <svg>, with
its ids prefixed so clip paths and glyph defs from different matplotlib files cannot
collide. Standard library only; runs on Python 3.8+.

Grid mode:
    compose.py -o fig.svg --width-mm 180 --cols 2 a.svg b.svg c.svg d.svg

Freeform mode (JSON layout, mm):
    compose.py -o fig.svg --layout layout.json
    {
      "width_mm": 180, "height_mm": 120,            # height optional (auto-fit)
      "panels": [
        {"file": "a.svg", "x": 0,  "y": 0, "width": 88},
        {"file": "b.svg", "x": 92, "y": 0, "width": 88, "height": 60, "label": "b"}
      ]
    }
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
for prefix, uri in {
    "": SVG_NS,
    "xlink": XLINK_NS,
    "dc": "http://purl.org/dc/elements/1.1/",
    "cc": "http://creativecommons.org/ns#",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "inkscape": "http://www.inkscape.org/namespaces/inkscape",
    "sodipodi": "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd",
}.items():
    ET.register_namespace(prefix, uri)

MM_PER_UNIT = {"": 25.4 / 96, "px": 25.4 / 96, "pt": 25.4 / 72, "pc": 25.4 / 6,
               "mm": 1.0, "cm": 10.0, "in": 25.4}
URL_RE = re.compile(r"url\(\s*#([^)\s]+)\s*\)")


def length_mm(value: str | None) -> float | None:
    if not value:
        return None
    m = re.fullmatch(r"\s*([0-9.eE+-]+)\s*([a-z%]*)\s*", value)
    if not m or m.group(2) not in MM_PER_UNIT:
        return None
    return float(m.group(1)) * MM_PER_UNIT[m.group(2)]


class Panel:
    """A loaded panel: natural size in mm plus a factory for the embedded element."""

    def __init__(self, path: Path, index: int):
        self.path = path
        self.prefix = f"p{index}-"
        if not path.is_file():
            sys.exit(f"{path}: no such file")
        if path.suffix.lower() == ".png":
            self._load_png()
        else:
            self._load_svg()

    def _load_svg(self) -> None:
        root = ET.parse(self.path).getroot()
        if root.tag != f"{{{SVG_NS}}}svg":
            sys.exit(f"{self.path}: not an SVG document")
        vb = root.get("viewBox")
        w, h = length_mm(root.get("width")), length_mm(root.get("height"))
        if vb:
            vb_vals = [float(v) for v in re.split(r"[\s,]+", vb.strip())]
            if w is None and h is None:  # unitless: assume user units are px
                w, h = vb_vals[2] * MM_PER_UNIT["px"], vb_vals[3] * MM_PER_UNIT["px"]
            elif w is None:
                w = h * vb_vals[2] / vb_vals[3]
            elif h is None:
                h = w * vb_vals[3] / vb_vals[2]
        else:
            if w is None or h is None:
                sys.exit(f"{self.path}: needs width/height or a viewBox")
            vb_vals = [0, 0, w / MM_PER_UNIT["px"], h / MM_PER_UNIT["px"]]
        self.w_mm, self.h_mm = w, h
        self.viewbox = " ".join(f"{v:g}" for v in vb_vals)
        self._prefix_ids(root)
        self.children = [c for c in root if c.tag != f"{{{SVG_NS}}}metadata"]

    def _prefix_ids(self, root: ET.Element) -> None:
        ids = {el.get("id") for el in root.iter() if el.get("id")}
        if not ids:
            return

        def fix_url(m: re.Match) -> str:
            ref = m.group(1)
            return f"url(#{self.prefix}{ref})" if ref in ids else m.group(0)

        for el in root.iter():
            for key, val in list(el.attrib.items()):
                if key == "id":
                    el.set(key, self.prefix + val)
                elif key.endswith("href") and val.startswith("#") and val[1:] in ids:
                    el.set(key, "#" + self.prefix + val[1:])
                elif "url(" in val:
                    el.set(key, URL_RE.sub(fix_url, val))
            if el.text and "url(" in el.text:
                el.text = URL_RE.sub(fix_url, el.text)

    def _load_png(self) -> None:
        data = self.path.read_bytes()
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            sys.exit(f"{self.path}: not a PNG")
        px_w, px_h = struct.unpack(">II", data[16:24])
        dpi = 300.0
        i = 8
        while i < len(data):  # look for a pHYs chunk to get the true DPI
            length, ctype = struct.unpack(">I4s", data[i:i + 8])
            if ctype == b"pHYs":
                ppu_x, _, unit = struct.unpack(">IIB", data[i + 8:i + 17])
                if unit == 1 and ppu_x:
                    dpi = ppu_x * 0.0254
                break
            if ctype == b"IDAT":
                break
            i += 12 + length
        self.w_mm, self.h_mm = px_w / dpi * 25.4, px_h / dpi * 25.4
        self.viewbox = f"0 0 {px_w} {px_h}"
        img = ET.Element(f"{{{SVG_NS}}}image", {
            "x": "0", "y": "0", "width": str(px_w), "height": str(px_h),
            "preserveAspectRatio": "none",
            f"{{{XLINK_NS}}}href": "data:image/png;base64," + base64.b64encode(data).decode(),
        })
        self.children = [img]

    def element(self, x: float, y: float, width: float, height: float | None) -> tuple[ET.Element, float]:
        scale = width / self.w_mm
        if abs(scale - 1) > 0.03:
            print(f"WARNING: {self.path.name} drawn {self.w_mm:.1f} mm wide, placed at {width:.1f} mm "
                  f"(x{scale:.2f}); fonts/lines scale too. Redraw it at {width:.1f} mm wide.",
                  file=sys.stderr)
        if height is None:
            height = width * self.h_mm / self.w_mm
        el = ET.Element(f"{{{SVG_NS}}}svg", {
            "x": f"{x:.4f}", "y": f"{y:.4f}",
            "width": f"{width:.4f}", "height": f"{height:.4f}",
            "viewBox": self.viewbox, "preserveAspectRatio": "xMinYMin meet",
            "id": self.prefix + "panel",
        })
        el.extend(self.children)
        return el, height


def label_text(i: int, style: str) -> str:
    letter = chr(ord("a") + i)
    return {"lower": letter, "upper": letter.upper(),
            "paren": f"({letter})", "Paren": f"({letter.upper()})"}[style]


def make_label(text: str, x: float, y_top: float, a: argparse.Namespace) -> ET.Element:
    size_mm = a.label_size_pt * 25.4 / 72
    el = ET.Element(f"{{{SVG_NS}}}text", {
        "x": f"{x:.4f}", "y": f"{y_top + size_mm * 0.8:.4f}",  # baseline ~ cap height below top
        "font-family": a.label_font, "font-size": f"{size_mm:.4f}",
        "font-weight": a.label_weight, "fill": "#000000",
    })
    el.text = text
    return el


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("panels", nargs="*", type=Path, help="panel files (.svg or .png), row-major order")
    p.add_argument("-o", "--output", required=True, type=Path)
    p.add_argument("--layout", type=Path, help="JSON freeform layout (overrides grid options)")
    p.add_argument("--width-mm", type=float, help="total figure width, e.g. 89 (single col) / 183 (double)")
    p.add_argument("--cols", type=int, default=1)
    p.add_argument("--gap-mm", type=float, default=3.0, help="space between panels")
    p.add_argument("--margin-mm", type=float, default=0.0)
    p.add_argument("--max-height-mm", type=float, help="warn if the composed figure is taller")
    p.add_argument("--labels", default="lower",
                   help="lower | upper | paren | Paren | none | comma list like 'a,b,c'")
    p.add_argument("--label-size-pt", type=float, default=8.0)
    p.add_argument("--label-font", default="Liberation Sans")
    p.add_argument("--label-weight", default="bold")
    p.add_argument("--label-space-mm", type=float,
                   help="vertical space reserved above each panel for its label (default: label height)")
    p.add_argument("--force", action="store_true", help="overwrite output")
    a = p.parse_args()

    if a.output.exists() and not a.force:
        sys.exit(f"{a.output} exists; pass --force to overwrite")

    labels_on = a.labels != "none"
    explicit = a.labels.split(",") if "," in a.labels else None
    reserve = 0.0
    if labels_on:
        reserve = a.label_space_mm if a.label_space_mm is not None else a.label_size_pt * 25.4 / 72 * 1.25

    def label_for(i: int) -> str:
        if explicit:
            return explicit[i] if i < len(explicit) else ""
        return label_text(i, a.labels)

    body = []
    if a.layout:
        spec = json.loads(a.layout.read_text())
        width = float(spec["width_mm"])
        bottom = 0.0
        for i, entry in enumerate(spec["panels"]):
            panel = Panel(Path(entry["file"]), i)
            x, y = float(entry["x"]), float(entry["y"])
            el, h = panel.element(x, y + reserve, float(entry["width"]), entry.get("height"))
            body.append(el)
            text = entry.get("label", label_for(i) if labels_on else "")
            if text:
                body.append(make_label(text, x, y, a))
            bottom = max(bottom, y + reserve + h)
        height = float(spec.get("height_mm", bottom + a.margin_mm))
    else:
        if not a.panels or not a.width_mm:
            sys.exit("grid mode needs panel files and --width-mm (or use --layout)")
        width = a.width_mm
        cell_w = (width - 2 * a.margin_mm - (a.cols - 1) * a.gap_mm) / a.cols
        panels = [Panel(f, i) for i, f in enumerate(a.panels)]
        y = a.margin_mm
        for r in range(0, len(panels), a.cols):
            row_h = 0.0
            for c, panel in enumerate(panels[r:r + a.cols]):
                i = r + c
                x = a.margin_mm + c * (cell_w + a.gap_mm)
                el, h = panel.element(x, y + reserve, cell_w, None)
                body.append(el)
                if labels_on and label_for(i):
                    body.append(make_label(label_for(i), x, y, a))
                row_h = max(row_h, reserve + h)
            y += row_h + a.gap_mm
        height = y - a.gap_mm + a.margin_mm

    root = ET.Element(f"{{{SVG_NS}}}svg", {
        "width": f"{width:.4f}mm", "height": f"{height:.4f}mm",
        "viewBox": f"0 0 {width:.4f} {height:.4f}", "version": "1.1",
    })
    root.append(ET.Element(f"{{{SVG_NS}}}rect", {
        "x": "0", "y": "0", "width": f"{width:.4f}", "height": f"{height:.4f}",
        "fill": "#ffffff", "id": "background",
    }))
    root.extend(body)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(a.output, encoding="utf-8", xml_declaration=True)
    print(f"wrote {a.output}: {width:.1f} x {height:.1f} mm, {len([b for b in body if b.tag.endswith('svg')])} panels")
    if a.max_height_mm and height > a.max_height_mm:
        print(f"WARNING: height {height:.1f} mm exceeds --max-height-mm {a.max_height_mm}", file=sys.stderr)


if __name__ == "__main__":
    main()
