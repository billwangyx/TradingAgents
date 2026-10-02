# Deep single-stock research harness

Checklist for a deep equity note (the pattern that held up on the 2026-10-02 HHH and SHOP passes). The TradingAgents graph still runs analysts, a bull/bear debate, and a simulated rating. The **note** those agents feed is research: attributed primary evidence, an explicit Gaps list, and no invented prints. It does not place orders.

Prompt text for the same rules lives in `tradingagents/agents/utils/deep_note.py` and is appended by the fundamentals analyst, news analyst, market analyst, bull and bear researchers, and research manager.

Do not commit ticker research dumps (HTML notes, full `management-*.md` packs, or `SOURCES.md` for a name) into this repo. Keep those next to the run. A skeleton is at the bottom of this file so a later pass has a shape to fill.

## Checklist

Run the steps in this order. Skip a step only by writing why under Gaps.

1. **Market data.** OHLCV and the verified market snapshot (`get_stock_data`, `get_verified_market_snapshot`, indicators). Any exact level, YTD, or percent move must come from tool output with a date. A blank YTD or missing bar is a Gap, not a guess.
2. **Filings.** Statements from the bound fundamentals tools. When a primary filing was actually retrieved, prefer SEC EDGAR, and SEDAR+ for a Canadian issuer. This repo's vendors do not download EDGAR or SEDAR+ themselves.
3. **Shareholder / controller pack.** Required. Ownership %, voting caps, fee arrangements, and strategy letters or presentations from the controller (Pershing's letters for HHH are the shape, not a default fact). 13D/13F only when that filing was retrieved. Attribute the source. Insider Form 4 rows are not a substitute.
4. **Management commentary pack.** Required. CEO, President, and CFO quotes from earnings calls and IR press releases. Distill them into a local `management-*.md` (`management-strategy.md`, or `management-and-pershing.md` when the controller is part of the voice) with speaker, date, and document. Flag third-party transcripts as secondary.
5. **Peers.** Only names and figures that appear in retrieved sources. No borrowed multiples.
6. **TA graph.** Indicators chosen and computed by the market analyst. No hand-drawn levels that the series does not show.
7. **Note + Gaps + residue.** Equity-research HTML (or the markdown report tree under `1_analysts/`) plus a Gaps section plus a short residue list. Residue is blocked URLs and excerpts that were not promoted into the note, kept so a later pass can retry. Residue is not a print.

## Source order

Use the first source that was actually retrieved. Do not skip ahead by inventing what a higher source "would have said."

1. SEC EDGAR, and SEDAR+ when the issuer reports in Canada.
2. Company press or GlobeNewswire.
3. Controller investor materials (strategy letter, presentation, 13D exhibit).
4. Third-party transcripts (Motley Fool, Quartr), marked **secondary**.
5. Yahoo quotes (price and profile fields only; not a substitute for a filing or a call).

## What the agents can and cannot fetch

Bound tools are Yahoo Finance, Alpha Vantage, FRED (`get_macro_indicators`), prediction markets, and (on the news analyst) `get_insider_transactions`. Optional Chinese-market and Xueqiu paths are separate and do not fill a US controller pack.

Those tools do not fetch EDGAR, SEDAR+, GlobeNewswire, or IR CDNs. A deep run still **opens** the shareholder and management sections. Anything not in tool output goes to Gaps. An operator who pastes a primary document into the run follows the source order above. The model does not backfill from memory.

## Known egress blocks and fallbacks

| Block | What to do | If the fallback is also empty |
| --- | --- | --- |
| IR host denies via Akamai (CDN 403 / edge block) | Use the same exhibit from SEC EDGAR (often EX-99) or the GlobeNewswire copy | Gap. Do not retype the release from memory. |
| Shopify (or similar) GCS investor decks return empty | Use the SEC exhibit that carried the deck | Gap. Do not describe slides that were not retrieved. |
| FRED series missing, key unset, or vendor error | — | Gap. Do not invent CPI, rates, or a curve. |
| Yahoo / vendor / TradingAgents news empty | — | Gap. Do not invent headlines. |
| YTD or other market print blank | — | Gap. Do not invent the percent. |
| No sell-side NAV in sources | — | Gap. Do not compute a NAV and present it as street research. |

## Gaps section

Every deep note ends with **Gaps**. Each bullet names the item, the source that failed, and the fallback tried. Empty news, a missing FRED series, a blank YTD, a blocked IR URL, an empty deck, and "no sell-side NAV" are all Gaps. A Gap is not filled with a plausible number.

`SOURCES.md` next to the run lists what was retrieved and repeats the Gaps list. The in-repo report tree (`fundamentals.md`, `news.md`, `market.md`) carries the same headings when the agents write the note.

## Research only

The note does not place orders and does not invent a fill. The graph's trader and portfolio manager may still emit a simulated rating. That rating has to treat Gaps as unknown. A missing price is not an entry.

## Skeleton (template only)

Fill from retrieved sources. Delete nothing by guessing. This skeleton is not a research dump and must not be copied into a note as if the braces were facts.

```markdown
# {TICKER} deep note — {as-of date}

## Market data
- Last / range / YTD: {from verified snapshot, or Gap}

## Filings
- {form, date, url}

## Controlling / major shareholder
- {holder, role}: {ownership % or "not in source"}; voting cap {or Gap}; fees {or Gap}
- Controller material: {letter or presentation, date, url} | Gap

## Management / strategy voice
- {Speaker, role}, {date}, {document, url}: "{quote}" — primary | secondary

## Peers
- {only retrieved figures}

## TA
- {indicator, date, value from tools}

## Gaps
- {item} — {source that failed} — fallback {tried or "none"} — still open

## Residue
- {blocked url or unused excerpt, not promoted into the note}
```

Local files beside the run, not committed:

- `management-strategy.md` or `management-and-pershing.md` — the distilled voice layer with attribution
- `SOURCES.md` — retrieved sources and the same Gaps list
