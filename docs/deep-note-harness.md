# Deep single-stock research harness

Checklist for a deep equity note (the pattern that held up on the 2026-10-02 HHH and SHOP passes). The TradingAgents graph still runs analysts, a bull/bear debate, and a simulated rating. The **note** those agents feed is research: attributed primary evidence, an explicit Gaps list, and no invented prints. It does not place orders.

Prompt text for the same rules lives in `tradingagents/agents/utils/deep_note.py` and is appended by the fundamentals analyst, news analyst, market analyst, bull and bear researchers, and research manager.

Do not commit ticker research dumps (HTML notes, full `management-*.md` packs, or `SOURCES.md` for a name) into this repo. Keep those next to the run. A skeleton is at the bottom of this file so a later pass has a shape to fill.

## Checklist

Run the steps in this order. Skip a step only by writing why under Gaps.

1. **Market data.** OHLCV and the verified market snapshot (`get_stock_data`, `get_verified_market_snapshot`, indicators). The snapshot must include **calendar YTD simple return** (latest close on or before the analysis date, divided by the last close before January 1 of that year, minus one) and **dividend yield** from Yahoo `dividendYield` when that field is present. If either print is missing, the snapshot line is `—` plus the reason. Copy that line into Gaps. Do not recompute a blank YTD from memory.
2. **FRED key series.** Call `get_fred_key_series` once. It attempts fed funds, the 2-year and 10-year Treasury yields, the 10y–2y curve, CPI, core PCE, and unemployment. A missing key, a failed request, an unknown series, or a window with no observations is an explicit `Gap:` line. The helper does not return an empty string. Do not invent the print.
3. **Filings.** Statements from the bound fundamentals tools. When a primary filing was actually retrieved, prefer SEC EDGAR, and SEDAR+ for a Canadian issuer. This repo's vendors do not download EDGAR or SEDAR+ themselves.
4. **Shareholder / controller pack.** Required. Ownership %, voting caps, fee arrangements, and strategy letters or presentations from the controller (Pershing's letters for HHH are the shape, not a default fact). 13D/13F only when that filing was retrieved. Attribute the source. Insider Form 4 rows are not a substitute.
5. **Management commentary pack.** Required. CEO, President, and CFO quotes from earnings calls and IR press releases. Distill them into a local `management-*.md` (`management-strategy.md`, or `management-and-pershing.md` when the controller is part of the voice) with speaker, date, and document.
6. **Earnings transcript.** Source order is company IR, then Quartr or stockanalysis, then Motley Fool marked **secondary**. Save the retrieved text under `transcripts/{ticker}/{call-date}-{source}.md` (helper: `save_retrieved_transcript`). If nothing was retrieved, or the only file is a secondary Motley Fool copy, write a Gap. A secondary quote may stay in the note only with that flag.
7. **Peers.** Only names and figures that appear in retrieved sources. No borrowed multiples.
8. **TA graph.** Indicators chosen and computed by the market analyst. No hand-drawn levels that the series does not show.
9. **Note + Gaps + residue.** Equity-research HTML (or the markdown report tree under `1_analysts/`) plus a Gaps section plus a short residue list. Residue is blocked URLs and excerpts that were not promoted into the note, kept so a later pass can retry. Residue is not a print.

## Source order

Use the first source that was actually retrieved. Do not skip ahead by inventing what a higher source "would have said."

1. SEC EDGAR, and SEDAR+ when the issuer reports in Canada.
2. Company press or GlobeNewswire.
3. Controller investor materials (strategy letter, presentation, 13D exhibit).
4. Earnings transcripts, in this order: company IR, then Quartr or stockanalysis, then Motley Fool marked **secondary**. Save under `transcripts/`. A note that only has the secondary copy still carries a Gap.
5. Yahoo quotes (price and profile fields only; not a substitute for a filing or a call).

## IR mirrors

Prefer, in order, a SEC EX-99 exhibit, the exchange filing, and the GlobeNewswire copy. Company IR pages and GCS-hosted decks are optional mirrors, not the first request.

When Akamai, an edge 403, or GCS returns a block or an empty deck:

- Record `Gap:` plus the blocked URL and the reason. `ir_cdn_gap(url, reason)` formats that line and does not fetch.
- Read the SEC EX-99 (or the exchange filing / GlobeNewswire copy) if that text was actually retrieved.
- Do not retry the CDN and do not hammer the IR host. One recorded block is enough.

`looks_like_cdn_block` only classifies an error string the caller already has. It does not open a connection.

## What the agents can and cannot fetch

Bound tools are Yahoo Finance, Alpha Vantage, FRED (`get_macro_indicators` and `get_fred_key_series` on the news analyst), prediction markets, and `get_insider_transactions`. Optional Chinese-market and Xueqiu paths are separate and do not fill a US controller pack.

Those tools do not fetch EDGAR, SEDAR+, GlobeNewswire, or IR CDNs. A deep run still **opens** the shareholder and management sections. Anything not in tool output goes to Gaps. An operator who pastes a primary document into the run follows the source order above. The model does not backfill from memory.

## Known egress blocks and fallbacks

| Block | What to do | If the fallback is also empty |
| --- | --- | --- |
| IR host denies via Akamai (CDN 403 / edge block) | Record Gap + blocked URL. Use SEC EX-99, the exchange filing, or GlobeNewswire. Do not retry the CDN. | Gap stays open. Do not retype the release from memory. |
| Shopify (or similar) GCS investor decks return empty | Record Gap + deck URL. Use the SEC exhibit that carried the deck. Do not hammer GCS. | Gap. Do not describe slides that were not retrieved. |
| FRED key series missing, key unset, empty window, or vendor error | `get_fred_key_series` writes `Gap: FRED ...` for each failed series. The pack is never a silent empty string. | Gap. Do not invent CPI, rates, or a curve. |
| Yahoo / vendor / TradingAgents news empty | — | Gap. Do not invent headlines. |
| Calendar YTD blank (no prior-year close in the verified window) | Snapshot line is `—` plus the reason | Gap. Do not invent the percent. |
| Dividend yield absent from Yahoo info, or the lookup failed | Snapshot line is `—` plus the reason | Gap. Do not invent a yield. A returned `0` is a real zero yield, not a Gap. |
| Earnings transcript only from Motley Fool, or none at all | Save whatever was retrieved under `transcripts/`. Gap the missing company IR / Quartr / stockanalysis copy. | Do not promote the secondary file to a company transcript. |
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
- Last / range: {from verified snapshot}
- Calendar YTD simple return: {snapshot line, or — (reason)}
- Dividend yield: {Yahoo dividendYield as returned, or — (reason)}

## FRED key series
- {alias}: {latest print, or Gap: FRED alias — reason}

## Earnings transcript
- File: transcripts/{ticker}/{call-date}-{source}.md
- Rank: company IR | Quartr | stockanalysis | Motley Fool (secondary)
- Gap if none, or if the only file is secondary

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
- {item} — {source that failed} — {blocked URL if any} — fallback {tried or "none"} — still open
- IR example: Gap: IR CDN blocked — Akamai 403 — https://ir.example/release — do not retry; SEC EX-99 mirror {used or still open}

## Residue
- {blocked url or unused excerpt, not promoted into the note}
```

Local files beside the run, not committed:

- `management-strategy.md` or `management-and-pershing.md` — the distilled voice layer with attribution
- `SOURCES.md` — retrieved sources and the same Gaps list
