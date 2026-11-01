"""Line and token estimates."""


def measure(text):
    """(lines, characters), the numbers everything else here works from."""
    return len(text.splitlines()), len(text)


def estimate_tokens(chars):
    return chars // 4


def _format_tokens(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def _format_lines(n):
    return f"{n} line" if n == 1 else f"{n} lines"


def summary(before, after):
    """Like: 812 lines → 19 lines (-97%) · ~5.2k → ~320 tokens (est.)"""
    lines_before, chars_before = before
    lines_after, chars_after = after
    # int() rounds down, so -99.8% never displays as a -100% that would claim nothing is left.
    saved = f" (-{int(100 * (1 - lines_after / lines_before))}%)" if lines_after < lines_before else ""
    return (
        f"{_format_lines(lines_before)} → {_format_lines(lines_after)}{saved}"
        f" · ~{_format_tokens(estimate_tokens(chars_before))} → ~{_format_tokens(estimate_tokens(chars_after))} tokens (est.)"
    )
