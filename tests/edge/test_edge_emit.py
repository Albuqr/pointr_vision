"""T10 (#72): the edge writes its status and error lines only through `child_protocol.emit`
and reads Studio's stop line only through `child_protocol.parse`.

The scan fails when a protocol prefix is a string literal in an edge module. The summary text
(`t0_wall=... failed_reads=N`) is still composed by its callers and sent as `Summary(detail)`.
"""

import ast
from pathlib import Path

import pytest

from services.edge import child_protocol as protocol
from services.edge import main as cli
from tests.edge.test_cli import run_cli

EDGE = Path(__file__).resolve().parents[2] / "services" / "edge"
PREFIXES = ("session: ", "device: ", "preview_port: ", "error: ", "stop ui")
# standalone command-line tools whose errors go to a person's terminal, not to a launcher
TERMINAL_TOOLS = {"launcher_impl.py", "reports/cli.py", "score.py"}


def test_no_edge_module_writes_a_protocol_line_by_hand():
    found = []
    for path in sorted(EDGE.rglob("*.py")):
        name = path.relative_to(EDGE).as_posix()
        if name == "child_protocol.py" or name in TERMINAL_TOOLS:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value.startswith(PREFIXES)
            ):
                found.append(f"{name}:{node.lineno} {node.value!r}")
    assert not found, "protocol prefixes outside child_protocol.py:\n" + "\n".join(found)


def test_the_scan_sees_a_prefix_in_a_literal():
    source = 'print(f"error: {x}")\nprint("device: cpu")\nsay(c, f"session: {d}")'
    hits = [
        n.value
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.Constant) and n.value.startswith(PREFIXES)
    ]
    assert sorted(hits) == ["device: cpu", "error: ", "session: "]


def test_a_link_conflict_is_a_config_conflict_start_failure(clips, tmp_path):
    result = run_cli(tmp_path / "out", "--source", str(clips["moving"]), "--link", "usb")
    assert result.returncode == cli.EXIT_OPEN_FAILED
    assert "error: config_conflict: --link usb contradicts a file source" in result.stderr
    kind, _, reason = result.stderr.strip().removeprefix("error: ").partition(": ")
    assert protocol.parse(f"error: {kind}: {reason}")[1] == protocol.StartFailed(kind, reason)


@pytest.mark.parametrize("line", ["stop ui\n", "stop\n"])
def test_stop_lines_are_read_by_the_protocol(line):
    from services.edge.run.stop import stop_source

    assert protocol.parse(line.strip())[1] == protocol.Stop(stop_source(line))
