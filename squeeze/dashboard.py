"""The `sq stats` terminal dashboard."""
import calendar
from collections import defaultdict
from datetime import date, timedelta
from types import SimpleNamespace

from . import records
from .stats import format_compact, saved

WIDTH = 58
BAR_WIDTH = 12
TOP_TOOLS = 3
MAX_MONTHS = 12
# Rough sizes, to make big numbers feel real. These sit on top of the characters ÷ 4 estimate.
CONTEXT_WINDOW_TOKENS = 200_000
NOVEL_TOKENS = 120_000
PAGE_TOKENS = 500


def _day(d):
    return f"{d:%b} {d.day}"


def _month_start(d):
    return d.replace(day=1)


def _previous_month_start(d):
    return (_month_start(d) - timedelta(days=1)).replace(day=1)


def _next_month_start(d):
    return (_month_start(d) + timedelta(days=32)).replace(day=1)


def _window(period, entries, today):
    """(title, label for the range, first day, last day, what to compare with, its first and last day)."""
    if period == "week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        return "this week", f"{_day(start)} – {_day(end)}", start, end, "last week", start - timedelta(days=7), start - timedelta(days=1)
    if period == "month":
        start = _month_start(today)
        end = start.replace(day=calendar.monthrange(today.year, today.month)[1])
        return "this month", f"{today:%B %Y}", start, end, "last month", _previous_month_start(today), start - timedelta(days=1)
    start = min((entry["date"] for entry in entries), default=today)
    return "all time", f"since {start:%b %Y}", start, today, None, None, None


def _buckets(period, start, end):
    """(label, first day, last day) for each bar: days of a week, weeks of a month, or months."""
    if period == "week":
        return [(f"{start + timedelta(days=n):%a}", start + timedelta(days=n), start + timedelta(days=n)) for n in range(7)]
    if period == "month":
        return [
            (_day(day), day, min(day + timedelta(days=6), end))
            for day in (start + timedelta(days=n) for n in range(0, (end - start).days + 1, 7))
        ]
    months = []
    month = _month_start(start)
    while month <= end:
        months.append((f"{month:%b %y}", month, _next_month_start(month) - timedelta(days=1)))
        month = _next_month_start(month)
    return months[-MAX_MONTHS:]


def _sum_saved(entries, first, last):
    return sum(saved(entry) for entry in entries if first <= entry["date"] <= last)


def _bar_rows(bars):
    label_width = max(len(label) for label, _ in bars)
    biggest = max(total for _, total in bars)
    rows = []
    for label, total in bars:
        width = max(1, round(BAR_WIDTH * total / biggest)) if total > 0 else 0
        value = format_compact(total) if total else "—"
        rows.append(f"   {label:<{label_width}} {'▇' * width:<{BAR_WIDTH}}  {value}")
    return rows


def _change(entries, first, last, current):
    """Percent change from an earlier stretch of days, or None if there's nothing to compare with."""
    if first is None:
        return None
    earlier = _sum_saved(entries, first, last)
    return round(100 * (current - earlier) / earlier) if earlier > 0 else None


def change_arrow(percent):
    return "▲" if percent > 0 else "▼" if percent < 0 else "="


def _rough(n):
    return f"{n:,.0f}" if n >= 100 else f"{n:.1f}"


def equivalents(tokens):
    """Like: ≈ 3 context windows · ≈ 5 novels' worth of log spam you didn't read."""
    if tokens >= CONTEXT_WINDOW_TOKENS:
        windows = tokens / CONTEXT_WINDOW_TOKENS
        novels = tokens / NOVEL_TOKENS
        return f"≈ {_rough(windows)} context windows · ≈ {_rough(novels)} novels' worth of log spam you didn't read"
    if tokens >= PAGE_TOKENS:
        return f"≈ {tokens / PAGE_TOKENS:.0f} pages of log spam you didn't read"
    return ""


