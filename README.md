# claude-statusline

A custom two-line status line for [Claude Code](https://claude.com/claude-code), rendered by a single standalone Python script. Tokyo Night / Catppuccin Mocha palette, 24-bit truecolor, powerline ribbon, and live session + all-time cost tracking.

## What it shows

**Line 1 — powerline ribbon** (segments stretch proportionally to the full width):
- OS icon
- current path
- git branch, short commit hash, and dirty marker
- model name (with a `1M` tag when the 1M-token context is active)
- reasoning effort
- clock

**Line 2 — metrics:**
- tokens in / out (with download / upload icons)
- cost: this session / all sessions to date (`$session / $all`)
- three progress bars — context window, 5-hour limit, 7-day limit — each with a status-coloured percentage and the time remaining until reset

Both lines are framed in a titled box (the title defaults to `designer`).

### Colour thresholds
- The **context** bar turns orange at 40% and red at 70%.
- The **5-hour** and **7-day** bars turn orange at 70% and red at 90% (rate-limit alarms fire later by design).

## Requirements

- Python 3.10 or newer (no third-party packages)
- A [Nerd Font](https://www.nerdfonts.com/) for the glyphs — MesloLG Nerd Font is recommended. Set your terminal to use it; otherwise the icons render as `?`.

## Install

1. Copy `statusline.py` somewhere stable, for example:
   ```bash
   mkdir -p ~/.claude/statusline
   cp statusline.py ~/.claude/statusline/statusline.py
   ```
2. Point Claude Code at it in `~/.claude/settings.json`:
   ```json
   {
     "statusLine": {
       "type": "command",
       "command": "python3 \"$HOME/.claude/statusline/statusline.py\"",
       "async": true,
       "refreshInterval": 1
     }
   }
   ```
3. Restart Claude Code (or start a fresh session) to pick up the change.

## Customisation

| Environment variable | Effect | Default |
|---|---|---|
| `CLAUDE_STATUSLINE_NAME` | The title shown on the box | `designer` |
| `CLAUDE_CONFIG_DIR` | Base directory for the render cache | `~/.claude` |

## How it works

- The render is **cache-gated on the transcript's modification time**: it recomputes only when the conversation advances, so it is cheap to refresh frequently.
- The **all-time cost** is computed by scanning `~/.claude/projects/**/*.jsonl`, de-duplicating usage records by message id, and applying per-model token rates; the per-file totals are cached incrementally.

## License

MIT — see `LICENSE` (add your own if you wish to publish).
