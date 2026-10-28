"""Doc hygiene: backticked repo paths exist, and acceptance IDs are unique per phase file."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PATH_RE = re.compile(r"`([^`\s]+\.(?:md|py|json|yml|toml|csv))`")
SKIP_RE = re.compile(r"[<{*]|XX")
SKIP_PREFIXES = (
    "sessions/",
    "runs/",
    "$S/",
    "%",
    "C:/",
    "rfdetr/",
    "trackers/",
    "supervision/",
)

# Paths that are referenced but genuinely absent, pending an owner decision.
ALLOWLIST = {
    ".scratch/pointr-vision/field-test-2026-10-22.md": "owner is copying it from another PC",
    "docs/pipeline.md": "AI Production Suite file, not vendored; owner decision pending",
    "docs/research/sources.md": "AI Production Suite file, not vendored; owner decision pending",
    ".suite/assess/assessment.md": "AI Production Suite file, not vendored; owner decision pending",
}

ID_RE = re.compile(r"^\**`?((?:[A-Z][A-Za-z0-9]*-)*[A-Z]\d+[a-z]?)`?\**$")


def _doc_files() -> list[Path]:
    files = list(ROOT.glob("docs/**/*.md")) + list(ROOT.glob(".scratch/**/*.md"))
    files += [ROOT / n for n in ("DECISIONS.md", "CLAUDE.md", "AGENTS.md", "GLOSSARY.md")]
    return sorted(f for f in files if f.is_file())


def test_backticked_repo_paths_in_docs_exist():
    missing = []
    for doc in _doc_files():
        text = doc.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), 1):
            for path in PATH_RE.findall(line):
                if "/" not in path or SKIP_RE.search(path) or path.startswith(SKIP_PREFIXES):
                    continue
                if path in ALLOWLIST or (ROOT / path).exists():
                    continue
                missing.append(f"{doc.relative_to(ROOT).as_posix()}:{line_no}: {path}")
    assert not missing, "doc paths that do not exist in the repo:\n" + "\n".join(missing)


def test_acceptance_ids_are_unique_within_each_phase_file():
    duplicates = []
    for phase in sorted(ROOT.glob("docs/phases/PHASE_*.md")):
        if phase.name.endswith("_REPORT.md"):
            continue  # reports restate the IDs per test run, by design
        ids = []
        in_acceptance = False
        for line in phase.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                # The Traceability table restates every ID by design; only count Acceptance.
                in_acceptance = "acceptance" in line.lower()
            if not in_acceptance or not line.lstrip().startswith("|"):
                continue
            first = line.strip().strip("|").split("|")[0].strip()
            match = ID_RE.match(first)
            if match:
                ids.append(match.group(1))
        for acceptance_id, count in Counter(ids).items():
            if count > 1:
                duplicates.append(f"{phase.name}: {acceptance_id} appears {count} times")
    assert not duplicates, "duplicate acceptance IDs:\n" + "\n".join(duplicates)