def _top_tools(entries):
    """[(tool, percent of tokens saved)], biggest first."""
    totals = defaultdict(int)
    for entry in entries:
        if saved(entry) > 0 and entry["tool"] != "none":
            totals[entry["tool"]] += saved(entry)
    overall = sum(totals.values())
    ranked = sorted(totals.items(), key=lambda item: item[1], reverse=True)[:TOP_TOOLS]
    return [(tool, percent) for tool, tokens in ranked if (percent := 100 * tokens // overall)]


def _top_repo(entries):
    totals = defaultdict(int)
    for entry in entries:
        totals[entry["repo"]] += saved(entry)
    best = max(totals.items(), key=lambda item: item[1], default=None)
    return best[0] if best and best[1] > 0 else ""


def describe_squeeze(entry):
    return f"{entry['command']} · {entry['lines_before']:,} → {entry['lines_after']:,} lines (-{records.squeeze_percent(entry)}%)"


def summarize(entries, period, today=None):
    """Everything the dashboard and the card show, worked out once."""
    today = today or date.today()
    title, range_label, start, end, compare_name, compare_first, compare_last = _window(period, entries, today)
    if compare_first:
        # Compare with the same point last time: one day of a new month against all of the last says nothing.
        compare_last = min(compare_last, compare_first + (today - start))
    current = [entry for entry in entries if start <= entry["date"] <= end]
    total = sum(map(saved, current))
    return SimpleNamespace(
        title=title,
        range_label=range_label,
        total=total,
        commands=sum(not entry["raw"] for entry in current),
        compare_name=compare_name,
        change=_change(entries, compare_first, compare_last, total),
        streak=records.current_streak(entries, today),
        bars=[(label, _sum_saved(entries, first, last)) for label, first, last in _buckets(period, start, end)],
        tools=_top_tools(current),
        biggest=records.biggest_squeeze(current),
        top_repo=_top_repo(current),
        record_biggest=records.biggest_squeeze(entries),
        record_day=records.best_day(entries),
        record_streak=records.longest_streak(entries),
        badges=records.earned_badges(entries),
    )


def format_day_record(day):
    return f"{_day(day[0])} · {format_compact(day[1])} tokens"


def render(entries, period, today=None, repo=None):
    s = summarize(entries, period, today)
    heading = f"🍋 SQUEEZE · {s.title}" + (f" · {repo}" if repo else "")
    lines = [f"{heading:<{WIDTH - len(s.range_label)}}{s.range_label}", ""]

    change = "" if s.change is None else f"{change_arrow(s.change)} {abs(s.change)}% vs {s.compare_name}"
    noun = "command" if s.commands == 1 else "commands"
    lines.append(f"   {f'{format_compact(s.total)} tokens saved':<26}{change}".rstrip())
    lines.append(f"   {f'{s.commands:,} {noun} squeezed':<26}{f'🔥 {s.streak}-day streak' if s.streak else ''}".rstrip())
    if fun := equivalents(s.total):
        lines.append(f"   {fun}")
    lines.append("")
    lines.extend(_bar_rows(s.bars))

    details = []
    if s.tools:
        details.append(f"   Top tools        {' · '.join(f'{tool} {percent}%' for tool, percent in s.tools)}")
    if s.biggest:
        details.append(f"   Biggest squeeze  {describe_squeeze(s.biggest)} 🏆")
    if not repo and s.top_repo:
        details.append(f"   Top repo         {s.top_repo}")
    if details:
        lines.extend(["", *details])

    lines.extend(["", "   🏆 Personal records"])
    lines.append(f"   Biggest squeeze  {describe_squeeze(s.record_biggest) if s.record_biggest else '—'}")
    lines.append(f"   Best day         {format_day_record(s.record_day) if s.record_day else '—'}")
    lines.append(f"   Longest streak   {s.record_streak} day{'s' if s.record_streak != 1 else ''}")
    lines.extend(["", f"   🎖 Badges ({len(s.badges)}/{len(records.BADGES)})  {' · '.join(s.badges) or '—'}"])
    return "\n".join(lines)
