"""The `sq stats` terminal dashboard."""
import calendar
from collections import defaultdict
from datetime import date, timedelta

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


def _bars(period, entries, start, end):
    buckets = _buckets(period, start, end)
    totals = [_sum_saved(entries, first, last) for _, first, last in buckets]
    label_width = max(len(label) for label, _, _ in buckets)
    biggest = max(totals, default=0)
    rows = []
    for (label, _, _), total in zip(buckets, totals):
        width = max(1, round(BAR_WIDTH * total / biggest)) if total > 0 else 0
        value = format_compact(total) if total else "—"
        rows.append(f"   {label:<{label_width}} {'▇' * width:<{BAR_WIDTH}}  {value}")
    return rows


def _change(entries, name, first, last, current):
    if name is None:
        return ""
    earlier = _sum_saved(entries, first, last)
    if earlier <= 0:
        return ""
    percent = round(100 * (current - earlier) / earlier)
    arrow = "▲" if percent > 0 else "▼" if percent < 0 else "="
    return f"{arrow} {abs(percent)}% vs {name}"


def equivalents(tokens):
    """Like: ≈ 3 context windows · ≈ 5 novels' worth of log spam you didn't read."""
    if tokens >= CONTEXT_WINDOW_TOKENS:
        windows = tokens / CONTEXT_WINDOW_TOKENS
        novels = tokens / NOVEL_TOKENS
        return f"≈ {windows:.1f} context windows · ≈ {novels:.1f} novels' worth of log spam you didn't read"
    if tokens >= PAGE_TOKENS:
        return f"≈ {tokens / PAGE_TOKENS:.0f} pages of log spam you didn't read"
    return ""


def _top_tools(entries):
    totals = defaultdict(int)
    for entry in entries:
        if saved(entry) > 0 and entry["tool"] != "none":
            totals[entry["tool"]] += saved(entry)
    overall = sum(totals.values())
    ranked = sorted(totals.items(), key=lambda item: item[1], reverse=True)[:TOP_TOOLS]
    return " · ".join(f"{tool} {100 * tokens // overall}%" for tool, tokens in ranked)


def _top_repo(entries):
    totals = defaultdict(int)
    for entry in entries:
        totals[entry["repo"]] += saved(entry)
    best = max(totals.items(), key=lambda item: item[1], default=None)
    return best[0] if best and best[1] > 0 else ""


def describe_squeeze(entry):
    return f"{entry['command']} · {entry['lines_before']:,} → {entry['lines_after']:,} lines (-{records.squeeze_percent(entry)}%)"


def render(entries, period, today=None, repo=None):
    today = today or date.today()
    title, range_label, start, end, compare_name, compare_first, compare_last = _window(period, entries, today)
    if compare_first:
        # Compare with the same point last time: one day of a new month against all of the last says nothing.
        compare_last = min(compare_last, compare_first + (today - start))
    current =[entry for entry in entries if start <= entry["date"] <= end]
    total = sum(map(saved, current))
    commands = sum(not entry["raw"] for entry in current)

    heading = f"🍋 SQUEEZE · {title}" + (f" · {repo}" if repo else "")
    lines = [f"{heading:<{WIDTH - len(range_label)}}{range_label}", ""]

    streak = records.current_streak(entries, today)
    change = _change(entries, compare_name, compare_first, compare_last, total)
    lines.append(f"   {f'{format_compact(total)} tokens saved':<26}{change}".rstrip())
    noun = "command" if commands == 1 else "commands"
    lines.append(f"   {f'{commands:,} {noun} squeezed':<26}{f'🔥 {streak}-day streak' if streak else ''}".rstrip())
    if fun := equivalents(total):
        lines.append(f"   {fun}")
    lines.append("")
    lines.extend(_bars(period, entries, start, end))

    details = []
    if tools := _top_tools(current):
        details.append(f"   Top tools        {tools}")
    if best := records.biggest_squeeze(current):
        details.append(f"   Biggest squeeze  {describe_squeeze(best)} 🏆")
    if not repo and (top_repo := _top_repo(current)):
        details.append(f"   Top repo         {top_repo}")
    if details:
        lines.extend(["", *details])

    lines.extend(["", "   🏆 Personal records"])
    best = records.biggest_squeeze(entries)
    day = records.best_day(entries)
    lines.append(f"   Biggest squeeze  {describe_squeeze(best) if best else '—'}")
    lines.append(f"   Best day         {f'{_day(day[0])} · {format_compact(day[1])} tokens' if day else '—'}")
    longest = records.longest_streak(entries)
    lines.append(f"   Longest streak   {longest} day{'s' if longest != 1 else ''}")

    earned = records.earned_badges(entries)
    lines.extend(["", f"   🎖 Badges ({len(earned)}/{len(records.BADGES)})  {' · '.join(earned) or '—'}"])
    return "\n".join(lines)
