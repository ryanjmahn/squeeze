"""Picks a squeezer for a command.

To add one: create a module with matches(command, output) -> bool and
squeeze(output, exit_code) -> str, then list it in SQUEEZERS. `command` is the
argv list; `output` has already been through clean().
"""
from ..clean import clean
from . import generic, pytest

SQUEEZERS = [pytest]


def squeeze(command, raw, exit_code):
    """Squeeze raw output. A squeezing bug must never hide a failure, so each step falls back to a blunter one."""
    try:
        output = clean(raw)
    except Exception:
        return raw
    for squeezer in (*SQUEEZERS, generic):
        try:
            if not squeezer.matches(command, output):
                continue
            result = squeezer.squeeze(output, exit_code)
        except Exception:
            continue
        # Nothing left from real output means the squeezer misread it.
        if result.strip() or not output.strip():
            return result
    return raw
