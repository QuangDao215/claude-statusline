# claude-statusline

A custom three-line status line for [Claude Code](https://claude.com/claude-code), rendered by a single dependency-free Python script. Tokyo Night / Catppuccin Mocha palette, a powerline ribbon, live session **and** all-time cost tracking, and an activity-history sparkline of your daily usage.

```
╭─ designer ───────────────────────────────────────────────────────────────────╮
│   macOS   ~/projects/app   main a1b2c3  ↑2  •5   Opus 4.8 1M   high   14:32     │
│  ↓ 12.3k  ↑ 4.5k    $0.42 / $13.99k    ctx ███░░░ 42%   5h ██░░ 31% 2h14m       │
│   activity ▃▁▁▃▅▅▄▅▂▂█▇█▆   14d 2.3B   ▲ 365M                                    │
╰────────────────────────────────────────────────────────────────────────────────╯
```

*(Glyphs render with a Nerd Font; the sketch above approximates the layout.)*

## Features

- **Powerline ribbon (line 1):** OS icon, current path, git branch + short hash, commits ahead/behind the upstream (`↑`ahead / `↓`behind, shown only when nonzero), a dirty-file marker (`•N`), model name (with a `1M` tag when the 1M-token context is active), reasoning effort, and a clock. Segments stretch proportionally to fill the width.
- **Metrics (line 2):** tokens in / out, cost for this session and across all sessions to date (`$session / $all`), and three progress bars — context window, 5-hour limit, and 7-day limit — each with a status-coloured percentage and the time remaining until reset.
- **Activity history (line 3):** an ember-intensity sparkline of tokens used per day over the last 14 days (one block per day, taller and a deeper orange on heavier days, pale gold on light days, a soft ash baseline on idle days), followed by the window total and the peak day. The window is configurable, and the line can be turned off entirely. The daily buckets come from the same all-sessions scan that powers all-time cost, so it adds no extra work.
- **Status colours:** the context bar turns orange at 40% and red at 70%; the rate-limit bars turn orange at 70% and red at 90% (they alarm later by design).
- **Cheap to refresh:** the render is cached and only recomputed when the conversation actually advances.
- **No third-party packages** — just the Python standard library.

## Requirements

- Python 3.10 or newer.
- A [Nerd Font](https://www.nerdfonts.com/) so the icons render correctly (MesloLG Nerd Font is recommended). Set your terminal to use it; otherwise the glyphs show as `?`.

## Installation

1. Copy the script somewhere stable:
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
3. Start a fresh Claude Code session to pick up the change.

## Configuration

| Environment variable | Effect | Default |
|---|---|---|
| `CLAUDE_STATUSLINE_NAME` | Title shown on the box | `designer` |
| `CLAUDE_STATUSLINE_HISTORY` | Set to `0` to hide the activity-history line | `1` (shown) |
| `CLAUDE_STATUSLINE_HISTORY_DAYS` | Number of days in the activity sparkline (1–60) | `14` |
| `CLAUDE_CONFIG_DIR` | Base directory for the render cache | `~/.claude` |

## How it works

- **Render caching is gated on the transcript's modification time**, so the status line recomputes only when the conversation moves forward — making frequent refreshes inexpensive.
- **All-time cost** is computed by scanning `~/.claude/projects/**/*.jsonl`, de-duplicating usage records by message id, and applying per-model token rates; per-file totals are cached incrementally so the scan stays fast.
- **The activity sparkline** reuses that same scan: each transcript's usage is also bucketed by the local calendar day of the message, and those per-day token totals are cached per file alongside the cost. The line 3 sparkline is just the last N days of those buckets, so the history costs no extra file reads.

## Notes

- On a Claude subscription the payload's reported cost is `0`, so the dollar figures here are derived from token usage and public per-model rates; treat them as close estimates, not billing truth.
- The script reads only your local Claude Code session files and prints to stdout; it sends nothing anywhere.

## License

[MIT](LICENSE).
