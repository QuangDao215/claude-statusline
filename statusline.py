#!/usr/bin/env python3
"""Custom statusline for Claude Code.

Layout:
  line 1  powerline ribbon (no caps):  OS | path | git | model(+ctx) | effort | clock
  line 2  metrics:  in | out | cost(sess/all)  ||  ctx-bar | 5h-bar | 7d-bar | plugins | skills
  line 3  activity history:  green-intensity sparkline of per-day tokens over the
          last N days (default 14) + N-day total + peak day. Toggle with
          CLAUDE_STATUSLINE_HISTORY=0; window with CLAUDE_STATUSLINE_HISTORY_DAYS.

Catppuccin Mocha palette. Line 1 uses powerline glyphs + Nerd Font icons (set
Terminal.app font to MesloLGS Nerd Font). 24-bit truecolor, UTF-8 forced.

Refresh: recompute is gated by the transcript's mtime -- expensive work runs only
when the conversation advances (an answer completes); idle repaints read the cache.
(The clock shows the last-answer time, not a live tick.)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

CACHE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))) / "statusline-cache"
COST_LOG = CACHE_DIR.parent / "statusline-cost.log"
PILL_NAME = os.environ.get("CLAUDE_STATUSLINE_NAME", "designer")
HIST_ENABLED = os.environ.get("CLAUDE_STATUSLINE_HISTORY", "1") != "0"
try:
    HIST_DAYS = max(1, min(60, int(os.environ.get("CLAUDE_STATUSLINE_HISTORY_DAYS", "14"))))
except ValueError:
    HIST_DAYS = 14

# ---- ANSI (24-bit truecolor) ----
R = "\033[0m"
BOLD = "\033[1m"
DEFBG = "\033[49m"


def _fg(r: int, g: int, b: int) -> str:
    return f"\033[38;2;{r};{g};{b}m"


def _bg(r: int, g: int, b: int) -> str:
    return f"\033[48;2;{r};{g};{b}m"


def _fgc(rgb: tuple[int, int, int]) -> str:
    return _fg(*rgb)


def _bgc(rgb: tuple[int, int, int]) -> str:
    return _bg(*rgb)


# ---- Catppuccin Mocha foregrounds ----
TEXT = _fg(0xCD, 0xD6, 0xF4)
SUBTEXT = _fg(0xA6, 0xAD, 0xC8)
OVERLAY = _fg(0x7F, 0x84, 0x9C)
SURF1 = _fg(0x45, 0x47, 0x5A)
BORDER = _fg(0x58, 0x5B, 0x70)
ROSEWATER = _fg(0xF5, 0xE0, 0xDC)
FLAMINGO = _fg(0xF2, 0xCD, 0xCD)
PINK = _fg(0xF5, 0xC2, 0xE7)
MAUVE = _fg(0xCB, 0xA6, 0xF7)
RED = _fg(0xF3, 0x8B, 0xA8)
MAROON = _fg(0xEB, 0xA0, 0xAC)
PEACH = _fg(0xFA, 0xB3, 0x87)
YELLOW = _fg(0xF9, 0xE2, 0xAF)
GREEN = _fg(0xA6, 0xE3, 0xA1)
TEAL = _fg(0x94, 0xE2, 0xD5)
SKY = _fg(0x89, 0xDC, 0xEB)
SAPPHIRE = _fg(0x74, 0xC7, 0xEC)
BLUE = _fg(0x89, 0xB4, 0xFA)
LAVENDER = _fg(0xB4, 0xBE, 0xFE)
PANEL_BG = _bg(0x1E, 0x1E, 0x2E)
ROW1_BG = _bg(0x18, 0x18, 0x25)    # mantle -- dark backing behind the ribbon row
LINE2_BG = _bg(0x2A, 0x3D, 0x6E)   # lively deep-blue band for the metrics row
BOX_FRAME = _fg(0x89, 0xB4, 0xFA)  # blue box frame

# ribbon segment backgrounds
SEG = {
    "red": (0xF3, 0x8B, 0xA8),
    "peach": (0xFA, 0xB3, 0x87),
    "yellow": (0xF9, 0xE2, 0xAF),
    "green": (0xA6, 0xE3, 0xA1),
    "sapphire": (0x74, 0xC7, 0xEC),
    "lavender": (0xB4, 0xBE, 0xFE),
}
CRUST = (0x11, 0x11, 0x1B)
FILLER = (0x3B, 0x42, 0x61)  # empty spacer segment that spans the ribbon to full width

# ---- activity-history sparkline ----
SPARK_BLOCKS = "▁▂▃▄▅▆▇█"  # 1/8..8/8 block heights
# heat scale for the sparkline glyph color: an inverted ember ramp -- soft ash for
# idle, then pale gold for the lightest days deepening to a rich orange for the
# heaviest (more activity == darker orange; kept vivid, not brown, on the blue band)
HEAT = [
    (0x8E, 0x81, 0x7B),  # idle / zero -- soft warm ash
    (0xFB, 0xDF, 0xA6),  # least active -- pale gold (lightest)
    (0xF8, 0xC1, 0x82),  # light peach-orange
    (0xF0, 0x9E, 0x52),  # orange
    (0xE4, 0x77, 0x28),  # most active -- deep orange (darkest)
]

# ---- glyphs (Nerd Font) -- U-escape text only (literal PUA chars unreliable via tools) ----
PL_SEP = "\U0000e0b0"        # triangle separator
GIT_ICON = "\U0000e0a0"      # branch
GIT_AHEAD_ICON = "\U0000f062"   # arrow-up -> commits ahead of upstream (unpushed)
GIT_BEHIND_ICON = "\U0000f063"  # arrow-down -> commits behind upstream (unpulled)
CLOCK_ICON = "\U0000f017"    # clock
ICON_MAC = "\U000f0035"      # apple
ICON_LINUX = "\U0000f17c"    # linux
ICON_OS = "\U0000f108"       # generic desktop
ICON_CTX = "\U0000f1c0"      # database -> context
ICON_5H = "\U0000f253"       # hourglass -> 5h
ICON_WK = "\U0000f073"       # calendar -> 7d
ICON_PLUG = "\U0000f1e6"     # plug
ICON_SKILL = "\U000f07df"    # skills
ICON_HIST = "\U0000f201"     # line-chart -> activity history
ICON_IN = "\U0000f019"       # download -> tokens in
ICON_OUT = "\U0000f093"      # upload -> tokens out
ICON_COST = "\U0000efc8"     # currency-usd -> cost
RATE_IN = 15.00
RATE_OUT = 75.00

ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def vis_len(s: str) -> int:
    return len(ANSI_RE.sub("", s))


def fmt_tok(n: int) -> str:
    n = int(n or 0)
    if n >= 1_000_000_000:
        return f"{n / 1e9:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1e6:.1f}M"
    if n >= 1_000:
        return f"{n / 1e3:.0f}k"
    return str(n)


def fmt_eta(resets_at: int) -> str:
    """Compact 'time until reset' for a rate-limit bucket (e.g. 2h14m, 3d5h, 45m)."""
    if not resets_at:
        return ""
    sec = int(resets_at) - int(time.time())
    if sec <= 0:
        return "now"
    d, rem = divmod(sec, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d}d{h}h"
    if h:
        return f"{h}h{m}m"
    return f"{m}m"


def os_icon() -> str:
    if sys.platform == "darwin":
        return ICON_MAC
    if sys.platform.startswith("linux"):
        return ICON_LINUX
    return ICON_OS


def context_tag(model_id: str, cw_size: int) -> str:
    if "[1m]" in model_id.lower() or cw_size >= 1_000_000:
        return "1M"
    if cw_size >= 1000:
        return f"{cw_size // 1000}k"
    return ""


def bar(pct: float, warn: float, crit: float, width: int = 8) -> str:
    try:
        pct = float(pct)
    except (TypeError, ValueError):
        pct = 0.0
    pct = max(0.0, min(100.0, pct))
    filled = max(0, min(width, int(round(pct / 100 * width))))
    color = GREEN if pct < warn else (PEACH if pct < crit else RED)
    return f"{color}{'█' * filled}{SURF1}{'░' * (width - filled)}{R}"


def pct_color(pct: float, warn: float, crit: float) -> str:
    try:
        pct = float(pct)
    except (TypeError, ValueError):
        pct = 0.0
    return GREEN if pct < warn else (PEACH if pct < crit else RED)


def display_path(p: str) -> str:
    home = str(Path.home())
    if p == home:
        return "~"
    if p.startswith(home + os.sep):
        return "~" + p[len(home):]
    return p


def git_info(cwd: str) -> tuple[str, str, int, int, int]:
    def g(args: list[str]) -> str:
        try:
            r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=1.0)
            return r.stdout.strip()
        except Exception:
            return ""

    branch = g(["rev-parse", "--abbrev-ref", "HEAD"])
    if not branch:
        return "", "", 0, 0, 0
    short = g(["rev-parse", "--short=9", "HEAD"])
    porcelain = g(["status", "--porcelain"])
    dirty = len([ln for ln in porcelain.splitlines() if ln.strip()]) if porcelain else 0
    # commits behind / ahead of the upstream branch; one call, empty when no
    # tracking branch is configured (detached HEAD, no remote) -> stays 0.
    ahead = behind = 0
    lr = g(["rev-list", "--left-right", "--count", "@{u}...HEAD"]).split()
    if len(lr) == 2 and lr[0].isdigit() and lr[1].isdigit():
        behind, ahead = int(lr[0]), int(lr[1])
    return branch, short, dirty, ahead, behind


def parse_transcript(path: str) -> tuple[float, int, int, int, int]:
    """Return (session_cost_usd, current_ctx_tokens, n_skills, tok_in, tok_out)."""
    cost = 0.0
    cur_ctx = tok_in = tok_out = 0
    skills: dict[str, None] = {}
    seen: set = set()
    if not path or not os.path.isfile(path):
        return cost, cur_ctx, len(skills), tok_in, tok_out
    skill_pat = re.compile(r'"name"\s*:\s*"Skill"[^}]*?"skill"\s*:\s*"([^"]+)"')
    try:
        with open(path, "r", errors="ignore") as fh:
            for ln in fh:
                if '"Skill"' in ln:
                    for m in skill_pat.finditer(ln):
                        skills.setdefault(m.group(1), None)
                if '"usage"' not in ln:
                    continue
                try:
                    obj = json.loads(ln)
                except ValueError:
                    continue
                msg = obj.get("message") if isinstance(obj, dict) else None
                u = msg.get("usage") if isinstance(msg, dict) else None
                if not isinstance(u, dict):
                    continue
                mid = msg.get("id")
                if mid is not None:
                    if mid in seen:
                        continue
                    seen.add(mid)
                it = int(u.get("input_tokens", 0) or 0)
                cc = int(u.get("cache_creation_input_tokens", 0) or 0)
                cr = int(u.get("cache_read_input_tokens", 0) or 0)
                ot = int(u.get("output_tokens", 0) or 0)
                cost += (it * RATE_IN + cc * RATE_IN * 1.25 + cr * RATE_IN * 0.1 + ot * RATE_OUT) / 1e6
                tok_in += it + cc + cr
                tok_out += ot
                ctx = it + cc + cr
                if ctx:
                    cur_ctx = ctx
    except OSError:
        pass
    return cost, cur_ctx, len(skills), tok_in, tok_out


RATES = {"opus": (15.0, 75.0), "sonnet": (3.0, 15.0), "haiku": (0.80, 4.0)}


def rates_for(model_name: str) -> tuple[float, float]:
    m = (model_name or "").lower()
    for key, rate in RATES.items():
        if key in m:
            return rate
    return RATES["opus"]


def _file_stats(path: Path) -> tuple[float, dict[str, int]]:
    """Return (cost_usd, {local_day: tokens}) for one transcript.

    Usage is counted once per message id (transcripts log each message multiple
    times). Tokens are input + cache + output, bucketed by the local calendar day
    of the message timestamp so the sparkline matches how a person reads "days".
    """
    cost = 0.0
    days: dict[str, int] = {}
    seen: set = set()
    try:
        with open(path, "r", errors="ignore") as fh:
            for ln in fh:
                if '"usage"' not in ln:
                    continue
                try:
                    obj = json.loads(ln)
                except ValueError:
                    continue
                msg = obj.get("message") if isinstance(obj, dict) else None
                u = msg.get("usage") if isinstance(msg, dict) else None
                if not isinstance(u, dict):
                    continue
                mid = msg.get("id")
                if mid is not None:
                    if mid in seen:
                        continue
                    seen.add(mid)
                ri, ro = rates_for(msg.get("model"))
                it = int(u.get("input_tokens", 0) or 0)
                cc = int(u.get("cache_creation_input_tokens", 0) or 0)
                cr = int(u.get("cache_read_input_tokens", 0) or 0)
                ot = int(u.get("output_tokens", 0) or 0)
                cost += (it * ri + cc * ri * 1.25 + cr * ri * 0.1 + ot * ro) / 1e6
                ts = obj.get("timestamp") if isinstance(obj, dict) else None
                if ts:
                    try:
                        day = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d")
                    except ValueError:
                        continue
                    days[day] = days.get(day, 0) + it + cc + cr + ot
    except OSError:
        pass
    return cost, days


def all_sessions_stats() -> tuple[float, dict[str, int]]:
    """Total estimated cost + per-local-day token totals across every transcript.

    Walks ~/.claude/projects/**/*.jsonl; re-reads only files whose mtime changed
    since the last scan (others come from the cache), so steady state is one
    transcript re-read per answer. The per-day token buckets feed the activity
    sparkline on line 3.
    """
    cache_path = CACHE_DIR / "statscache.json"
    cache: dict = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text())
        except Exception:
            cache = {}
    projects = CACHE_DIR.parent / "projects"
    total = 0.0
    by_day: dict[str, int] = defaultdict(int)
    fresh: dict = {}
    if projects.is_dir():
        for f in projects.rglob("*.jsonl"):
            try:
                mt = f.stat().st_mtime
            except OSError:
                continue
            key = str(f)
            ent = cache.get(key)
            if isinstance(ent, list) and len(ent) == 3 and abs(ent[0] - mt) < 1e-6:
                c, days = ent[1], ent[2]
            else:
                c, days = _file_stats(f)
            fresh[key] = [mt, c, days]
            total += c
            for d, t in days.items():
                by_day[d] += int(t)
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(fresh))
    except OSError:
        pass
    return total, dict(by_day)


def day_series(by_day: dict[str, int], n_days: int) -> list[int]:
    """The last n_days of per-day totals, oldest first, ending with today."""
    today = datetime.now().date()
    return [int(by_day.get((today - timedelta(days=i)).strftime("%Y-%m-%d"), 0)) for i in range(n_days - 1, -1, -1)]


def sparkline(vals: list[int]) -> str:
    """Green-intensity block sparkline; idle days render as a dim grey baseline."""
    mx = max(vals) if vals else 0
    if mx <= 0:
        return f"{SURF1}{'▁' * len(vals)}{R}"
    out: list[str] = []
    for v in vals:
        if v <= 0:
            out.append(f"{_fgc(HEAT[0])}▁")
            continue
        frac = v / mx
        height = min(7, int(frac * 7.999))
        level = min(4, 1 + int(frac * 3.999))
        out.append(f"{_fgc(HEAT[level])}{SPARK_BLOCKS[height]}")
    return "".join(out) + R


def powerline(segments: list[tuple[str, tuple[int, int, int]]]) -> str:
    """Contiguous colored segments with triangle separators; flat ends (no caps)."""
    if not segments:
        return ""
    text_fg = _fgc(CRUST)
    parts: list[str] = []
    for i, (text, bg) in enumerate(segments):
        if i > 0:
            parts.append(_fgc(segments[i - 1][1]) + _bgc(bg) + PL_SEP)
        parts.append(_bgc(bg) + text_fg + BOLD + f" {text} ")
    parts.append(R)
    return "".join(parts)


def make_box(lines: list[str], title: str, bgs: list[str]) -> str:
    inner = max(vis_len(ln) for ln in lines)
    pill = f"─ {title} "
    pill_styled = f"{BOX_FRAME}─ {MAUVE}{BOLD}{title}{R}{BOX_FRAME} "
    dashes = inner - vis_len(pill)
    if dashes < 0:
        inner += -dashes
        dashes = 0
    out = [f"{BOX_FRAME}╭{pill_styled}{'─' * dashes}╮{R}"]
    for ln, bg in zip(lines, bgs):
        pad = " " * (inner - vis_len(ln))
        body = ln.replace(R, R + bg)
        out.append(f"{BOX_FRAME}│{bg}{body}{bg}{pad}{R}{BOX_FRAME}│{R}")
    out.append(f"{BOX_FRAME}╰{'─' * inner}╯{R}")
    return "\n".join(out)


def render(payload: dict) -> str:
    ws = payload.get("workspace") or {}
    cwd = str(ws.get("current_dir") or payload.get("cwd") or os.getcwd())
    path_disp = display_path(cwd)

    model = payload.get("model") or {}
    raw_name = model.get("display_name") or model.get("id") or "?"
    base_name = re.sub(r"\s*\((?:1M context|1M|\d+k)\)\s*$", "", raw_name).strip()

    cw = payload.get("context_window") or {}
    cw_size = int(cw.get("context_window_size") or 0) or 200_000
    tag = context_tag(str(model.get("id") or ""), cw_size)
    model_name = f"{base_name} ({tag})" if tag else base_name

    effort = str((payload.get("effort") or {}).get("level") or "").strip()

    rl = payload.get("rate_limits") or {}
    five = rl.get("five_hour") or {}
    seven = rl.get("seven_day") or {}
    fh_pct = five.get("used_percentage") or 0
    wk_pct = seven.get("used_percentage") or 0
    fh_eta = fmt_eta(int(five.get("resets_at") or 0))
    wk_eta = fmt_eta(int(seven.get("resets_at") or 0))

    cost, cur_ctx, n_skills, tok_in, tok_out = parse_transcript(str(payload.get("transcript_path") or ""))
    total_cost, by_day = all_sessions_stats()

    ctx_tokens = int(cw.get("total_input_tokens") or 0) or cur_ctx
    ctx_pct = cw.get("used_percentage")
    if not isinstance(ctx_pct, (int, float)):
        ctx_pct = (ctx_tokens / cw_size * 100) if cw_size else 0.0

    branch, short, dirty, ahead, behind = git_info(cwd)
    plugins = list((ws.get("enabledPlugins") or {}).keys())

    # ---- line 2: metrics (tokens + cost left, bars right) ----
    ctx_c, fh_c, wk_c = pct_color(ctx_pct, 40, 70), pct_color(fh_pct, 70, 90), pct_color(wk_pct, 70, 90)
    metrics = (
        f" {TEAL}{ICON_IN} {fmt_tok(tok_in)}{R}"
        f"  {SKY}{ICON_OUT} {fmt_tok(tok_out)}{R}"
        f"  {YELLOW}{ICON_COST}{R} {GREEN}${cost:,.2f}{OVERLAY}/{PEACH}${total_cost:,.2f}{R}"
        f"  {BORDER}┃{R} "
        f"{MAUVE}{ICON_CTX}{R} {bar(ctx_pct, 40, 70)} {ctx_c}{float(ctx_pct):>3.0f}%{R}"
        f"  {BLUE}{ICON_5H} 5h{R} {bar(fh_pct, 70, 90)} {fh_c}{float(fh_pct):>3.0f}%{R} {SAPPHIRE}{fh_eta}{R}"
        f"  {LAVENDER}{ICON_WK} 7d{R} {bar(wk_pct, 70, 90)} {wk_c}{float(wk_pct):>3.0f}%{R} {LAVENDER}{wk_eta}{R}"
    )
    if plugins:
        metrics += f"  {PEACH}{ICON_PLUG} {', '.join(plugins)}{R}"
    if n_skills:
        metrics += f"  {MAUVE}{ICON_SKILL} {n_skills}{R}"
    metrics += " "  # trailing margin; the ribbon spans to this same width so both right edges align

    # ---- line 3: activity history (per-day tokens over HIST_DAYS) ----
    activity = ""
    if HIST_ENABLED:
        hist = day_series(by_day, HIST_DAYS)
        spark = sparkline(hist)
        tot = fmt_tok(sum(hist))
        peak = fmt_tok(max(hist) if hist else 0)
        activity = (
            f" {MAUVE}{ICON_HIST}{R} {SUBTEXT}activity{R} {spark}"
            f"  {OVERLAY}{HIST_DAYS}d{R} {TEAL}{tot}{R}"
            f"  {PEACH}▲{R} {YELLOW}{peak}{R} "
        )

    # ---- line 1: powerline ribbon, spanned to the metrics width (clock right-aligned) ----
    base_segs: list[tuple[str, tuple[int, int, int]]] = [
        (os_icon(), SEG["red"]),
        (path_disp, SEG["peach"]),
    ]
    if branch:
        gtext = f"{GIT_ICON} {branch} {short}"
        if ahead:
            gtext += f"  {GIT_AHEAD_ICON} {ahead}"
        if behind:
            gtext += f"  {GIT_BEHIND_ICON} {behind}"
        if dirty:
            gtext += f"  •{dirty}"
        base_segs.append((gtext, SEG["yellow"]))
    base_segs.append((model_name, SEG["green"]))
    if effort:
        base_segs.append((effort, SEG["sapphire"]))
    time_text = f"{CLOCK_ICON} {datetime.now().strftime('%H:%M')}"

    all_segs = base_segs + [(time_text, SEG["lavender"])]
    target_w = max(vis_len(metrics), vis_len(activity))
    need = target_w - vis_len(powerline(all_segs))
    if need > 0:
        # spread the slack across every segment proportional to its text length;
        # all segments left-align their content, the clock right-aligns (flush to edge)
        lens = [max(1, len(t)) for t, _ in all_segs]
        tot = sum(lens)
        extra = [need * l // tot for l in lens]
        for i in range(need - sum(extra)):
            extra[i % len(extra)] += 1
        segs = []
        for (t, bg), e in zip(all_segs, extra):
            lpad = e // 2
            segs.append((" " * lpad + t + " " * (e - lpad), bg))
    else:
        segs = all_segs
    ribbon = powerline(segs)

    lines = [ribbon, metrics]
    bgs = [ROW1_BG, LINE2_BG]
    if activity:
        lines.append(activity)
        bgs.append(LINE2_BG)  # share the metrics band so the two rows read as one panel
    return make_box(lines, PILL_NAME, bgs)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    session_id = str(payload.get("session_id") or "default")
    transcript = str(payload.get("transcript_path") or "")
    cache_file = CACHE_DIR / f"{re.sub(r'[^A-Za-z0-9_-]', '_', session_id)}.cache"

    tmtime = 0.0
    if transcript and os.path.isfile(transcript):
        try:
            tmtime = os.path.getmtime(transcript)
        except OSError:
            pass

    if cache_file.exists():
        try:
            cached = cache_file.read_text()
            head, _, body = cached.partition("\n")
            if abs(float(head) - tmtime) < 1e-6:
                sys.stdout.write(body)
                return
        except (OSError, ValueError):
            pass

    out = render(payload)
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(f"{tmtime}\n{out}")
    except OSError:
        pass
    sys.stdout.write(out)


if __name__ == "__main__":
    main()
