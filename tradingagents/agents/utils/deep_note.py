"""Required prompt fragments for a deep single-stock research note.

The 2026-10-02 HHH and SHOP notes only held together when every deep equity
pass attempted a controlling-shareholder layer and a management-voice layer,
attributed both, and wrote an explicit Gaps list instead of inventing a
print. ``docs/deep-note-harness.md`` is the checklist; these strings are the
same rules, short enough to live in the analyst prompts.
"""

SHAREHOLDER_HEADING = "Controlling / major shareholder"
MANAGEMENT_HEADING = "Management / strategy voice"
GAPS_HEADING = "Gaps"

SOURCE_ORDER = (
    "SEC EDGAR (and SEDAR+ when the issuer reports in Canada) → "
    "company or GlobeNewswire press → controller investor materials → "
    "third-party transcripts (Motley Fool, Quartr), flagged secondary → "
    "Yahoo quotes"
)


def stock_layer_instruction() -> str:
    """Required sections for a single-stock fundamentals pass."""
    return f"""

Deep-note layers (required on every single-stock run; research only, no orders):
Attempt both layers below. Attribute every ownership percent, voting cap, fee, and quote to text that was actually retrieved. Never invent a filing, letter, quote, headline, NAV, YTD, or price. This framework's bound tools (Yahoo Finance, Alpha Vantage, FRED, insider transactions) do not fetch EDGAR, SEDAR+, GlobeNewswire, or IR CDNs. If the primary document is not in tool output, write that under {GAPS_HEADING}. Do not fill it from memory.

- {SHAREHOLDER_HEADING}: ownership %, voting caps, fee arrangements, and strategy letters or presentations from the controller. Cite 13D/13F only when that filing was retrieved. Name the source.
- {MANAGEMENT_HEADING}: CEO, President, and CFO quotes from earnings calls and IR press releases, with speaker, date, and document. Flag Motley Fool or Quartr transcripts as secondary. Distill this layer so it can be saved as a local `management-*.md` (for example `management-strategy.md` or `management-and-pershing.md`) with the same attribution.
- Source order when a primary text is actually in hand: {SOURCE_ORDER}.
- {GAPS_HEADING}: end with this section. Record IR CDN/Akamai denials, empty GCS or IR decks, missing FRED series, empty news, blank YTD, and no sell-side NAV. Fallbacks, then still a Gap if the fallback is empty: Akamai-blocked IR → SEC EX-99 or GlobeNewswire; empty GCS decks → SEC exhibits; missing FRED → Gap; empty Yahoo or vendor news → Gap. Do not invent a headline or a print to cover a block.
"""


def news_layer_instruction(asset_type: str = "stock") -> str:
    """News-analyst slice: attempt both layers, and Gap empty news or FRED."""
    if asset_type != "stock":
        return non_stock_gap_instruction()
    return f"""

Deep-note layers (required on a stock news pass; research only, no orders):
- {MANAGEMENT_HEADING}: if tool output contains CEO, President, or CFO remarks from an earnings call or an IR/GlobeNewswire release, quote them with speaker, date, and source. Flag Motley Fool or Quartr as secondary. If none were retrieved, say so under {GAPS_HEADING}. Do not invent quotes.
- {SHAREHOLDER_HEADING}: if tool output contains ownership, voting caps, fees, a 13D/13F, or a controller letter, attribute it. Insider transactions are not a 13D and are not an earnings-call quote. If the controller pack was not retrieved, {GAPS_HEADING}. Do not invent a controller.
- Call get_insider_transactions once for the ticker. Report only rows the tool returned.
- {GAPS_HEADING}: empty get_news or get_global_news → Gap; do not invent headlines. FRED missing, unconfigured, or empty → Gap; do not invent macro prints. Akamai-blocked IR → use SEC EX-99 or GlobeNewswire if that text was retrieved, otherwise Gap. Empty GCS/IR decks → SEC exhibits if retrieved, otherwise Gap. Source order: {SOURCE_ORDER}.
"""


def non_stock_gap_instruction() -> str:
    """Crypto and other non-stocks: do not invent an equity controller pack."""
    return (
        f" Deep-note controller and management packs apply to single stocks. "
        f"Do not invent a shareholder, 13D, or earnings-call quote for this asset. "
        f"If news, FRED, or a market print is empty, list it under {GAPS_HEADING}. "
        f"Never invent headlines or prices."
    )


def market_gap_instruction() -> str:
    """Market analyst: blank prints stay blank."""
    return (
        f" If YTD or any other exact print is absent from tool output, list it under "
        f"{GAPS_HEADING}. Do not invent the figure, a headline, or a reconciled number."
    )


def downstream_instruction() -> str:
    """Bull, bear, and research manager must use the layers or the Gaps."""
    return (
        f" Weigh any {SHAREHOLDER_HEADING} and {MANAGEMENT_HEADING} sections in the "
        f"analyst reports, including attributed quotes. Items listed under {GAPS_HEADING} "
        f"(blocked IR, empty filings, missing FRED, empty news, blank YTD, no sell-side NAV) "
        f"are unknown. Do not invent ownership, quotes, headlines, or prints to fill a Gap. "
        f"This note is research. Do not turn a missing print into an order."
    )
