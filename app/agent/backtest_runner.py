"""
Backtest Runner — Orchestrates TradingView Replay + Strategy Evaluation
------------------------------------------------------------------------
This module ties together:
  1. TradingViewControl (chart control, replay mode, indicator reading)
  2. StrategyEngine (rule evaluation, trade tracking)
  3. SSE streaming (live updates to the Nancy dashboard)

When a user types a natural-language backtest command, Nancy's LLM parses
it into a structured strategy, and this runner executes the full replay loop.
"""

import asyncio
import json
import re
import time
from datetime import datetime, timezone
from app.mcp.tradingview_control import TradingViewControl
from app.agent.strategy_engine import StrategyEngine
from app.agent import memory
from app.logger import system_logger


class BacktestRunner:
    """
    Orchestrates a full backtest using TradingView's replay mode.
    
    Flow:
        1. Setup chart (symbol, timeframe, indicators)
        2. Start replay mode from specified date
        3. Loop: step bar → read values → evaluate → trade
        4. Stop replay → compile summary
        5. Yield SSE events at each step for live dashboard updates
    """

    def __init__(self, tv_control: TradingViewControl):
        self.tv = tv_control
        self.is_running = False

    async def run(self, backtest_config: dict):
        """
        Execute a full backtest and yield SSE events.
        
        Args:
            backtest_config: Dict with keys:
                - symbol: str (e.g. 'EURUSD')
                - timeframe: str (e.g. '5')
                - start_date: str (e.g. '2024-12-01')
                - strategy: dict (rules for StrategyEngine)
                - max_bars: int (optional, default 200)
                - step_delay: float (optional, seconds between steps, default 0.3)
                
        Yields:
            SSE-formatted strings with JSON payloads of types:
                - setup: chart preparation info
                - step: each bar's data + action
                - trade: when a trade is entered/exited
                - complete: final summary
                - error: if something goes wrong
        """
        self.is_running = True
        
        symbol = backtest_config.get("symbol", "EURUSD")
        timeframe = backtest_config.get("timeframe", "5")
        start_date = backtest_config.get("start_date", "2024-01-01")
        strategy_rules = backtest_config.get("strategy", {})
        max_bars = backtest_config.get("max_bars", 200)
        step_delay = backtest_config.get("step_delay", 0.3)
        
        engine = StrategyEngine(strategy_rules)
        memory.remember_backtest_config(backtest_config)
        
        try:
            # ── Step 1: Setup ─────────────────────────────────────────────
            system_logger.info("Backtest", f"Setting up: {symbol} / {timeframe}min from {start_date}")
            
            yield self._sse_event("setup", {
                "status": "preparing",
                "symbol": symbol,
                "timeframe": timeframe,
                "start_date": start_date,
                "strategy_name": engine.name,
            })
            
            # Switch symbol
            switch_result = self.tv.switch_symbol(symbol)
            if "error" in switch_result:
                yield self._sse_event("error", {"message": f"Failed to switch symbol: {switch_result}"})
                return
            await asyncio.sleep(1.0)
            
            # Set timeframe
            tf_result = self.tv.set_timeframe(timeframe)
            if "error" in tf_result:
                system_logger.warning("Backtest", f"Timeframe switch issue: {tf_result}")
            await asyncio.sleep(0.5)
            
            # Scroll backwards to force TradingView to load the historical data into the chart memory
            system_logger.info("Backtest", f"Scrolling chart back to {start_date} to load historical data...")
            self.tv.scroll_to_date(start_date)
            # Wait for chart data to lazily load over the network
            await asyncio.sleep(2.0)  
            
            pine_code = backtest_config.get("pine_code")
            if pine_code:
                system_logger.info("Backtest", "Pine Script detected. Bypassing Replay Mode check to use Instant Strategy Tester directly.")
                yield self._sse_event("setup", {
                    "status": "fallback", 
                    "message": "Using Instant Strategy Tester for Pine Script..."
                })
                async for event in self._run_instant_backtest(pine_code, max_bars, step_delay, backtest_config):
                    yield event
                return
            
            # ── Step 2: Start Replay ──────────────────────────────────────
            system_logger.info("Backtest", f"Starting replay from {start_date}...")
            
            replay_result = self.tv.replay_start(start_date)
            if "error" in replay_result:
                yield self._sse_event("error", {
                    "message": f"Replay mode failed: {replay_result.get('message', 'Unknown error')}. TradingView Premium may be required.",
                    "fallback": True,
                })
                return
            
            await asyncio.sleep(2.0)  # Give TV time to enter replay mode
            
            yield self._sse_event("setup", {
                "status": "replay_started",
                "message": f"Replay active from {start_date}. Processing up to {max_bars} bars...",
            })
            
            # ── Step 3: Main Loop ─────────────────────────────────────────
            system_logger.info("Backtest", f"Beginning bar-by-bar evaluation (max {max_bars} bars)...")
            
            for bar_idx in range(max_bars):
                if not self.is_running:
                    system_logger.warning("Backtest", "Playback stopped by user")
                    break
                
                # Step one bar forward
                step_result = self.tv.replay_step()
                if "error" in step_result:
                    system_logger.warning("Backtest", f"Replay step failed at bar {bar_idx}: {step_result}")
                    if bar_idx == 0:
                        pine_code = backtest_config.get("pine_code")
                        if pine_code:
                            yield self._sse_event("setup", {
                                "status": "fallback", 
                                "message": "Replay mode requires Premium. Falling back to Instant Strategy Tester..."
                            })
                            async for event in self._run_instant_backtest(pine_code, max_bars, step_delay, backtest_config):
                                yield event
                        else:
                            yield self._sse_event("error", {
                                "message": "Replay mode failed. TradingView Premium is required to step through historical data.",
                                "fallback": True
                            })
                        return
                    break
                
                await asyncio.sleep(step_delay)
                
                # Read indicator values
                values = self.tv.get_indicator_values()
                
                # Read current price from quote
                quote_data = self.tv.get_ohlcv()
                current_price = self._extract_price(quote_data)
                current_time = self._extract_time(quote_data, step_result)
                
                if current_price is None:
                    current_price = 0.0
                if current_time is None:
                    current_time = f"bar_{bar_idx}"
                
                # Evaluate strategy
                action = engine.evaluate(values, current_price)
                
                # Execute action
                trade_event = None
                if action == "buy":
                    engine.record_entry("buy", current_price, current_time)
                    self.tv.replay_trade("buy")
                    trade_event = {
                        "action": "BUY",
                        "price": current_price,
                        "time": current_time,
                        "trade_id": engine.trade_counter,
                    }
                elif action == "sell":
                    engine.record_entry("sell", current_price, current_time)
                    self.tv.replay_trade("sell")
                    trade_event = {
                        "action": "SELL",
                        "price": current_price,
                        "time": current_time,
                        "trade_id": engine.trade_counter,
                    }
                elif action == "close":
                    engine.record_exit(current_price, current_time)
                    self.tv.replay_trade("close")
                    last_trade = engine.trades[-1] if engine.trades else None
                    trade_event = {
                        "action": "CLOSE",
                        "price": current_price,
                        "time": current_time,
                        "pnl": last_trade.pnl if last_trade else 0,
                        "pnl_pct": last_trade.pnl_pct if last_trade else 0,
                    }
                
                # Record equity
                engine.record_equity(current_time, current_price)
                
                # Yield step event
                step_data = {
                    "bar": bar_idx + 1,
                    "total_bars": max_bars,
                    "price": current_price,
                    "time": current_time,
                    "action": action,
                    "position": engine.position,
                    "balance": round(engine.balance, 2),
                    "total_trades": len([t for t in engine.trades if t.status == "closed"]),
                }
                
                yield self._sse_event("step", step_data)
                
                # Yield trade event separately if one occurred
                if trade_event:
                    yield self._sse_event("trade", trade_event)
            
            # ── Step 4: Stop Replay & Compile Summary ─────────────────────
            system_logger.info("Backtest", "Stopping replay mode...")
            self.tv.replay_stop()
            await asyncio.sleep(1.0)
            
            summary = engine.get_summary()
            summary.update({
                "symbol": symbol,
                "timeframe": timeframe,
                "requested_start_date": start_date,
                "max_bars_requested": max_bars,
                **self._time_range_summary(
                    [point.get("time") for point in engine.equity_curve if isinstance(point, dict)],
                    requested_start_date=start_date,
                ),
            })
            system_logger.info("Backtest", 
                f"Complete: {summary['total_trades']} trades | "
                f"Win rate: {summary['win_rate']}% | "
                f"Return: {summary['return_pct']}%"
            )
            
            memory.remember_backtest_summary(
                summary,
                backtest_config,
                {
                    "bar_count": summary.get("bars_processed", 0),
                    "indicators": strategy_rules.get("indicators", []),
                },
            )
            yield self._sse_event("complete", summary)
            
        except asyncio.CancelledError:
            system_logger.warning("Backtest", "Client disconnected")
            self.tv.replay_stop()
            raise
        except Exception as e:
            system_logger.error("Backtest", f"Unexpected error: {e}")
            self.tv.replay_stop()
            yield self._sse_event("error", {"message": str(e)})
        finally:
            self.is_running = False

    def stop(self):
        """Signal the runner to stop after the current bar."""
        self.is_running = False

    async def _run_instant_backtest(self, pine_code: str, max_bars: int, step_delay: float, backtest_config: dict | None = None):
        """
        Fallback mechanism for users without TradingView Premium.
        Instead of stepping through bars, we compile the Pine Script strategy to the chart,
        let TradingView calculate it instantly, and stream the resulting trades.
        """
        system_logger.info("Backtest", "Running instant Strategy Tester fallback...")
        
        # 1. Load Pine Script
        system_logger.info("Backtest", "Step 1a: Opening Pine Editor panel...")
        open_res = self.tv.open_pine_editor()
        system_logger.info("Backtest", f"open_pine_editor result: {json.dumps(open_res)[:500]}")
        await asyncio.sleep(1.0)

        system_logger.info("Backtest", f"Step 1b: pine_set — loading {len(pine_code)} chars of Pine Script...")
        set_res = self.tv.pine_set(pine_code)
        system_logger.info("Backtest", f"pine_set result: {json.dumps(set_res)[:500]}")

        if "error" in set_res and "pine editor" in json.dumps(set_res).lower():
            system_logger.warning("Backtest", "Pine Editor was not ready. Creating/focusing a new Pine Script and retrying...")
            new_res = self.tv.pine_new()
            system_logger.info("Backtest", f"pine_new result: {json.dumps(new_res)[:500]}")
            await asyncio.sleep(1.5)
            self.tv.open_pine_editor()
            await asyncio.sleep(1.0)
            set_res = self.tv.pine_set(pine_code)
            system_logger.info("Backtest", f"pine_set retry result: {json.dumps(set_res)[:500]}")

        if "error" in set_res:
            error_msg = set_res.get("message") or set_res.get("details") or "Unknown error setting Pine Script"
            system_logger.warning("Backtest", f"Failed to set Pine Script: {error_msg}")
            yield self._sse_event("error", {"message": f"Failed to load Pine Script into TradingView after opening the Pine Editor. TradingView may need to be logged in and the chart page fully loaded. Error: {error_msg}"})
            return
        await asyncio.sleep(1.5)
        
        # 2. Compile and apply — TWO-PHASE approach
        #    Phase 1: First compile usually just SAVES the script (if it's new code).
        #    Phase 2: Second compile detects "Add to chart" button and actually applies it.
        system_logger.info("Backtest", "Step 2a: pine_compile (Phase 1 — save script)...")
        compile_res = self.tv.pine_compile()
        system_logger.info("Backtest", f"Phase 1 result: {json.dumps(compile_res)[:500]}")
        if "error" in compile_res:
            yield self._sse_event("error", {"message": f"Strategy compilation failed: {compile_res.get('message', 'Unknown')}"})
            return
            
        if compile_res.get("has_errors"):
            errors = compile_res.get("errors", [])
            # Filter out severity 4 (warnings) to find actual errors
            actual_errors = [e.get("message", "Unknown Error") for e in errors if e.get("severity", 8) > 4]
            if actual_errors:
                error_str = " | ".join(actual_errors)
                yield self._sse_event("error", {"message": f"Pine Script compilation failed with errors: {error_str}"})
                return
        
        # Check if the strategy was actually added to the chart
        study_added = compile_res.get("study_added", False)
        button_clicked = compile_res.get("button_clicked", "")
        
        if not study_added and "add to chart" not in str(button_clicked).lower():
            # Phase 2: The first compile only saved — now "Add to chart" should be visible
            system_logger.info("Backtest", "Step 2b: Strategy not yet on chart. Waiting 2s then re-compiling to trigger 'Add to chart'...")
            await asyncio.sleep(2.0)
            compile_res2 = self.tv.pine_compile()
            system_logger.info("Backtest", f"Phase 2 result: {json.dumps(compile_res2)[:500]}")
            
            study_added2 = compile_res2.get("study_added", False)
            button_clicked2 = compile_res2.get("button_clicked", "")
            
            if not study_added2 and "add to chart" not in str(button_clicked2).lower():
                # Phase 3: Last resort — try raw-compile which blindly clicks whatever compile button exists
                system_logger.info("Backtest", "Step 2c: Still not on chart. Trying raw-compile as last resort...")
                await asyncio.sleep(1.0)
                raw_res = self.tv._run_tv_command([self.tv.tv_path, "pine", "raw-compile"], timeout=15)
                system_logger.info("Backtest", f"raw-compile result: {json.dumps(raw_res)[:500]}")
        
        # Give TradingView time to apply the strategy and calculate trades
        system_logger.info("Backtest", "Step 3: Waiting 5 seconds for TradingView to calculate strategy trades...")
        await asyncio.sleep(5.0)
        
        # 3. Read performance and official TradingView trade rows
        system_logger.info("Backtest", "Step 4: Reading strategy performance...")
        perf_res = self.tv.get_strategy_performance()
        system_logger.info("Backtest", f"get_strategy_performance result: {json.dumps(perf_res)[:800]}")
        
        perf_total = int(perf_res.get("total_trades", 0) or 0) if isinstance(perf_res, dict) else 0
        requested_trade_rows = max(perf_total, max_bars * 4, 5000)
        system_logger.info("Backtest", f"Step 5: Reading official strategy trade rows (target {requested_trade_rows})...")
        trades_res = self.tv.get_strategy_trades(max_trades=requested_trade_rows)
        system_logger.info("Backtest", f"get_strategy_trades result: {json.dumps(trades_res)[:1200]}")
        
        trade_list = trades_res.get("trades", []) if isinstance(trades_res, dict) else []
        if not isinstance(trade_list, list):
            trade_list = []
            
        official_row_count = len(trade_list)
        total = perf_total or official_row_count
        trades_unavailable = official_row_count == 0 and perf_total > 0
        trade_rows_partial = bool(perf_total and 0 < official_row_count < perf_total)
        if trades_unavailable:
            system_logger.info("Backtest", f"Strategy summary reports {perf_total} trades; official individual rows were not exposed by TradingView.")
        elif trade_rows_partial:
            system_logger.info("Backtest", f"Extracted {official_row_count}/{perf_total} official TradingView trade rows ({trades_res.get('source', 'unknown')}).")
        else:
            system_logger.info("Backtest", f"Extracted {official_row_count} official TradingView trade rows ({trades_res.get('source', 'unknown')}).")
        
        if total == 0:
            system_logger.warning("Backtest", "Strategy returned 0 trades. Possible causes: Pine Script didn't compile as strategy, strategy tab not visible, or compilation silently failed.")
            # Try reading performance one more time after an additional wait
            system_logger.info("Backtest", "Retrying: waiting 3 more seconds and re-reading...")
            await asyncio.sleep(3.0)
            perf_res = self.tv.get_strategy_performance()
            retry_perf_total = int(perf_res.get("total_trades", 0) or 0) if isinstance(perf_res, dict) else 0
            perf_total = retry_perf_total or perf_total
            requested_trade_rows = max(perf_total, max_bars * 4, 5000)
            trades_res = self.tv.get_strategy_trades(max_trades=requested_trade_rows)
            system_logger.info("Backtest", f"Retry perf: {json.dumps(perf_res)[:500]}")
            system_logger.info("Backtest", f"Retry trades: {json.dumps(trades_res)[:800]}")
            trade_list = trades_res.get("trades", []) if isinstance(trades_res, dict) else []
            if not isinstance(trade_list, list):
                trade_list = []
            official_row_count = len(trade_list)
            total = perf_total or official_row_count
            trades_unavailable = official_row_count == 0 and perf_total > 0
            trade_rows_partial = bool(perf_total and 0 < official_row_count < perf_total)
            system_logger.info("Backtest", f"After retry: {official_row_count} official trade rows found.")
            
        # Forcefully exit replay mode just in case TV is stuck in a weird state from a silently failed replay_start
        self.tv.replay_stop()
        await asyncio.sleep(0.5)
        
        # Fetch 500 historical bars from TradingView to simulate the chart replay
        system_logger.info("Backtest", "Step 6: Fetching 500 historical bars for chart replay...")
        bars_res = self.tv.get_chart_bars(count=500)
        bars = bars_res.get("bars", []) if isinstance(bars_res, dict) else []
        system_logger.info("Backtest", f"get_chart_bars returned {len(bars)} bars.")
        
        if not bars:
            system_logger.error("Backtest", f"get_chart_bars returned empty or error: {bars_res}")
            yield self._sse_event("error", {"message": "Failed to fetch historical candlestick data for local replay."})
            return
            
        indicator_defs = self._extract_overlay_indicators(pine_code)
        indicator_series = self._build_indicator_series(bars, indicator_defs)
        if indicator_defs:
            system_logger.info("Backtest", "Chart indicator overlays: " + ", ".join(d["title"] for d in indicator_defs))

        # Sort trades by time just in case
        def _get_trade_time(t):
            time_val = t.get("time")
            coerced = self._coerce_timestamp(time_val)
            if coerced is not None:
                return coerced
            try:
                if isinstance(time_val, str):
                    import dateutil.parser
                    dt = dateutil.parser.parse(time_val)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return int(dt.timestamp())
                return 9999999999
            except Exception:
                return 9999999999
                
        sorted_trades = sorted(trade_list, key=_get_trade_time)
        trade_idx = 0
        estimated_signals = []
        should_estimate_missing = (trades_unavailable and not sorted_trades) or trade_rows_partial
        if should_estimate_missing:
            estimated_signals = self._estimate_crossover_signals(bars, indicator_defs, indicator_series)
            if estimated_signals:
                reason = "no official trade rows" if trades_unavailable else "partial official trade rows"
                system_logger.info("Backtest", f"Generated {len(estimated_signals)} estimated crossover signal marker(s) for chart replay because {reason} were available.")
        signal_idx = 0
        
        # Split bars into initial context (first 200) and replay animation (next 300)
        split_point = min(200, len(bars) // 2)
        initial_batch = bars[:split_point]
        replay_batch = bars[split_point:]
        replay_start_time = int(replay_batch[0].get("time", 0) or 0) if replay_batch else 0
        while trade_idx < len(sorted_trades) and _get_trade_time(sorted_trades[trade_idx]) < replay_start_time:
            trade_idx += 1
        while signal_idx < len(estimated_signals) and int(estimated_signals[signal_idx].get("time", 0) or 0) < replay_start_time:
            signal_idx += 1
        
        # 1. Send the setup event with the initial historical context
        yield self._sse_event("setup", {
            "data": initial_batch,
            "indicators": self._indicator_setup_payload(indicator_defs, indicator_series, 0, split_point),
        })
        await asyncio.sleep(1.0)
        
        # 2. Stream the remaining bars one-by-one
        for i, bar in enumerate(replay_batch):
            if not self.is_running:
                break
                
            bar_time = int(bar.get("time", 0))
            
            # Send the candle tick
            absolute_idx = split_point + i
            yield self._sse_event("tick", {
                "bar": i + 1,
                "total_bars": len(replay_batch),
                "data": bar,
                "status": "running",
                "indicators": self._indicator_tick_payload(indicator_defs, indicator_series, absolute_idx),
            })
            
            # Check if any official trades occurred on or before this bar.
            while trade_idx < len(sorted_trades):
                t = sorted_trades[trade_idx]
                t_time = _get_trade_time(t)
                
                if t_time <= bar_time:
                    action_type = self._trade_action(t)
                    
                    yield self._sse_event("trade", {
                        "action": action_type,
                        "price": float(t.get("price", 0) or 0),
                        "time": t_time if t_time != 9999999999 else str(t.get("time")),
                        "pnl_pct": float(t.get("profit_pct", 0) or 0),
                        "official": True,
                        "source": (t.get("source") or trades_res.get("source", "official_trade_row")) if isinstance(trades_res, dict) else "official_trade_row",
                    })
                    trade_idx += 1
                else:
                    break

            # If TradingView only exposed summary stats, show local crossover markers
            # so the replay still teaches the strategy rhythm on the chart.
            while signal_idx < len(estimated_signals):
                signal = estimated_signals[signal_idx]
                if int(signal.get("time", 0) or 0) <= bar_time:
                    yield self._sse_event("trade", signal)
                    signal_idx += 1
                else:
                    break
                    
            await asyncio.sleep(step_delay)
            
        # Any remaining trades or estimated markers that happen after the last bar (edge case)
        while trade_idx < len(sorted_trades):
            t = sorted_trades[trade_idx]
            t_time = _get_trade_time(t)
            action_type = self._trade_action(t)
            yield self._sse_event("trade", {
                "action": action_type,
                "price": float(t.get("price", 0) or 0),
                "time": t_time if t_time != 9999999999 else str(t.get("time")),
                "pnl_pct": float(t.get("profit_pct", 0) or 0),
                "official": True,
                "source": (t.get("source") or trades_res.get("source", "official_trade_row")) if isinstance(trades_res, dict) else "official_trade_row",
            })
            trade_idx += 1

        while signal_idx < len(estimated_signals):
            yield self._sse_event("trade", estimated_signals[signal_idx])
            signal_idx += 1
            
        perf = perf_res if isinstance(perf_res, dict) and "error" not in perf_res else {}
        config = backtest_config or memory.get_last_backtest_config() or {}
        row_stats = self._trade_row_stats(trade_list)
        summary = {
            "strategy_name": perf.get("name", "Instant Strategy Fallback"),
            "symbol": config.get("symbol", "EURUSD"),
            "timeframe": config.get("timeframe", "5"),
            "requested_start_date": config.get("start_date"),
            "max_bars_requested": max_bars,
            "bars_processed": len(bars),
            "total_trades": perf.get("total_trades", total),
            "winning_trades": perf.get("winning_trades", 0),
            "losing_trades": perf.get("losing_trades", 0),
            "win_rate": perf.get("win_rate", 0),
            "return_pct": perf.get("net_profit_pct", 0),
            "max_drawdown_pct": perf.get("max_drawdown_pct", 0),
            "final_balance": 10000 + (10000 * (float(perf.get("net_profit_pct", 0) or 0) / 100)),
            "indicator_overlays": [d["title"] for d in indicator_defs],
            "trades_unavailable": trades_unavailable,
            "trade_rows_available": official_row_count > 0,
            "trade_rows_partial": trade_rows_partial,
            "trade_rows_count": official_row_count,
            "trade_rows_total_reported": perf_total or total,
            "trade_rows_source": trades_res.get("source", "unknown") if isinstance(trades_res, dict) else "unknown",
            "trade_rows_attempts": trades_res.get("attempts", []) if isinstance(trades_res, dict) else [],
            "trade_rows_note": (
                "TradingView reported aggregate strategy metrics, but neither its internal model nor the visible Strategy Tester table exposed individual rows. "
                "Nancy therefore used summary totals for performance and local Pine overlay logic for estimated chart markers."
                if trades_unavailable else
                (f"TradingView exposed {official_row_count} official row(s) out of {perf_total} reported trade(s); markers and per-row stats are exact for the rows received."
                 if trade_rows_partial else
                 "TradingView exposed individual official Strategy Tester rows, so markers and per-trade stats came from those rows.")
            ),
            "estimated_signals": len(estimated_signals),
            **row_stats,
            **self._bar_range_summary(bars, requested_start_date=config.get("start_date")),
        }
        memory.remember_backtest_summary(
            summary,
            config,
            {"bar_count": len(bars), "indicators": [d["title"] for d in indicator_defs]},
        )
        yield self._sse_event("complete", summary)


    def _trade_action(self, trade: dict) -> str:
        explicit = str(trade.get("action", "")).upper()
        if explicit in {"BUY", "SELL", "CLOSE"}:
            return explicit

        trade_type = " ".join(str(trade.get(key, "")) for key in ("type", "side", "direction", "orderType", "position")).lower()
        if "exit" in trade_type or "close" in trade_type:
            return "CLOSE"
        if "long" in trade_type or "buy" in trade_type:
            return "BUY"
        if "short" in trade_type or "sell" in trade_type:
            return "SELL"
        return "TRADE"

    def _bar_range_summary(self, bars: list[dict], requested_start_date: str | None = None) -> dict:
        """Summarize the actual loaded chart range used for the local replay."""
        times = []
        for bar in bars:
            if not isinstance(bar, dict):
                continue
            times.append(bar.get("time") or bar.get("timestamp") or bar.get("datetime") or bar.get("date"))
        return self._time_range_summary(times, requested_start_date=requested_start_date)

    def _time_range_summary(self, times: list, requested_start_date: str | None = None) -> dict:
        timestamps = [self._coerce_timestamp(value) for value in times]
        timestamps = [value for value in timestamps if value is not None]
        summary = {"requested_start_date": requested_start_date}
        if not timestamps:
            return summary

        first_ts = min(timestamps)
        last_ts = max(timestamps)
        seconds = max(0, last_ts - first_ts)
        days = seconds / 86400 if seconds else 0
        summary.update({
            "first_bar_time": first_ts,
            "last_bar_time": last_ts,
            "first_bar_datetime": self._format_timestamp(first_ts),
            "last_bar_datetime": self._format_timestamp(last_ts),
            "first_bar_date": self._format_timestamp(first_ts, include_time=False),
            "last_bar_date": self._format_timestamp(last_ts, include_time=False),
            "days_covered": round(days, 2),
            "hours_covered": round(seconds / 3600, 2),
        })
        return summary

    def _coerce_timestamp(self, value) -> int | None:
        if value is None:
            return None
        try:
            if isinstance(value, (int, float)):
                timestamp = float(value)
                return int(timestamp / 1000) if timestamp > 10000000000 else int(timestamp)
            if isinstance(value, str):
                stripped = value.strip()
                if not stripped:
                    return None
                if re.fullmatch(r"\d+(?:\.\d+)?", stripped):
                    timestamp = float(stripped)
                    return int(timestamp / 1000) if timestamp > 10000000000 else int(timestamp)
                iso_value = stripped.replace("Z", "+00:00")
                try:
                    dt = datetime.fromisoformat(iso_value)
                except ValueError:
                    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                        try:
                            dt = datetime.strptime(stripped, fmt)
                            break
                        except ValueError:
                            dt = None
                    if dt is None:
                        return None
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return int(dt.timestamp())
        except (TypeError, ValueError, OverflowError):
            return None
        return None

    def _format_timestamp(self, timestamp: int, include_time: bool = True) -> str:
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        if include_time:
            return dt.strftime("%Y-%m-%d %H:%M UTC")
        return dt.strftime("%Y-%m-%d")

    def _trade_row_stats(self, trades: list[dict]) -> dict:
        profit_pcts = []
        for trade in trades:
            if not isinstance(trade, dict):
                continue
            raw = trade.get("profit_pct", trade.get("pnl_pct"))
            try:
                profit_pcts.append(float(raw))
            except (TypeError, ValueError):
                continue

        wins = [value for value in profit_pcts if value > 0]
        losses = [value for value in profit_pcts if value < 0]
        return {
            "avg_win_pct": round(sum(wins) / len(wins), 2) if wins else None,
            "avg_loss_pct": round(sum(losses) / len(losses), 2) if losses else None,
        }

    def _extract_overlay_indicators(self, pine_code: str) -> list[dict]:
        """Extract simple overlay MA plots from Pine code for local chart replay."""
        if not pine_code:
            return []

        assignments = {}
        assignment_re = re.compile(
            r"^\s*([A-Za-z_]\w*)\s*=\s*ta\.(sma|ema|wma|rma)\s*\(\s*(open|high|low|close|hl2|hlc3|ohlc4)\s*,\s*(\d+)\s*\)",
            re.IGNORECASE,
        )
        for line in pine_code.splitlines():
            match = assignment_re.search(line)
            if match:
                var_name, kind, source, length = match.groups()
                assignments[var_name] = {
                    "id": var_name,
                    "title": f"{kind.upper()} {length}",
                    "kind": kind.lower(),
                    "source": source.lower(),
                    "length": int(length),
                    "color": None,
                }

        overlays = []
        for line in pine_code.splitlines():
            stripped = line.strip()
            if not stripped.lower().startswith("plot("):
                continue
            inner = stripped[stripped.find("(") + 1:]
            if inner.endswith(")"):
                inner = inner[:-1]
            args = self._split_pine_args(inner)
            if not args:
                continue

            expr = args[0].strip()
            if expr not in assignments:
                continue

            kwargs = self._parse_pine_kwargs(args[1:])
            definition = dict(assignments[expr])
            definition["title"] = self._strip_pine_string(kwargs.get("title")) or definition["title"]
            definition["color"] = self._pine_color_to_hex(kwargs.get("color")) or definition["color"]
            overlays.append(definition)

        if not overlays:
            overlays = list(assignments.values())

        default_colors = ["#2962ff", "#f23645", "#ff9800", "#7e57c2", "#00bcd4", "#8bc34a"]
        deduped = []
        seen = set()
        for idx, item in enumerate(overlays):
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            item["color"] = item.get("color") or default_colors[idx % len(default_colors)]
            deduped.append(item)
            if len(deduped) >= 6:
                break
        return deduped

    def _split_pine_args(self, value: str) -> list[str]:
        args = []
        current = []
        depth = 0
        quote = None
        for char in value:
            if quote:
                current.append(char)
                if char == quote:
                    quote = None
                continue
            if char in ("'", '"'):
                quote = char
                current.append(char)
                continue
            if char == "(":
                depth += 1
            elif char == ")" and depth > 0:
                depth -= 1
            if char == "," and depth == 0:
                args.append("".join(current).strip())
                current = []
            else:
                current.append(char)
        if current:
            args.append("".join(current).strip())
        return args

    def _parse_pine_kwargs(self, args: list[str]) -> dict:
        output = {}
        for arg in args:
            if "=" not in arg:
                continue
            key, value = arg.split("=", 1)
            output[key.strip().lower()] = value.strip()
        return output

    def _strip_pine_string(self, value: str | None) -> str | None:
        if not value:
            return None
        value = value.strip()
        if len(value) >= 2 and value[0] in ("'", '"') and value[-1] == value[0]:
            return value[1:-1]
        return value

    def _pine_color_to_hex(self, value: str | None) -> str | None:
        if not value:
            return None
        color_map = {
            "blue": "#2962ff",
            "red": "#f23645",
            "green": "#089981",
            "lime": "#00e676",
            "orange": "#ff9800",
            "yellow": "#fdd835",
            "purple": "#7e57c2",
            "aqua": "#00bcd4",
            "teal": "#26a69a",
            "fuchsia": "#e040fb",
            "white": "#f8fafc",
            "gray": "#9ca3af",
            "grey": "#9ca3af",
            "black": "#111827",
        }
        match = re.search(r"color\.([A-Za-z_]+)", value)
        if match:
            return color_map.get(match.group(1).lower())
        hex_match = re.search(r"#[0-9A-Fa-f]{6}", value)
        return hex_match.group(0) if hex_match else None

    def _build_indicator_series(self, bars: list[dict], definitions: list[dict]) -> dict:
        series = {}
        for definition in definitions:
            values = []
            previous = None
            length = max(1, int(definition.get("length", 1)))
            kind = definition.get("kind", "sma")
            source_values = [self._source_value(bar, definition.get("source", "close")) for bar in bars]

            for idx, value in enumerate(source_values):
                point = None
                if value is not None:
                    if kind == "ema":
                        alpha = 2 / (length + 1)
                        previous = value if previous is None else (value * alpha) + (previous * (1 - alpha))
                        point = previous
                    else:
                        window = [v for v in source_values[max(0, idx - length + 1):idx + 1] if v is not None]
                        if len(window) == length:
                            point = sum(window) / length

                if point is None:
                    values.append(None)
                else:
                    values.append({"time": bars[idx].get("time"), "value": round(float(point), 8)})
            series[definition["id"]] = values
        return series

    def _source_value(self, bar: dict, source: str) -> float | None:
        try:
            if source == "hl2":
                return (float(bar["high"]) + float(bar["low"])) / 2
            if source == "hlc3":
                return (float(bar["high"]) + float(bar["low"]) + float(bar["close"])) / 3
            if source == "ohlc4":
                return (float(bar["open"]) + float(bar["high"]) + float(bar["low"]) + float(bar["close"])) / 4
            return float(bar.get(source, bar.get("close")))
        except (TypeError, ValueError, KeyError):
            return None

    def _indicator_setup_payload(self, definitions: list[dict], series: dict, start: int, end: int) -> dict | None:
        if not definitions:
            return None
        return {
            "definitions": definitions,
            "series": {
                definition["id"]: [point for point in series.get(definition["id"], [])[start:end] if point]
                for definition in definitions
            },
        }

    def _indicator_tick_payload(self, definitions: list[dict], series: dict, idx: int) -> dict | None:
        if not definitions:
            return None
        points = {}
        for definition in definitions:
            values = series.get(definition["id"], [])
            if idx < len(values) and values[idx]:
                points[definition["id"]] = values[idx]
        return {"definitions": definitions, "points": points}

    def _estimate_crossover_signals(self, bars: list[dict], definitions: list[dict], series: dict) -> list[dict]:
        """Build estimated BUY/SELL markers from the first two overlay lines."""
        if len(definitions) < 2 or not bars:
            return []

        fast_def, slow_def = definitions[0], definitions[1]
        fast_values = series.get(fast_def["id"], [])
        slow_values = series.get(slow_def["id"], [])
        limit = min(len(bars), len(fast_values), len(slow_values))
        signals = []

        def value_at(values, idx):
            point = values[idx] if idx < len(values) else None
            return point.get("value") if isinstance(point, dict) else None

        for idx in range(1, limit):
            prev_fast = value_at(fast_values, idx - 1)
            prev_slow = value_at(slow_values, idx - 1)
            curr_fast = value_at(fast_values, idx)
            curr_slow = value_at(slow_values, idx)
            if None in (prev_fast, prev_slow, curr_fast, curr_slow):
                continue

            action = None
            if prev_fast <= prev_slow and curr_fast > curr_slow:
                action = "BUY"
            elif prev_fast >= prev_slow and curr_fast < curr_slow:
                action = "SELL"

            if action:
                try:
                    price = float(bars[idx].get("close", 0) or 0)
                except (TypeError, ValueError):
                    price = 0.0
                signals.append({
                    "action": action,
                    "price": price,
                    "time": bars[idx].get("time"),
                    "estimated": True,
                    "source": f"{fast_def.get('title', fast_def['id'])} / {slow_def.get('title', slow_def['id'])} crossover",
                })

        return signals

    def _sse_event(self, event_type: str, data: dict) -> str:
        """Format a Server-Sent Event string."""
        payload = {"type": event_type, **data}
        return f"data: {json.dumps(payload)}\n\n"

    def _extract_price(self, data: dict) -> float | None:
        """Extract the current close price from OHLCV or quote data."""
        if not data or "error" in data:
            return None
        
        # Try various formats the tv CLI might return
        if isinstance(data, dict):
            # Direct close field
            if "close" in data:
                try:
                    return float(data["close"])
                except (ValueError, TypeError):
                    pass
            
            # Nested in last bar
            if "bars" in data and isinstance(data["bars"], list) and data["bars"]:
                last_bar = data["bars"][-1]
                if "close" in last_bar:
                    try:
                        return float(last_bar["close"])
                    except (ValueError, TypeError):
                        pass
            
            # price field
            if "price" in data:
                try:
                    return float(data["price"])
                except (ValueError, TypeError):
                    pass
            
            # last field
            if "last" in data:
                try:
                    return float(data["last"])
                except (ValueError, TypeError):
                    pass
        
        return None

    def _extract_time(self, data: dict, step_data: dict = None) -> str | None:
        """Extract the current bar timestamp."""
        if not data or "error" in data:
            if step_data and isinstance(step_data, dict):
                return step_data.get("time", step_data.get("datetime", None))
            return None
        
        if isinstance(data, dict):
            for key in ("time", "datetime", "date", "timestamp"):
                if key in data:
                    return str(data[key])
            
            if "bars" in data and isinstance(data["bars"], list) and data["bars"]:
                last_bar = data["bars"][-1]
                for key in ("time", "datetime", "date"):
                    if key in last_bar:
                        return str(last_bar[key])
        
        return None
