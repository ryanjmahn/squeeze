"""pytest: the totals, each failure's location and error, warnings collapsed into counts."""
import re
from collections import Counter
from pathlib import Path

from ..clean import cap_error_lines, last_lines, trim

NAMES = {"pytest", "py.test"}
MY_FRAMES = 2
FALLBACK_LINES = 10

_SESSION_RE = re.compile(r"^=+ test session starts =+$", re.MULTILINE)
_SECTION_RE = re.compile(r"^={3,} (.+?) ={3,}$")
_BLOCK_RE = re.compile(r"^_+ (.+?) _+$")
_FRAME_DIVIDER_RE = re.compile(r"^(_ )+_?$")
# The optional second word allows pytest 9's "59 subtests passed".
_TOTALS_RE = re.compile(r"^=*\s*((?:\d+ \w+(?: \w+)?|no tests ran)(?:, \d+ \w+(?: \w+)?)* in [\d.]+s(?: \(.*\))?)\s*=*$")
_BANNER_RE = re.compile(r"^!{3,} (.+?) !{3,}$")
_SUMMARY_RE = re.compile(r"^(?:FAILED|ERROR|SUBFAILED(\(.*?\))?) (\S.*?)(?: - (.*))?$")
_FRAME_RE = re.compile(r"^(?!E\s)([^\s>].*?\.py):(\d+):(?: (.*))?$")
_NOT_MY_CODE_RE = re.compile(r"site-packages|dist-packages|/lib/python\d|<frozen")
_NATIVE_FRAME_RE = re.compile(r'^\s*File "(.+?)", line (\d+), in ')
_CARETS_RE = re.compile(r"^\s*[~^]+\s*$")
_CAPTURED_RE = re.compile(r"^-+ (Captured .*?) -+$")
_COVERAGE_FAILED_RE = re.compile(r"^FAIL Required test coverage.*$", re.MULTILINE)
_WARNING_RE = re.compile(r"^\s*(\S+?):\d+: (\w*Warning):")
_WARNED_NODE_RE = re.compile(r"^\S.*?(?:: (\d+) warnings?)?$")


def matches(command, output):
    # A false match (`pip install pytest`) is harmless: squeeze() finds no totals and raises.
    return any(Path(arg).name in NAMES for arg in command) or bool(_SESSION_RE.search(output))


def squeeze(output, exit_code):
    lines = output.split("\n")
    totals = next((m[1] for line in reversed(lines) if (m := _TOTALS_RE.match(line))), None)
    if totals is None:
        raise ValueError("no pytest totals found, so this run may have crashed")

    root = next((line.split(": ", 1)[1] for line in lines[:10] if line.startswith("rootdir: ")), None)
    sections = _split_sections(lines)
    failures = _failures(sections, root)
    # pytest's own count is the check on our parsing: never report fewer failures than it did.
    expected = sum(int(n) for n, _ in re.findall(r"(\d+) (failed|errors?)\b", totals))
    if len(failures) != expected:
        raise ValueError(f"parsed {len(failures)} failures, pytest reported {expected}")
    coverage = _COVERAGE_FAILED_RE.findall(output)
    # Exit 5 means no tests ran. Any other failure code with no failed tests and no
    # coverage failure has a cause we didn't parse, so it mustn't look like a pass.
    if exit_code not in (0, 5) and not failures and not coverage:
        raise ValueError(f"exit {exit_code} with no failed tests")

    head = f"✓ {totals}" if exit_code == 0 and not failures else totals
    banners = [m[1] for line in lines if (m := _BANNER_RE.match(line))]
    warnings = _warnings(sections.get("warnings summary", []), root, totals)
    parts = ["\n".join([head, *banners, *coverage]), *failures, warnings]
    return "\n\n".join(part for part in parts if part)


def _split_sections(lines):
    sections = {}
    current = None
    for line in lines:
        if m := _SECTION_RE.match(line):
            current = sections.setdefault(m[1], [])
        elif current is not None:
            current.append(line)
    return sections


def _failures(sections, root):
    """One rendered entry per failure. Every summary line gets an entry, parsed block or not."""
    summary = [
        (f"{m[2]} {m[1]}" if m[1] else m[2], m[3])
        for line in sections.get("short test summary info", [])
        if (m := _SUMMARY_RE.match(line))
    ]
    entries = []
    for title, body in _blocks(sections.get("ERRORS", []) + sections.get("FAILURES", [])):
        name = re.sub(r"^ERROR (at \w+ of|collecting) ", "", title)
        # Pairing in order keeps same-named tests in different files apart.
        match = next((entry for entry in summary if _node_title(entry[0]) == name), None)
        if match:
            summary.remove(match)
        label = re.match(r"ERROR (?:at (\w+) of|(collecting))", title)
        suffix = f" ({label[1] or 'collection'} error)" if label else ""
        entries.append("\n".join([f"✗ {match[0] if match else name}{suffix}", *_describe(body, root)]))
    for node, message in summary:
        entries.append(f"✗ {node}" + (f"\n    {message}" if message else ""))
    return entries


