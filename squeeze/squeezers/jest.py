"""jest and vitest: the totals, each failing test's location and assertion, no passing tests or their console noise."""
import re
from pathlib import Path

from ..clean import cap_error_lines, last_lines, trim

NAMES = {"jest", "vitest"}
MY_FRAMES = 2

_NOT_MY_CODE_RE = re.compile(r"node_modules|^node:|^internal/")
_FAILED_RE = re.compile(r"(\d+) failed\b")

_JEST_TOTALS_RE = re.compile(r"^Tests:\s+(.*)$", re.MULTILINE)
_JEST_SUITES_RE = re.compile(r"^Test Suites:\s+(.*)$", re.MULTILINE)
_JEST_TIME_RE = re.compile(r"^Time:\s+([^,\n]+)", re.MULTILINE)
_JEST_FILE_RE = re.compile(r"^(?:FAIL|PASS) (.+)$")
_JEST_BLOCK_RE = re.compile(r"^  ● (.*)$")
_JEST_VERBOSE_CONSOLE_RE = re.compile(r"^  console\.\w+$")
_JEST_CONSOLE_RE = re.compile(r"^\s*console\.\w+$")
_JEST_BANNER_RE = re.compile(r"^Jest: .*$", re.MULTILINE)
_JEST_CODE_RE = re.compile(r"^\s+(>)?\s*\d* \|")
_JEST_STACK_RE = re.compile(r"^\s+at (?:.*? \()?([^\s()]+):(\d+):\d+\)?$")

_VITEST_TOTALS_RE = re.compile(r"^\s*Tests\s{2,}(.*)$", re.MULTILINE)
_VITEST_FILES_RE = re.compile(r"^\s*Test Files\s{2,}(.*)$", re.MULTILINE)
_VITEST_TIME_RE = re.compile(r"^\s*Duration\s{2,}(\S+)", re.MULTILINE)
_VITEST_ERRORS_RE = re.compile(r"^\s*Errors\s{2,}\d+", re.MULTILINE)
_VITEST_FAIL_RE = re.compile(r"^ FAIL  (.+)$")
_VITEST_END_RE = re.compile(r"^⎯+\[\d+/\d+\]⎯+$")
_VITEST_FRAME_RE = re.compile(r"^ ❯ (?:\S+ )?(\S+?):(\d+):\d+$")
_VITEST_CODE_RE = re.compile(r"^\s*(\d*)\|(.*)$")
_VITEST_SUITE_RE = re.compile(r"^(.*?) \[ .* \]$")
_VITEST_CONSOLE_RE = re.compile(r"^(?:stdout|stderr) \| (\S+)")


def matches(command, output):
    return any(Path(arg).name in NAMES for arg in command) or bool(
        (_JEST_SUITES_RE.search(output) and _JEST_TOTALS_RE.search(output)) or _VITEST_FILES_RE.search(output)
    )


def squeeze(output, exit_code):
    if _JEST_SUITES_RE.search(output) and (totals := _JEST_TOTALS_RE.search(output)):
        return _jest(output, totals[1], exit_code)
    if _VITEST_FILES_RE.search(output) and (totals := _VITEST_TOTALS_RE.search(output)):
        return _vitest(output, totals[1], exit_code)
    raise ValueError("no test totals found, so this run may have crashed")


def _jest(output, totals, exit_code):
    suites = _JEST_SUITES_RE.search(output)[1]
    time = _JEST_TIME_RE.search(output)
    failures = []
    failing_files = set()
    failed_tests = 0
    path = None
    block = None
    for line in output.split("\n"):
        # Runs with many suites print every failure a second time under this heading.
        if line.startswith("Summary of all failing tests") or line.startswith("Test Suites:"):
            break
        file_match = _JEST_FILE_RE.match(line)
        block_match = _JEST_BLOCK_RE.match(line)
        if file_match or block_match or _JEST_VERBOSE_CONSOLE_RE.match(line):
            block = None
        if file_match:
            path = file_match[1]
        elif block_match and block_match[1] != "Console":
            block = []
            suite_failed = block_match[1] == "Test suite failed to run"
            failed_tests += not suite_failed
            failing_files.add(path)
            name = f"{path} (suite failed to run)" if suite_failed else f"{path} › {block_match[1]}"
            failures.append((name, block))
        elif block is not None:
            block.append(line)

    return _report(
        totals,
        suites if _FAILED_RE.search(suites) else None,
        time[1] if time else None,
        [([name], *_describe_jest(body)) for name, body in failures],
        failed_tests,
        _JEST_BANNER_RE.findall(output),
        _jest_console(output, failing_files),
        exit_code,
    )


def _jest_console(output, failing_files):
    """Console output from files with failures. A log's stack line says which file it came from."""
    found = {}
    message = None
    for line in output.split("\n"):
        if line.startswith("Summary of all failing tests") or line.startswith("Test Suites:"):
            break
        if _JEST_CONSOLE_RE.match(line):
            message = []
        elif message is not None:
            if m := _JEST_STACK_RE.match(line):
                if m[1] in failing_files:
                    found.setdefault(m[1], []).extend(message)
                message = None
            elif line.strip():
                message.append(line.strip())
    return found


