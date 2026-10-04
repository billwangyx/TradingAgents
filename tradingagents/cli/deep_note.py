"""Single-ticker deep note.

Research only. The default graph is analysts → bull → bear → research manager.
It does not place orders. Pass ``--full-trading-graph`` to keep the trader,
the risk desk, and the portfolio manager.

Examples::

    python -m tradingagents.cli deep-note --ticker HHH --date 2026-10-02
    python -m tradingagents.cli deep-note --ticker HHH --date 2026-10-02 --out ./notes/HHH
    python -m tradingagents.cli deep-note --ticker HHH --date 2026-10-02 --research-dir ./research/HHH
"""

from __future__ import annotations

import copy
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from tradingagents.agents.utils.local_fundamental_pack import (
    build_local_fundamental_pack,
)
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients.model_catalog import (
    resolve_deep_think_model,
    resolve_quick_think_model,
)

app = typer.Typer(
    help="Headless equity research. Does not place orders.",
    no_args_is_help=True,
)


@app.callback()
def _root() -> None:
    """Headless equity research. Does not place orders."""

_DEFAULT_ANALYSTS = ("market", "social", "news", "fundamentals")


def build_deep_note_config(
    *,
    provider: str = "deepseek",
    quick_model: str = "deepseek-flash",
    deep_model: str | None = None,
    research_mode: bool = True,
) -> dict:
    """Config for a deep-note run.

    Research mode is on. Analysts and the quick path default to DeepSeek
    flash (API id ``deepseek-v4-flash``) when the provider is DeepSeek.
    """
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["llm_provider"] = provider
    config["research_mode"] = research_mode
    config["quick_think_llm"] = resolve_quick_think_model(provider, quick_model)
    config["deep_think_llm"] = resolve_deep_think_model(
        provider, deep_model if deep_model else config.get("deep_think_llm")
    )
    return config


def _local_pack_from_research_dir(research_dir: Path | None) -> str:
    """Compress caller-supplied .txt/.md, or return empty when no directory was passed."""
    if research_dir is None:
        return ""
    path = Path(research_dir)
    if not path.is_dir():
        raise typer.BadParameter(
            f"research directory does not exist or is not a directory: {path}"
        )
    return build_local_fundamental_pack(path)


def _parse_analysts(raw: str | None) -> tuple[str, ...]:
    if raw is None or not raw.strip():
        return _DEFAULT_ANALYSTS
    keys = tuple(part.strip().lower() for part in raw.split(",") if part.strip())
    if not keys:
        return _DEFAULT_ANALYSTS
    return keys


@app.command("deep-note")
def deep_note(
    ticker: Annotated[str, typer.Option("--ticker", help="Ticker, for example HHH.")],
    date: Annotated[str, typer.Option("--date", help="Analysis date, YYYY-MM-DD.")],
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Directory for the markdown report tree. Defaults under the results dir."),
    ] = None,
    research_mode: Annotated[
        bool,
        typer.Option(
            "--research-mode/--full-trading-graph",
            help=(
                "Default research-mode stops after the Research Manager. "
                "--full-trading-graph keeps Trader, Risk, and Portfolio Manager. "
                "Neither path places an order."
            ),
        ),
    ] = True,
    provider: Annotated[
        str,
        typer.Option("--provider", help="LLM provider. Deep-note defaults to deepseek."),
    ] = "deepseek",
    quick_model: Annotated[
        str,
        typer.Option(
            "--quick-model",
            help=(
                "Analyst and quick model. deepseek-flash resolves to deepseek-v4-flash "
                "when the provider is deepseek."
            ),
        ),
    ] = "deepseek-flash",
    deep_model: Annotated[
        str | None,
        typer.Option("--deep-model", help="Research-manager model. DeepSeek defaults to deepseek-v4-pro."),
    ] = None,
    analysts: Annotated[
        str | None,
        typer.Option("--analysts", help="Comma-separated analysts. Default: market,social,news,fundamentals."),
    ] = None,
    research_dir: Annotated[
        Path | None,
        typer.Option(
            "--research-dir",
            help=(
                "Optional local directory of financial-report text already on disk "
                "(.txt and .md, including SOURCES.md). When set, that text is "
                "compressed into a short fundamental pack and given to the research "
                "manager with fundamentals_report. PDFs are not parsed and nothing "
                "is downloaded."
            ),
        ),
    ] = None,
) -> None:
    """Run one equity note. Research only; does not place orders.

    News vendors, in order, are Yahoo, Alpha Vantage, then Eastmoney via
    akshare for CN/HK names. An empty chain sets NEWS_EMPTY and does not
    invent headlines. Calendar YTD uses Yahoo ytdReturn, or OHLC (first close
    of the year to the last close) when that field is empty or the quote
    lookup returns 401.
    """
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError as exc:
        raise typer.BadParameter("date must be YYYY-MM-DD") from exc

    ticker = ticker.strip().upper()
    if not ticker:
        raise typer.BadParameter("ticker is required")

    local_pack = _local_pack_from_research_dir(research_dir)

    selected = _parse_analysts(analysts)
    config = build_deep_note_config(
        provider=provider.strip().lower(),
        quick_model=quick_model.strip(),
        deep_model=deep_model.strip() if deep_model else None,
        research_mode=research_mode,
    )

    # Imported here so `--help` does not construct a graph or touch a broker.
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = TradingAgentsGraph(selected_analysts=selected, config=config)
    final_state, rating = graph.propagate(
        ticker, date, local_fundamental_pack=local_pack
    )
    report_path = graph.save_reports(final_state, ticker, save_path=out)
    mode = "research-mode (stops after Research Manager)" if research_mode else "full trading graph"
    news = "NEWS_EMPTY" if final_state.get("news_empty") else "news present"
    typer.echo(
        f"{ticker} {date}: {mode}; quick model {config['quick_think_llm']}; {news}; "
        f"rating {rating}. Research only; no order placed. Report: {report_path}"
    )
