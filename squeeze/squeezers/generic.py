"""Fallback for any command: first lines, last lines, and anything that looks like an error."""
import re
from itertools import groupby

from ..clean import ERROR_RE, collapse_runs, render_run, trim, without_numbers

HEAD = 3
TAIL_ON_FAILURE = 20
TAIL_ON_SUCCESS = 5
CONTEXT_BEFORE = 1
CONTEXT_AFTER = 2
MIN_HIDDEN = 3  # a note about hiding one or two lines costs as much as showing them
MAX_WARNINGS = 5

_WARNING_RE = re.compile(r"\bwarn(?:ing)?s?\b|⚠|\(!\)|deprecat", re.IGNORECASE)


def matches(command, output):
    return True


def squeeze(output, exit_code):
    runs = collapse_runs(output.split("\n"))
    tail = TAIL_ON_SUCCESS if exit_code == 0 else TAIL_ON_FAILURE
    keep = {*range(HEAD), *range(len(runs) - tail, len(runs))}

    seen = set()
    warnings = set()
    for i, (line, _) in enumerate(runs):
        if ERROR_RE.search(line):
            if line not in seen:
                seen.add(line)
                keep.update(range(i - CONTEXT_BEFORE, i + CONTEXT_AFTER + 1))
        # A successful build's warnings are the only thing in it worth reading, but they
        # can repeat by the thousand: one of each kind, no context, and only a few kinds.
        elif _WARNING_RE.search(line) and len(warnings) < MAX_WARNINGS and without_numbers(line) not in warnings:
            warnings.add(without_numbers(line))
            keep.add(i)

    result = []
    for kept, group in groupby(range(len(runs)), key=keep.__contains__):
        section = [runs[i] for i in group]
        hidden = sum(count for _, count in section)
        if kept or hidden < MIN_HIDDEN:
            result.extend(trim(render_run(*run)) for run in section)
        else:
            result.append(f"… {hidden} lines hidden …")
    return "\n".join(result)
