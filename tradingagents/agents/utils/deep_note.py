"""Required prompt fragments for a deep single-stock research note.

The 2026-10-02 HHH and SHOP notes only held together when every deep equity
pass attempted a controlling-shareholder layer and a management-voice layer,
attributed both, and wrote an explicit Gaps list instead of inventing a
print. ``docs/deep-note-harness.md`` is the checklist; these strings are the
same rules, short enough to live in the analyst prompts.
"""

from tradingagents.agents.utils.deep_note_sources import IR_MIRROR_RULE, TRANSCRIPT_RULE

SHAREHOLDER_HEADING = "Controlling / major shareholder"
MANAGEMENT_HEADING = "Management / strategy voice"
GAPS_HEADING = "Gaps"

SOURCE_ORDER = (
    "SEC EDGAR (and SEDAR+ when the issuer reports in Canada) → "
    "company or GlobeNewswire press → controller investor materials → "
    "earnings transcripts (company IR, then Quartr or stockanalysis, then "
    "Motley Fool flagged secondary) → Yahoo quotes"
)

FRED_KEY_SERIES_RULE = (
    "Call get_fred_key_series once for the current date. It attempts fed funds, "
    "the 2-year and 10-year Treasury yields, the yield curve, CPI, core PCE, and "
    "unemployment. Copy every line that starts with 'Gap:' into the Gaps section. "
    "An empty FRED response or a DATA_UNAVAILABLE macro result is a Gap, not a "
    "skipped section. Do not invent CPI, rates, or a curve."
)


def stock_layer_instruction() -> str:
    """Required sections for a single-stock fundamentals pass."""
    return f"""

Deep-note layers (required on every single-stock run; research only, no orders):
Attempt both layers below. Attribute every ownership percent, voting cap, fee, and quote to text that was actually retrieved. Never invent a filing, letter, quote, headline, NAV, YTD, or price. This framework's bound tools (Yahoo Finance, Alpha Vantage, FRED, insider transactions) do not fetch EDGAR, SEDAR+, GlobeNewswire, or IR CDNs. If the primary document is not in tool output, write that under {GAPS_HEADING}. Do not fill it from memory.

- {SHAREHOLDER_HEADING}: ownership %, voting caps, fee arrangements, and strategy letters or presentations from the controller. Cite 13D/13F only when that filing was retrieved. Name the source.
- {MANAGEMENT_HEADING}: CEO, President, and CFO quotes from earnings calls and IR press releases, with speaker, date, and document. {TRANSCRIPT_RULE} Distill this layer so it can be saved as a local `management-*.md` (for example `management-strategy.md` or `management-and-pershing.md`) with the same attribution.
- {IR_MIRROR_RULE}
- Source order when a primary text is actually in hand: {SOURCE_ORDER}.
- {GAPS_HEADING}: put this section near the top of the note, immediately after the snapshot and before the long exhibits. {SHAREHOLDER_HEADING} and {MANAGEMENT_HEADING} come next, ahead of peers and technicals. Record IR CDN/Akamai denials with the blocked URL, empty GCS or IR decks, missing FRED series, empty news, blank YTD, a dividend yield that came back as an em dash, and no sell-side NAV. Fallbacks, then still a Gap if the fallback is empty: Akamai-blocked IR → SEC EX-99, the exchange filing, or GlobeNewswire, and do not hammer the CDN; empty GCS decks → SEC exhibits; missing FRED → Gap; ticker news tries Yahoo, then Alpha Vantage, then Eastmoney/akshare for CN/HK names, and a still-empty result is NEWS_EMPTY → Gap. Do not invent a headline or a print to cover a block.
"""


def news_layer_instruction(asset_type: str = "stock") -> str:
    """News-analyst slice: attempt both layers, and Gap empty news or FRED."""
    if asset_type != "stock":
        return non_stock_gap_instruction()
    return f"""

Deep-note layers (required on a stock news pass; research only, no orders):
- {MANAGEMENT_HEADING}: if tool output contains CEO, President, or CFO remarks from an earnings call or an IR/GlobeNewswire release, quote them with speaker, date, and source. {TRANSCRIPT_RULE} If none were retrieved, say so under {GAPS_HEADING}. Do not invent quotes.
- {SHAREHOLDER_HEADING}: if tool output contains ownership, voting caps, fees, a 13D/13F, or a controller letter, attribute it. Insider transactions are not a 13D and are not an earnings-call quote. If the controller pack was not retrieved, {GAPS_HEADING}. Do not invent a controller.
- Call get_insider_transactions once for the ticker. Report only rows the tool returned.
- {FRED_KEY_SERIES_RULE}
- {IR_MIRROR_RULE}
- {GAPS_HEADING}: put Gaps near the top of the note, after the snapshot. {SHAREHOLDER_HEADING} and {MANAGEMENT_HEADING} are the next priorities. Empty get_news (including a NEWS_EMPTY line after Yahoo, Alpha Vantage, and Eastmoney/akshare) or empty get_global_news → Gap; do not invent headlines. FRED missing, unconfigured, or empty → Gap; do not invent macro prints. Akamai-blocked IR → record Gap plus the blocked URL, then use SEC EX-99, the exchange filing, or GlobeNewswire if that text was retrieved. Do not retry the CDN. Empty GCS/IR decks → SEC exhibits if retrieved, otherwise Gap plus the deck URL. Source order: {SOURCE_ORDER}.
"""


def non_stock_gap_instruction() -> str:
    """Crypto and other non-stocks: do not invent an equity controller pack."""
    return (
        f" Deep-note controller and management packs apply to single stocks. "
        f"Do not invent a shareholder, 13D, or earnings-call quote for this asset. "
        f"If news, FRED, or a market print is empty, list it under {GAPS_HEADING}. "
        f"Never invent headlines or prices. {FRED_KEY_SERIES_RULE}"
    )


def market_gap_instruction() -> str:
    """Market analyst: blank prints stay blank."""
    return (
        f" The verified snapshot includes Calendar YTD simple return and Dividend yield. "
        f"Calendar YTD is Yahoo info ytdReturn when that field is present. If ytdReturn "
        f"is empty or the quote lookup returns 401, the snapshot uses the first available "
        f"close of the calendar year versus the latest close. Gap only when that price "
        f"history is missing. If YTD, dividend yield, or any other exact print is an em "
        f"dash or otherwise absent from tool output, copy that line under {GAPS_HEADING} "
        f"with its reason. Do not invent the figure, a headline, or a reconciled number."
    )


def news_empty_debate_note(state: dict | None) -> str:
    """Short bull/bear/manager addendum when ticker news vendors returned nothing."""
    if not state or not state.get("news_empty"):
        return ""
    return (
        " NEWS_EMPTY is set: ticker news vendors returned no headlines. "
        "Keep this argument to one short paragraph. Do not invent headlines "
        "and do not extend the debate to fill the gap."
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
