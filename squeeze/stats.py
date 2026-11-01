"""Line and token estimates."""


def estimate_tokens(text):
    return len(text) // 4


def _format_tokens(n):
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def summary(before, after):
    """Like: 812 lines → 19 lines (-97%) · ~5.2k → ~320 tokens (est.)"""
    lines_before, lines_after = len(before.splitlines()), len(after.splitlines())
    # int() rounds down, so -99.8% never displays as a -100% that would claim nothing is left.
    saved = f" (-{int(100 * (1 - lines_after / lines_before))}%)" if lines_after < lines_before else ""
    return (
        f"{lines_before} lines → {lines_after} lines{saved}"
        f" · ~{_format_tokens(estimate_tokens(before))} → ~{_format_tokens(estimate_tokens(after))} tokens (est.)"
    )
