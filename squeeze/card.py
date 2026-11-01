"""The shareable activity card: one SVG design, which the HTML version wraps."""
from html import escape

from . import dashboard, records
from .stats import format_compact

WIDTH, HEIGHT = 1200, 630
MARGIN = 64
BACKGROUND = "#14140F"
LEMON = "#F7E733"
INK = "#F5F5EC"
MUTED = "#A3A392"
RULE = "#3A3A30"
# System fonts only: an SVG in a GitHub README can't load anything external.
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"

CHART_LEFT, CHART_RIGHT = 660, WIDTH - MARGIN
CHART_TOP, CHART_BASE = 130, 325
MAX_BAR_WIDTH = 44
MAX_COMMAND = 16
RECORD_COLUMNS = (MARGIN, CHART_LEFT, 930)


def _text(x, y, content, size, fill=INK, weight=400, anchor="start"):
    return (
        f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
        f'text-anchor="{anchor}">{escape(str(content))}</text>'
    )


def _lines(n):
    # A seven-digit count would crowd the columns beside it.
    return f"{n:,}" if n < 100_000 else format_compact(n)


def _rounded_bar(x, width, top):
    """A bar anchored to the baseline, with 4px rounded corners at its data end."""
    r = min(4, width / 2, (CHART_BASE - top))
    return (
        f'<path fill="{LEMON}" d="M{x:.1f} {CHART_BASE}V{top + r:.1f}Q{x:.1f} {top:.1f} {x + r:.1f} {top:.1f}'
        f'H{x + width - r:.1f}Q{x + width:.1f} {top:.1f} {x + width:.1f} {top + r:.1f}V{CHART_BASE}Z"/>'
    )


def _chart(bars):
    slot = (CHART_RIGHT - CHART_LEFT) / len(bars)
    width = min(MAX_BAR_WIDTH, slot - 2)
    biggest = max(total for _, total in bars)
    parts = [f'<line x1="{CHART_LEFT}" x2="{CHART_RIGHT}" y1="{CHART_BASE}" y2="{CHART_BASE}" stroke="{RULE}" stroke-width="2"/>']
    labelled_peak = False
    for i, (label, total) in enumerate(bars):
        x = CHART_LEFT + slot * i
        center = x + slot / 2
        # Twelve month bars have no room for a year on each label.
        short = label.split()[0] if len(bars) > 7 else label
        # A hit area as wide as the slot, so a short bar is still easy to hover.
        group = [f"<g><title>{escape(label)}: {format_compact(total)} tokens saved</title>"]
        group.append(f'<rect x="{x:.1f}" y="{CHART_TOP}" width="{slot:.1f}" height="{CHART_BASE - CHART_TOP}" fill="transparent"/>')
        if total > 0:
            top = CHART_BASE - max(4, (CHART_BASE - CHART_TOP) * total / biggest)
            group.append(_rounded_bar(center - width / 2, width, top))
            if total == biggest and not labelled_peak:
                labelled_peak = True
                group.append(_text(f"{center:.1f}", f"{top - 10:.1f}", format_compact(total), 19, weight=700, anchor="middle"))
        group.append(_text(f"{center:.1f}", CHART_BASE + 26, short, 16, MUTED, anchor="middle"))
        group.append("</g>")
        parts.append("".join(group))
    return parts


def _tools(tools):
    if not tools:
        return []
    parts = [_text(CHART_LEFT, 384, "TOP TOOLS", 15, MUTED, 700)]
    track_left, track_right = CHART_LEFT + 96, CHART_RIGHT - 56
    for i, (tool, percent) in enumerate(tools):
        y = 411 + i * 24
        parts.append(_text(CHART_LEFT, y, tool[:10], 17))
        parts.append(f'<rect x="{track_left}" y="{y - 10}" width="{track_right - track_left}" height="8" rx="4" fill="{RULE}"/>')
        filled = (track_right - track_left) * percent / 100
        if filled > 0:
            parts.append(f'<rect x="{track_left}" y="{y - 10}" width="{max(8, filled):.1f}" height="8" rx="4" fill="{LEMON}"/>')
        parts.append(_text(CHART_RIGHT, y, f"{percent}%", 17, anchor="end"))
    return parts