def _node_title(node):
    # pytest titles tests/a.py::TestX::test_y as TestX.test_y, and collection errors by path.
    return node.split("::", 1)[-1].replace("::", ".")


def _blocks(lines):
    blocks = []
    for line in lines:
        m = _BLOCK_RE.match(line)
        if m and not _FRAME_DIVIDER_RE.match(line):
            blocks.append((m[1], []))
        elif blocks:
            blocks[-1][1].append(line)
    return blocks


def _describe(body, root):
    """The last frames in the user's own code, the error lines, and the end of anything the test printed."""
    body, captured = _split_captured(body)
    frames, errors = _parse_traceback(body)
    if not errors:
        frames, errors = _parse_native_traceback(body, root)
    if not errors:
        # An unfamiliar format. Showing its end beats showing nothing.
        return [*(trim("    " + line) for line in body if line.strip())][-FALLBACK_LINES:] + captured
    # pytest indents errors to match the code above them; only the relative indent means anything.
    margin = min(len(line) - len(line.lstrip()) for line in errors)
    errors = [trim("    " + line[margin:]) for line in errors]
    return [*frames[-MY_FRAMES:], *cap_error_lines(errors), *captured]


def _split_captured(body):
    """Separate the traceback from what the test printed. A print is often the clue, so keep its end."""
    starts = [i for i, line in enumerate(body) if _CAPTURED_RE.match(line)]
    rendered = []
    for start, end in zip(starts, [*starts[1:], len(body)]):
        printed = [line for line in body[start + 1 : end] if line.strip()]
        rendered.append(f"    {_CAPTURED_RE.match(body[start])[1]}:")
        rendered.extend(trim("      " + line) for line in last_lines(printed))
    return (body[: starts[0]] if starts else body), rendered


def _parse_traceback(body):
    frames = []
    errors = []
    pointed_at = None
    for i, line in enumerate(body):
        if line.startswith(">"):
            pointed_at = line[1:].strip()
        elif line == "E" or line.startswith("E "):
            if line[1:].strip():
                errors.append(line[1:])
        elif m := _FRAME_RE.match(line):
            # Long tracebacks mark the code with ">" before the location; short ones print it after.
            following = body[i + 1] if i + 1 < len(body) else ""
            code = pointed_at or (following.strip() if following.startswith("    ") else "")
            pointed_at = None
            if not _NOT_MY_CODE_RE.search(m[1]):
                frames.append(trim(f"    {m[1]}:{m[2]}  {code}".rstrip()))
    return frames, errors


def _parse_native_traceback(body, root):
    """--tb=native prints Python's own format: File "x", line N, in f, then the code, ending with the error."""
    frames = []
    last = None
    for i, line in enumerate(body):
        if m := _NATIVE_FRAME_RE.match(line):
            last = i
            if not _NOT_MY_CODE_RE.search(m[1]):
                path = m[1].removeprefix(f"{root}/") if root else m[1]
                code = body[i + 1].strip() if i + 1 < len(body) else ""
                frames.append(trim(f"    {path}:{m[2]}  {code}".rstrip()))
    if last is None:
        return [], []
    after = body[last + 1 :]
    # Frames without source (compiled or frozen code) go straight to the error, which isn't indented.
    after = after[1:] if after and after[0].startswith("    ") else after
    return frames, [line for line in after if line.strip() and not _CARETS_RE.match(line)]


def _warnings(section, root, totals):
    total = re.search(r"(\d+) warnings?\b", totals)
    if not total:
        return ""
    counts = Counter()
    nodes = 0
    for line in section:
        if m := _WARNING_RE.match(line):
            path = m[1].removeprefix(f"{root}/") if root else m[1]
            counts[m[2], path] += nodes or 1
            nodes = 0
        elif line and not line[0].isspace() and (node := _WARNED_NODE_RE.match(line)):
            nodes += int(node[1] or 1)
    detail = ", ".join(f"{kind} ×{n} from {path}" for (kind, path), n in counts.most_common(3))
    if len(counts) > 3:
        detail += ", …"
    return f"⚠ {total[0]}" + (f" ({detail})" if detail else "") + " — hidden"
