"""Personal records, streaks and badges, all worked out from the history."""
from collections import Counter, defaultdict
from datetime import timedelta

from .stats import format_compact, saved

# Below this a "record" is just a small early run, not worth a line of an agent's context.
MIN_PR_TOKENS = 1000


def _active_days(entries):
    return {entry["date"] for entry in entries if not entry["raw"]}


def current_streak(entries, today):
    """Consecutive days squeezed, up to today. Yesterday still counts: today isn't over yet."""
    days = _active_days(entries)
    day = today if today in days else today - timedelta(days=1)
    streak = 0
    while day in days:
        streak += 1
        day -= timedelta(days=1)
    return streak


def longest_streak(entries):
    days = _active_days(entries)
    best = 0
    for day in days:
        if day - timedelta(days=1) not in days:
            length = 1
            while day + timedelta(days=length) in days:
                length += 1
            best = max(best, length)
    return best


def biggest_squeeze(entries):
    """The run that saved the most tokens, or None if nothing has saved any yet."""
    best = max(entries, key=saved, default=None)
    return best if best and saved(best) > 0 else None


def tokens_by_day(entries):
    totals = defaultdict(int)
    for entry in entries:
        totals[entry["date"]] += saved(entry)
    return totals


def best_day(entries):
    """(date, tokens saved), or None if no day has saved any yet."""
    best = max(tokens_by_day(entries).items(), key=lambda item: item[1], default=None)
    return best if best and best[1] > 0 else None


def squeeze_percent(entry):
    """Truncated, so -99.97% never displays as a -100.0% that would claim nothing is left."""
    before, after = entry["lines_before"], entry["lines_after"]
    return int(1000 * (1 - after / before)) / 10 if before and after < before else 0


def _busiest_pytest_week(entries):
    weeks = Counter(entry["date"].isocalendar()[:2] for entry in entries if entry["tool"] == "pytest" and not entry["raw"])
    return max(weeks.values(), default=0)


def _tool_runs(entries, tool):
    return sum(entry["tool"] == tool and not entry["raw"] for entry in entries)


BADGES = {
    "First Squeeze": lambda entries: bool(_active_days(entries)),
    "100k Club": lambda entries: sum(map(saved, entries)) >= 100_000,
    "1M Club": lambda entries: sum(map(saved, entries)) >= 1_000_000,
    "Week Streak": lambda entries: longest_streak(entries) >= 7,
    "npm Whisperer": lambda entries: _tool_runs(entries, "npm") >= 50,
    "Test Marathon": lambda entries: _busiest_pytest_week(entries) >= 100,
}


def earned_badges(entries):
    return [name for name, earned in BADGES.items() if earned(entries)]


def celebration(previous, entry):
    """One line about what this run achieved, or None. It goes into an agent's context, so it stays short."""
    after = [*previous, entry]
    news = [f"🎖 Badge unlocked: {name}" for name in earned_badges(after) if name not in earned_badges(previous)]

    best = biggest_squeeze(previous)
    if best and saved(entry) > saved(best) and saved(entry) >= MIN_PR_TOKENS:
        news.append(f"🏆 New PR: biggest squeeze ever (-{squeeze_percent(entry)}%)")

    # Only on the run that crosses the old record, or every later run today would claim it again.
    day = entry["date"]
    today_before = tokens_by_day(previous).get(day, 0)
    earlier = max((tokens for d, tokens in tokens_by_day(previous).items() if d != day), default=0)
    today_after = today_before + saved(entry)
    if earlier > 0 and today_before <= earlier < today_after and today_after >= MIN_PR_TOKENS:
        news.append(f"🏆 New PR: most tokens saved in a day ({format_compact(today_after)})")

    # A streak of 1 isn't a record, and a first day has nothing to beat.
    streak = longest_streak(after)
    if streak > longest_streak(previous) and streak >= 2:
        news.append(f"🏆 New PR: longest streak ({streak} days)")

    return " · ".join(news) or None
