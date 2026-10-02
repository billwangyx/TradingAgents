"""Local helpers for deep-note source policy.

These functions record Gaps and save a transcript that was already retrieved.
They do not request IR CDNs, Akamai hosts, or GCS decks.
"""

from __future__ import annotations

from pathlib import Path

IR_MIRROR_RULE = (
    "IR mirror policy: prefer SEC EX-99, exchange filings, and GlobeNewswire. "
    "On an Akamai or GCS block, record a Gap that includes the blocked URL and "
    "use the SEC mirror. Do not retry or hammer the CDN."
)

TRANSCRIPT_RULE = (
    "Earnings transcript order: company IR → Quartr or stockanalysis → "
    "Motley Fool (secondary). Save retrieved transcripts under transcripts/. "
    "If the only copy is secondary, write a Gap; do not treat Motley Fool as "
    "the company transcript."
)

_CDN_MARKERS = (
    "akamai",
    "edgesuite",
    "access denied",
    "gcs",
    "storage.googleapis.com",
    "403",
)

_SECONDARY_TRANSCRIPT_MARKERS = ("motley fool", "motleyfool", "fool.com")


def looks_like_cdn_block(detail: str) -> bool:
    """True when an error string looks like an Akamai or GCS denial."""
    text = (detail or "").lower()
    return any(marker in text for marker in _CDN_MARKERS)


def ir_cdn_gap(url: str, reason: str) -> str:
    """Gap line for a blocked IR URL. Does not fetch or retry the host."""
    recorded = (url or "").strip() or "(no URL recorded)"
    why = (reason or "Akamai/GCS block").strip()
    return (
        f"Gap: IR CDN blocked — {why} — {recorded}. "
        "Do not retry or hammer the CDN. Prefer the SEC EX-99 mirror, "
        "the exchange filing, or GlobeNewswire."
    )


def _is_secondary_transcript(source: str) -> bool:
    key = source.strip().lower()
    return any(marker in key for marker in _SECONDARY_TRANSCRIPT_MARKERS)


def assess_transcript_sources(sources: list[str] | tuple[str, ...]) -> str:
    """Gap when no transcript was retrieved, or the only copy is secondary."""
    labels = [source.strip() for source in sources if source and source.strip()]
    order = "company IR → Quartr or stockanalysis → Motley Fool (secondary)"
    if not labels:
        return (
            "Gap: no earnings transcript retrieved. "
            f"Source order: {order}. Save any retrieved text under transcripts/."
        )
    if all(_is_secondary_transcript(source) for source in labels):
        joined = ", ".join(labels)
        return (
            f"Gap: earnings transcript is only a secondary source ({joined}). "
            f"Prefer {order}. Quote Motley Fool only with that secondary flag, "
            "and still save the file under transcripts/."
        )
    return (
        "Transcript sources include a company IR, Quartr, or stockanalysis copy. "
        "Save each retrieved file under transcripts/ and attribute every quote."
    )


def _slug(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    parts = [part for part in cleaned.split("-") if part]
    return "-".join(parts) or "source"


def transcript_destination(ticker: str, call_date: str, source: str) -> str:
    """Relative path for a retrieved transcript. Does not create the file."""
    return f"transcripts/{_slug(ticker)}/{call_date.strip()}-{_slug(source)}.md"


def save_retrieved_transcript(
    root: Path | str,
    ticker: str,
    call_date: str,
    source: str,
    text: str,
) -> Path:
    """Write an already-retrieved transcript under ``transcripts/``.

    Empty text is refused so a Gap is not replaced by a blank file.
    """
    body = (text or "").strip()
    if not body:
        raise ValueError("Gap: refusing to save an empty transcript")
    relative = transcript_destination(ticker, call_date, source)
    path = Path(root) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body + "\n", encoding="utf-8")
    return path
