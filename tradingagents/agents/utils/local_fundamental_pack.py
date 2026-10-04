"""Compress financial-report text already on disk into a short fundamental pack.

deep-note passes the pack to the research manager. This module only reads
``.txt`` and ``.md`` files that are already in the caller-supplied directory
(including ``SOURCES.md``). It does not parse PDFs, run OCR, or download
anything, and it does not invent figures.
"""

from __future__ import annotations

import re
from pathlib import Path

TEXT_SUFFIXES = frozenset({".txt", ".md"})

# A caller-supplied directory with no financial text. Not fundamental material.
EMPTY_DIR_GAP = (
    "Gap: no .txt or .md financial text in the local research directory. "
    "PDFs were not parsed. Nothing was downloaded. Do not invent figures."
)

_MAX_READ_CHARS = 2_000_000
_SHORT_FILE_CHARS = 1_800
_SOURCES_CAP = 2_000
_MAX_LINES = 40
_MAX_LINE_CHARS = 400
_MAX_PACK_CHARS = 6_000

# Lines worth keeping from a long filing. Quoted as written; nothing is computed.
_FINANCIAL_LINE = re.compile(
    r"(?i)("
    r"revenue|turnover|net profit|operating profit|gross profit|"
    r"profit for the period|profit|earnings|\beps\b|\bebitda?\b|"
    r"margin|cash flow|comprehensive income|dividend|"
    r"\brmb\b|hk\$|us\$|\busd\b|\bcny\b|"
    r"收入|营收|收益|利润|盈利|亏损|每股|现金流|营业|人民币|百万元|亿元|万元"
    r")"
)
_AMOUNT_LINE = re.compile(
    r"(?i)("
    r"\d{1,3}(?:,\d{3})+(?:\.\d+)?"
    r"|\d+\.\d+\s*(?:million|billion|百万元|亿元|万元|元)?"
    r")"
)
_HEADLINE = re.compile(
    r"(?i)(revenue|profit for the period|net profit|operating profit|"
    r"营业收入|期内利润|净利润|营业利润)"
)


def build_local_fundamental_pack(directory: Path | str) -> str:
    """Return a short pack quoted from ``.txt`` / ``.md`` in ``directory``.

    Only the directory itself is scanned. Subdirectories are left alone.
    PDFs and every other suffix are ignored. Figures are copied from the
    files; none are calculated or filled in.
    """
    root = Path(directory)
    if not root.is_dir():
        raise NotADirectoryError(f"research directory is not a directory: {root}")

    files = sorted(
        (
            path
            for path in root.iterdir()
            if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES
        ),
        key=lambda path: (path.name.lower() != "sources.md", path.name.lower()),
    )
    if not files:
        return EMPTY_DIR_GAP

    parts = [
        "Local fundamental pack. Quoted from .txt/.md already in the directory. "
        "PDFs were not parsed. Nothing was downloaded. Do not invent figures.",
        f"Files: {', '.join(path.name for path in files)}",
    ]
    for path in files:
        parts.append(f"### {path.name}\n{_compress_file(path)}")

    pack = "\n\n".join(parts).strip()
    if len(pack) > _MAX_PACK_CHARS:
        pack = pack[:_MAX_PACK_CHARS].rstrip() + "\n\n[pack truncated to stay short]"
    return pack


def _compress_file(path: Path) -> str:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return (
            f"Gap: could not read {path.name} ({exc}). Do not invent figures."
        )
    note = ""
    if len(raw) > _MAX_READ_CHARS:
        raw = raw[:_MAX_READ_CHARS]
        note = "\n[file truncated before compression]"

    if path.name.lower() == "sources.md":
        body = _trim_lines(raw, _SOURCES_CAP)
        return body + note

    if len(raw) <= _SHORT_FILE_CHARS:
        return _trim_lines(raw, _SHORT_FILE_CHARS) + note

    kept = _financial_excerpt(raw)
    if not kept:
        head = _trim_lines(raw, 800)
        return (
            "Gap: no financial figure line matched in this file. "
            "Excerpt follows; do not invent figures.\n" + head + note
        )
    return kept + note


def _trim_lines(raw: str, cap: int) -> str:
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    body = "\n".join(lines)
    if len(body) <= cap:
        return body
    return body[:cap].rstrip() + "\n[excerpt truncated]"


def _financial_excerpt(raw: str) -> str:
    """Keep high-signal lines, in file order, until the pack is short."""
    raw_lines = raw.splitlines()
    chosen: list[int] = []
    seen: set[int] = set()
    for index, line in enumerate(raw_lines):
        stripped = line.strip()
        if not stripped:
            continue
        financial = bool(_FINANCIAL_LINE.search(stripped) or _HEADLINE.search(stripped))
        if _line_score(stripped) < 2 or not financial:
            previous = raw_lines[index - 1].strip() if index else ""
            amount_under_label = (
                not financial
                and _line_score(stripped) >= 2
                and bool(previous)
                and (_FINANCIAL_LINE.search(previous) or _HEADLINE.search(previous))
            )
            if not amount_under_label:
                continue
        previous_index = index - 1
        if previous_index >= 0 and previous_index not in seen:
            label = raw_lines[previous_index].strip()
            if (
                label
                and len(label) <= 120
                and (_FINANCIAL_LINE.search(label) or _HEADLINE.search(label))
            ):
                chosen.append(previous_index)
                seen.add(previous_index)
        if index not in seen:
            chosen.append(index)
            seen.add(index)
        if len(chosen) >= _MAX_LINES:
            break

    excerpts = []
    for index in chosen:
        excerpts.append(raw_lines[index].strip()[:_MAX_LINE_CHARS])
    return "\n".join(excerpts)


def _line_score(line: str) -> int:
    score = 0
    if _FINANCIAL_LINE.search(line):
        score += 1
    if _AMOUNT_LINE.search(line):
        score += 2
    if _HEADLINE.search(line):
        score += 2
    return score