def _describe_jest(body):
    message = []
    frames = []
    code = ""
    in_message = True
    for line in body:
        if m := _JEST_CODE_RE.match(line):
            in_message = False
            if m[1]:
                code = line.split("|", 1)[1].strip()
        elif m := _JEST_STACK_RE.match(line):
            in_message = False
            if not _NOT_MY_CODE_RE.search(m[1]):
                frames.append(f"{m[1]}:{m[2]}")
        elif in_message and line.strip():
            message.append(line)
    return _locations(frames, code), message


def _vitest(output, totals, exit_code):
    if _VITEST_ERRORS_RE.search(output):
        raise ValueError("vitest reported unhandled errors, which sit outside the failure list")
    time = _VITEST_TIME_RE.search(output)
    entries = []
    current = None
    for line in output.split("\n"):
        if m := _VITEST_FAIL_RE.match(line):
            # vitest groups tests with an identical error: several FAIL lines, then one error.
            if current is None or current[1]:
                current = ([], [])
                entries.append(current)
            current[0].append(m[1])
        elif _VITEST_END_RE.match(line):
            current = None
        elif current is not None:
            current[1].append(line)

    failed_tests = sum(not _VITEST_SUITE_RE.match(name) for names, _ in entries for name in names)
    files = _VITEST_FILES_RE.search(output)[1]
    return _report(
        _normalize_vitest(totals),
        _normalize_vitest(files) if _FAILED_RE.search(files) else None,
        time[1] if time else None,
        [([_vitest_name(name) for name in names], *_describe_vitest(body)) for names, body in entries],
        failed_tests,
        [],
        _vitest_console(output, entries),
        exit_code,
    )


def _vitest_console(output, entries):
    """Console output from files with failures."""
    failing_files = {re.sub(r" (?:>|\[ ).*$", "", name) for names, _ in entries for name in names}
    found = {}
    target = None
    for line in output.split("\n"):
        if m := _VITEST_CONSOLE_RE.match(line):
            target = found.setdefault(m[1], []) if m[1] in failing_files else None
        elif not line.strip():
            target = None
        elif target is not None:
            target.append(line.strip())
    return found


def _normalize_vitest(totals):
    return re.sub(r" \((\d+)\)$", r", \1 total", totals.replace(" | ", ", "))


def _vitest_name(name):
    suite = _VITEST_SUITE_RE.match(name)
    return f"{suite[1]} (suite failed to run)" if suite else name.replace(" > ", " › ")


def _describe_vitest(body):
    message = []
    frames = []
    code = ""
    target = None
    for line in body:
        if m := _VITEST_FRAME_RE.match(line):
            if not _NOT_MY_CODE_RE.search(m[1]):
                frames.append(f"{m[1]}:{m[2]}")
                target = target or m[2]
        elif m := _VITEST_CODE_RE.match(line):
            if m[1] and m[1] == target and not code:
                code = m[2].strip()
        elif not frames and line.strip():
            message.append(line)
    return _locations(frames, code), message


def _locations(frames, code):
    """Outermost first, like the pytest squeezer. Stacks list the innermost frame first, which is the code shown."""
    kept = frames[:MY_FRAMES]
    return [
        trim(f"    {frame}  {code}".rstrip() if i == 0 else f"    {frame}") for i, frame in reversed(list(enumerate(kept)))
    ]


def _report(totals, failed_units, time, failures, failed_tests, banners, console, exit_code):
    # The runner's own count is the check on our parsing: never report fewer failures than it did.
    expected = _FAILED_RE.search(totals)
    if failed_tests != (int(expected[1]) if expected else 0):
        raise ValueError(f"parsed {failed_tests} failed tests, the runner reported {expected and expected[1]}")
    # A failing exit with no failed test has a cause we didn't parse, so it mustn't look like a pass.
    if exit_code != 0 and not failures and not banners:
        raise ValueError(f"exit {exit_code} with no failed tests")

    head = f"tests: {totals}" + (f" · suites: {failed_units}" if failed_units else "")
    if time:
        head += f" in {time}"
    if exit_code == 0 and not failures:
        head = f"✓ {head}"
    parts = ["\n".join([head, *banners])]
    for names, locations, message in failures:
        margin = min((len(line) - len(line.lstrip()) for line in message), default=0)
        errors = [trim("    " + line[margin:]) for line in message]
        parts.append("\n".join([*(f"✗ {name}" for name in names), *locations, *cap_error_lines(errors)]))
    if console:
        printed = ["console output from failing files:"]
        for path, lines in console.items():
            printed.append(f"  {path}")
            printed.extend(trim(f"    {line}") for line in last_lines(lines))
        parts.append("\n".join(printed))
    return "\n\n".join(parts)
