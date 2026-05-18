"""
Runtime memory for Nancy's single-user dashboard session.

The LLM conversation history is intentionally compact, but the dashboard needs
to remember richer artifacts such as the last Pine script, backtest request,
summary, and replay bars.  This module keeps that state outside the model
prompt so follow-up requests can act on the current chart/backtest context.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any


_last_pine_code: str | None = None
_last_backtest_config: dict[str, Any] | None = None
_last_backtest_summary: dict[str, Any] | None = None
_last_replay_snapshot: dict[str, Any] | None = None


def _clone(value: Any) -> Any:
    return deepcopy(value)


def remember_pine_code(pine_code: str | None) -> None:
    global _last_pine_code
    if pine_code:
        _last_pine_code = pine_code


def get_last_pine_code() -> str | None:
    return _last_pine_code


def remember_backtest_config(config: dict[str, Any]) -> None:
    global _last_backtest_config
    _last_backtest_config = _clone(config)
    remember_pine_code(config.get("pine_code"))


def get_last_backtest_config() -> dict[str, Any] | None:
    return _clone(_last_backtest_config) if _last_backtest_config else None


def remember_backtest_summary(
    summary: dict[str, Any],
    config: dict[str, Any] | None = None,
    replay_snapshot: dict[str, Any] | None = None,
) -> None:
    global _last_backtest_summary, _last_replay_snapshot

    stored = _clone(summary)
    stored["completed_at"] = datetime.now().isoformat(timespec="seconds")
    if config:
        stored["config"] = _clone(config)
        remember_backtest_config(config)

    _last_backtest_summary = stored

    if replay_snapshot:
        _last_replay_snapshot = _clone(replay_snapshot)


def get_last_backtest_summary() -> dict[str, Any] | None:
    return _clone(_last_backtest_summary) if _last_backtest_summary else None


def get_last_replay_snapshot() -> dict[str, Any] | None:
    return _clone(_last_replay_snapshot) if _last_replay_snapshot else None


def has_backtest_context() -> bool:
    return _last_backtest_config is not None or _last_backtest_summary is not None


def _value(value: Any, fallback: str = "unknown") -> str:
    if value is None or value == "":
        return fallback
    return str(value)


def _range_text(summary: dict[str, Any], config: dict[str, Any] | None = None) -> str:
    config = config or {}
    requested = summary.get("requested_start_date") or config.get("start_date")
    first_dt = summary.get("first_bar_datetime")
    last_dt = summary.get("last_bar_datetime")
    days = summary.get("days_covered")
    bars = summary.get("bars_processed") or (_last_replay_snapshot or {}).get("bar_count")

    parts = []
    if requested:
        parts.append(f"requested start date {requested}")
    if first_dt and last_dt:
        day_text = f", about {days} calendar days" if days is not None else ""
        parts.append(f"actual loaded chart range {first_dt} to {last_dt}{day_text}")
    if bars:
        parts.append(f"{bars} bars")
    return "; ".join(parts) if parts else "date range unavailable"


def _trade_rows_text(summary: dict[str, Any]) -> str:
    rows = summary.get("trade_rows_count", 0)
    reported = summary.get("trade_rows_total_reported") or summary.get("total_trades", 0)
    source = summary.get("trade_rows_source", "unknown")
    if summary.get("trades_unavailable"):
        estimated = summary.get("estimated_signals", 0)
        return (
            f"Trade rows were not available for this run: the official row extractors returned {rows} rows even though "
            f"TradingView's strategy summary reported {reported} trades. Nancy used the summary metrics for "
            f"performance, and drew {estimated} estimated crossover marker(s) from the plotted Pine logic. "
            "That is why Avg Win/Avg Loss may be unavailable: those need individual entry/exit row data."
        )
    if summary.get("trade_rows_partial"):
        return (
            f"TradingView exposed {rows} official Strategy Tester row(s) out of {reported} reported trade(s) via {source}. "
            "Nancy can use those rows exactly, but the missing rows still cannot be reviewed trade by trade."
        )
    return (
        f"Trade rows were available from TradingView ({rows} official row(s), source: {source}), "
        "so Nancy can use them for exact markers and per-trade statistics."
    )


def build_runtime_context() -> str:
    """
    Return a compact prompt block describing Nancy's current remembered state.
    """
    parts: list[str] = []

    if _last_backtest_config:
        strategy = _last_backtest_config.get("strategy") or {}
        parts.append(
            "Latest backtest request: "
            f"{strategy.get('name', 'Strategy')} on "
            f"{_last_backtest_config.get('symbol', 'EURUSD')} "
            f"{_last_backtest_config.get('timeframe', '5')}min from "
            f"{_last_backtest_config.get('start_date', '2024-01-01')} "
            f"for up to {_last_backtest_config.get('max_bars', 200)} bars."
        )

        indicators = strategy.get("indicators") or []
        if indicators:
            parts.append("Remembered strategy indicators: " + ", ".join(map(str, indicators[:8])) + ".")

    if _last_backtest_summary:
        s = _last_backtest_summary
        parts.append(
            "Latest backtest result: "
            f"{s.get('total_trades', 0)} trades, "
            f"{s.get('winning_trades', 0)} wins, "
            f"{s.get('losing_trades', 0)} losses, "
            f"{s.get('win_rate', 0)}% win rate, "
            f"{s.get('return_pct', s.get('net_profit_pct', 0))}% return, "
            f"{s.get('max_drawdown_pct', 0)}% max drawdown; "
            f"{_range_text(s, _last_backtest_config)}."
        )
        if s.get("trades_unavailable"):
            parts.append("Latest backtest has aggregate TradingView metrics, but individual Strategy Tester trade rows were unavailable.")

    if _last_replay_snapshot:
        bars = _last_replay_snapshot.get("bar_count", 0)
        indicators = _last_replay_snapshot.get("indicators") or []
        suffix = f" Indicator overlays available: {', '.join(indicators)}." if indicators else ""
        parts.append(f"Latest chart replay has {bars} bars cached for the dashboard.{suffix}")

    if _last_pine_code:
        parts.append("The full Pine Script from the latest strategy is still available in backend memory.")

    return "\n".join(parts) if parts else "No prior chart/backtest context is stored yet."


def wants_chart_replay(message: str) -> bool:
    msg = message.lower()
    replay_words = ("replay", "bar-by-bar", "bar by bar", "playback", "show me", "watch")
    chart_words = ("chart", "charts", "graph", "lightgraph")
    backtest_words = ("backtest", "test", "strategy")
    return (
        any(word in msg for word in replay_words)
        and (any(word in msg for word in chart_words) or any(word in msg for word in backtest_words))
    )


def wants_backtest_explanation(message: str) -> bool:
    msg = message.lower()
    action_words = (
        "backtest this", "run it", "run this", "test it", "try it",
        "simulate", "replay", "execute", "on the chart", "start the backtest",
    )
    if any(word in msg for word in action_words):
        return False

    followup_words = (
        "explain", "why", "what happened", "breakdown", "more of it", "learn",
        "outcome", "result", "summary", "performance", "how many", "days", "data",
        "date", "start date", "started", "range", "bars", "trade rows", "trade row",
        "markers", "signals", "unavailable", "avg win", "avg loss",
    )
    return has_backtest_context() and any(word in msg for word in followup_words)


def explain_latest_backtest(message: str | None = None) -> str:
    config = _last_backtest_config or {}
    summary = _last_backtest_summary or {}
    strategy = config.get("strategy") or {}
    name = summary.get("strategy_name") or strategy.get("name") or "the strategy"

    if not summary:
        indicators = strategy.get("indicators") or []
        indicator_text = f" I will keep {', '.join(map(str, indicators[:6]))} visible while it plays." if indicators else ""
        return (
            f"I still have {name} in memory, so I can replay it on the chart without you pasting the Pine Script again."
            f"{indicator_text}"
        )

    total = summary.get("total_trades", 0)
    wins = summary.get("winning_trades", 0)
    losses = summary.get("losing_trades", 0)
    win_rate = summary.get("win_rate", 0)
    return_pct = summary.get("return_pct", summary.get("net_profit_pct", 0))
    drawdown = summary.get("max_drawdown_pct", 0)
    bars = summary.get("bars_processed") or (_last_replay_snapshot or {}).get("bar_count", 0)
    symbol = summary.get("symbol") or config.get("symbol", "EURUSD")
    timeframe = summary.get("timeframe") or config.get("timeframe", "5")
    range_text = _range_text(summary, config)

    entries = strategy.get("entry_rules") or []
    if isinstance(entries, dict):
        entry_bits = []
        for side, rules in entries.items():
            if rules:
                entry_bits.append(f"{side}: " + "; ".join(map(str, rules[:2])))
        entry_text = " | ".join(entry_bits)
    else:
        entry_text = "; ".join(map(str, entries[:3]))

    indicator_text = ""
    snapshot = _last_replay_snapshot or {}
    indicators = snapshot.get("indicators") or strategy.get("indicators") or []
    if indicators:
        indicator_text = f"\n\nI also put these overlays on the chart replay: {', '.join(map(str, indicators[:6]))}. Watch how price reacts around those lines when a trade marker appears."

    trade_note = (
        "That is a very high trade count, so the useful lesson is not any single trade; "
        "it is the rhythm: fast crossovers fire constantly, and the small losing flips can outnumber the winners."
        if total and total > 100
        else "The useful lesson is to compare each signal with the surrounding candles and ask whether the entry had enough follow-through."
    )
    trade_rows = _trade_rows_text(summary)
    msg = (message or "").lower()

    if any(word in msg for word in ("trade rows", "trade row", "avg win", "avg loss", "markers", "signals", "unavailable")):
        return (
            f"Trade rows are the individual Strategy Tester entries/exits: time, side, price, and per-trade P&L. "
            f"Nancy uses them for exact chart markers, trade-by-trade review, and Avg Win/Avg Loss. {trade_rows}"
        )

    if any(word in msg for word in ("how many", "days", "data", "date", "start", "started", "range", "bars")):
        return (
            f"The last backtest used {bars} bars on {symbol} {timeframe}min. Date detail: {range_text}. "
            "The requested start date and actual loaded chart range can differ if TradingView only exposes the currently loaded/visible historical window."
        )

    return (
        f"Yes. I remember the last backtest for {name}. It processed {bars} bars on {symbol} {timeframe}min "
        f"({range_text}) and reported {total} trades: {wins} wins, {losses} losses, {win_rate}% win rate, "
        f"{return_pct}% return, and {drawdown}% max drawdown.\n\n"
        f"The strategy logic I am tracking is: {entry_text or 'the Pine Script rules from the last strategy'}. "
        f"{trade_note}{indicator_text}\n\n{trade_rows}"
    )
