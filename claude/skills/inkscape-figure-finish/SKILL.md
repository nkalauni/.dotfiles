---
name: inkscape-figure-finish
description: Final-pass finishing of scientific figures with the Inkscape CLI — combine panel SVGs into one multi-panel figure at an exact journal width with (a)/(b) labels, swap fonts, convert text to paths, and export final PDF/EPS/PNG/SVG at exact physical size. Use after plotting (e.g. with the scientific-visualization skill) whenever the user wants a polished, submission-ready figure file, panels assembled, or mentions Inkscape.
allowed-tools: Read Write Edit Bash Glob Grep
---

# Inkscape figure finishing

Plotting code decides what the figure *shows*. This skill handles the last step: putting the
panels together at the exact physical size and producing files that look the same everywhere.
Inkscape 1.4 is installed for this user at `~/.local/bin/inkscape` (an AppImage, so it prints
harmless banner/glibmm warnings on stderr). Both scripts use only the Python standard library and
run with the system `python3` (3.9).

Scripts (run from anywhere):
- `~/.claude/skills/inkscape-figure-finish/scripts/compose.py` puts panels into one SVG
- `~/.claude/skills/inkscape-figure-finish/scripts/finish.py` runs the Inkscape export

## Pipeline

1. **Draw each panel at its final size.** First work out the panel width:
   `cell = (total_width - (cols-1)*gap) / cols` (defaults: gap 3 mm, no margin). Create
   each matplotlib figure at exactly that width, e.g. `figsize=(cell/25.4, h/25.4)`.
   Then a font set to 7 pt stays 7 pt in print. Compose warns when it has to rescale a panel by
   more than 3%; if you see that warning, redraw the panel instead of accepting it.
   Export the panels as SVG with `bbox_inches=None` (the default) so the page size stays exact. Use
   `plt.rcParams["svg.fonttype"] = "none"` so text stays text until the final step. That makes
   `--font-replace` possible and lets Inkscape draw the glyphs. Don't add panel letters in
   matplotlib; compose adds them.
2. **Compose** (skip for a single-panel figure):
   ```bash
   python3 .../compose.py -o build/fig1.svg --width-mm 183 --cols 2 a.svg b.svg c.svg d.svg
   ```
   Options: `--gap-mm`, `--margin-mm`, `--labels lower|upper|paren|Paren|none|"a,b,c"`,
   `--label-size-pt 8`, `--label-font`, `--label-weight bold`, `--label-space-mm`,
   `--max-height-mm` (warns if the figure is too tall), `--force`. PNG panels such as micrographs
   are embedded at their stored DPI.
   For uneven layouts (one panel spanning the width, columns of different widths), pass `--layout layout.json`,
   with every position in mm:
   ```json
   {"width_mm": 183, "panels": [
     {"file": "wide.svg", "x": 0,  "y": 0,  "width": 183},
     {"file": "b.svg",    "x": 0,  "y": 65, "width": 90},
     {"file": "c.svg",    "x": 93, "y": 65, "width": 90}]}
   ```
   `y` is the top of the label row. The panel itself starts `label-space` below it. Panel ids get a
   prefix, so clip paths from different matplotlib files don't collide.
3. **Finish / export**:
   ```bash
   python3 .../finish.py build/fig1.svg -o final/fig1 --formats pdf,png,svg \
       --font-replace "DejaVu Sans=Liberation Sans" --dpi 600
   ```
   - Text is converted to paths by default, so fonts can never go missing. Use `--keep-text` only when
     the journal requires editable or searchable text (Nature, for example, asks for editable text in vector files). Then
     the PDF embeds the fonts.
   - The exported page is the SVG's own page, so composed figures keep their exact mm size. For a single
     loose SVG with extra whitespace, `--fit [--margin-mm 1]` shrinks the page to the drawing first.
   - PNG output gets an opaque white background (`--transparent` turns that off). EPS uses
     PostScript level 3. Note that EPS can't do transparency, so Inkscape rasterizes semi-transparent parts.
   - The script never overwrites existing files unless you pass `--force`. It prints each output's physical size; check that
     it matches the target.

## Fonts available here

Arial and Helvetica aren't installed. `Liberation Sans` matches Arial's metrics and `Nimbus Sans` matches
Helvetica's, and fontconfig already substitutes them for those names. Matplotlib's default
is DejaVu Sans, which is wider. When a journal asks for Arial or Helvetica, use
`--font-replace "DejaVu Sans=Liberation Sans"`, or set matplotlib's `font.family` to Liberation Sans
from the start, so the layout is computed with the correct metrics.

## Verify before handing over

- Render a preview with **poppler**, not Inkscape:
  `pdftoppm -png -r 150 -singlefile final/fig1.pdf /tmp/.../preview`, then look at it with Read.
  Inkscape's PDF *import* drops some transparency settings and makes correct PDFs look wrong.
  `gs` is also available.
- Check that the printed size matches the journal width. Look at label placement, overlaps, and clipping at the
  panel edges.
- Keep the composed SVG (`build/`) and the panel SVGs. They are the editable source. Re-run the pipeline
  rather than hand-editing the final files.

## Small edits without a GUI

The SVG is plain text, so small changes can be made directly in the composed SVG before running `finish.py`:
recolor (`sed 's/#1f77b4/#0072B2/g'`), nudge a label's `x`/`y` (in mm), or change label text.
Inkscape actions can also run headless, for example:
`inkscape in.svg --actions="select-by-id:p2-panel;object-to-path;export-filename:out.svg;export-do"`.
Run `inkscape --action-list` for the full list. There is no display on this machine, so GUI-only operations
don't work.
