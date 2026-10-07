# Claude Code skills

Each skill is symlinked individually into `~/.claude/skills/` (the `synced/` folder there is
managed by Claude Code and is deliberately not tracked):

```bash
mkdir -p ~/.claude/skills
for s in ~/.dotfiles/claude/skills/*/; do ln -sfn "$s" ~/.claude/skills/"$(basename "$s")"; done
```

- `scientific-visualization/` is from [K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills)
  (MIT, v1.4, reviewed 2026-10-01), with the "Citing Scientific Agent Skills" section removed.
  Its examples use `uv run --python 3.13`, so `uv` must be installed.
- `inkscape-figure-finish/` is a custom skill for the final Inkscape pass (panel composition, text-to-path, exact-size export).
  It needs Inkscape 1.x on PATH. Without root, install the AppImage:

  ```bash
  mkdir -p ~/.local/opt ~/.local/bin
  curl -L -o ~/.local/opt/Inkscape.AppImage https://inkscape.org/gallery/item/59506/Inkscape-1.4.4.AppImage
  chmod +x ~/.local/opt/Inkscape.AppImage && ln -sf ~/.local/opt/Inkscape.AppImage ~/.local/bin/inkscape
  ```
