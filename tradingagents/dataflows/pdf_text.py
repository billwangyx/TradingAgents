"""Extract text from a PDF that is already in memory or on disk.

HKEX and cninfo filings are PDFs. pypdf drops the Chinese text in those
files; PyMuPDF keeps the figures and the sentences around them. This module
does not OCR and does not download anything.
"""

from __future__ import annotations

from pathlib import Path


def extract_pdf_text(source: bytes | bytearray | Path | str) -> str:
    """Return the text of ``source``. Raises if the PDF cannot be read."""
    import pymupdf

    if isinstance(source, (bytes, bytearray)):
        document = pymupdf.open(stream=bytes(source), filetype="pdf")
    else:
        document = pymupdf.open(Path(source))
    try:
        parts = [(page.get_text() or "") for page in document]
    finally:
        document.close()
    return "\n".join(parts)