def _stats_row(s):
    columns = [(f"{s.commands:,}", "commands" if s.commands != 1 else "command"), (s.streak, "day streak")]
    if s.change is not None:
        columns.append((f"{s.change:+d}%", f"vs {s.compare_name}"))
    parts = []
    for i, (value, label) in enumerate(columns):
        x = MARGIN + i * 190
        parts.append(_text(x, 418, value, 44, weight=800))
        parts.append(_text(x, 446, label, 17, MUTED))
    return parts


def _records(s):
    biggest = "—"
    if best := s.record_biggest:
        biggest = (
            f"{best['command'][:MAX_COMMAND]} · {_lines(best['lines_before'])} → {_lines(best['lines_after'])} lines "
            f"(-{records.squeeze_percent(best)}%)"
        )
    day = dashboard.format_day_record(s.record_day) if s.record_day else "—"
    longest = f"{s.record_streak} day{'s' if s.record_streak != 1 else ''}"
    parts = [f'<line x1="{MARGIN}" x2="{CHART_RIGHT}" y1="478" y2="478" stroke="{RULE}" stroke-width="2"/>']
    for x, label, value in zip(RECORD_COLUMNS, ("BIGGEST SQUEEZE", "BEST DAY", "LONGEST STREAK"), (biggest, day, longest)):
        parts.append(_text(x, 510, label, 15, MUTED, 700))
        parts.append(_text(x, 537, value, 20, weight=600))
    return parts


def _badges(names):
    parts = []
    x = MARGIN
    for name in names:
        # Text width is estimated: the viewer's font decides the real one, and this leaves room for it.
        width = len(name) * 9.2 + 28
        parts.append(f'<rect x="{x:.1f}" y="561" width="{width:.1f}" height="32" rx="16" fill="none" stroke="{LEMON}" stroke-width="1.5"/>')
        parts.append(_text(f"{x + width / 2:.1f}", 582, name, 15, weight=600, anchor="middle"))
        x += width + 8
    return parts


def render_svg(entries, period, today=None):
    s = dashboard.summarize(entries, period, today)
    headline = format_compact(s.total)
    fun = dashboard.equivalents(s.total).split(" · ")[0]
    description = (
        f"{format_compact(s.total)} tokens saved {s.title}, {s.range_label}. {s.commands} commands. "
        f"{s.streak} day streak. "
        + " ".join(f"{label}: {format_compact(total)}." for label, total in s.bars)
        + f" Badges: {', '.join(s.badges) or 'none'}."
    )
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" height="{HEIGHT}" '
        f'role="img" aria-labelledby="card-title card-desc" font-family="{FONT}">',
        f'<title id="card-title">Squeeze: {escape(headline)} tokens saved {escape(s.title)}</title>',
        f'<desc id="card-desc">{escape(description)}</desc>',
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{BACKGROUND}"/>',
        _text(MARGIN, 80, "🍋 SQUEEZE", 30, LEMON, 800),
        _text(CHART_RIGHT, 80, f"{s.title.upper()} · {s.range_label.upper()}", 18, MUTED, 600, "end"),
        # Long totals get a smaller size rather than running into the chart.
        _text(MARGIN - 4, 248, headline, 148 if len(headline) <= 5 else 112, LEMON, 800),
        # One flowing line, because the viewer's font decides how wide "tokens saved" is.
        f'<text x="{MARGIN}" y="298" font-size="36" font-weight="700" fill="{INK}">tokens saved '
        f'<tspan font-size="22" font-weight="400" fill="{MUTED}">(est.)</tspan></text>',
    ]
    if fun:
        parts.append(_text(MARGIN, 338, fun, 20, MUTED))
    parts += [*_stats_row(s), *_chart(s.bars), *_tools(s.tools), *_records(s), *_badges(s.badges), "</svg>"]
    return "\n".join(parts) + "\n"


def render_html(svg):
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Squeeze card</title>
<style>
html, body {{ margin: 0; min-height: 100%; background: {BACKGROUND}; }}
body {{ display: flex; align-items: center; justify-content: center; min-height: 100vh; }}
svg {{ display: block; width: 100%; max-width: {WIDTH}px; height: auto; }}
</style>
</head>
<body>
{svg}</body>
</html>
"""
