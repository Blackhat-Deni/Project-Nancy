import subprocess
import json
import os
import pathlib
import time
import re

class TradingViewControl:
    """
    A Python wrapper around the tradingview-mcp-jackson CLI tool ('tv').
    This class allows Nancy to programmatically control TradingView Desktop
    via Chrome DevTools Protocol — switching symbols, reading indicators,
    running replay mode, executing trades, and drawing on charts.
    """

    def __init__(self):
        self.project_root = pathlib.Path(__file__).resolve().parents[2]
        self.tv_path = "/home/deni/.nvm/versions/node/v24.14.1/bin/tv"
        self.node_path = "/home/deni/.nvm/versions/node/v24.14.1/bin/node"
        
    def _run_tv_command(self, command: list[str], timeout: int = 10, input_str: str = None) -> dict:
        """
        Helper method to run a 'tv' command via subprocess and parse JSON output.
        Returns parsed JSON dict on success, or an error dict on failure.
        """
        try:
            run_command = command
            if command and command[0] == self.tv_path and os.path.exists(self.node_path):
                run_command = [self.node_path, self.tv_path, *command[1:]]

            env = os.environ.copy()
            node_dir = os.path.dirname(self.node_path)
            env["PATH"] = f"{node_dir}{os.pathsep}{env.get('PATH', '')}"

            result = subprocess.run(
                run_command,
                input=input_str,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=True,
                env=env,
            )
            
            # Try to parse as JSON first
            try:
                parsed = json.loads(result.stdout)
                # If TradingView CLI explicitly returned success: false, treat it as an error
                if isinstance(parsed, dict) and parsed.get("success") is False:
                    # Map the CLI's internal error/message to our error schema
                    return {
                        "error": "CommandFailed",
                        "message": parsed.get("error", parsed.get("message", "Unknown TradingView CLI error"))
                    }
                return parsed
            except json.JSONDecodeError:
                # Some commands return plain text — wrap it
                return {"output": result.stdout.strip(), "status": "ok"}
            
        except subprocess.TimeoutExpired:
            return {"error": "Timeout", "message": f"Command {' '.join(command)} took longer than {timeout} seconds."}
            
        except subprocess.CalledProcessError as e:
            try:
                error_data = json.loads(e.stdout)
                return {"error": "CommandFailed", "details": error_data}
            except json.JSONDecodeError:
                return {"error": "CommandFailed", "message": e.stderr.strip() or e.stdout.strip() or "Unknown error occurred"}
                
        except Exception as e:
            return {"error": "UnexpectedError", "message": str(e)}

    # ──────────────────────────────────────────────────────────────────────
    # Basic Chart Control
    # ──────────────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Check CDP connection to TradingView Desktop."""
        return self._run_tv_command([self.tv_path, "status"])

    def get_state(self) -> dict:
        """Get current chart state — symbol, timeframe, loaded studies."""
        return self._run_tv_command([self.tv_path, "state"])

    def get_quote(self, symbol: str) -> dict:
        """Fetch current OHLCV price quote."""
        return self._run_tv_command([self.tv_path, "quote", symbol])

    def switch_symbol(self, symbol: str) -> dict:
        """Switch the active chart to a different symbol."""
        return self._run_tv_command([self.tv_path, "symbol", symbol], timeout=15)

    def set_timeframe(self, timeframe: str) -> dict:
        """
        Switch the chart timeframe.
        Examples: '1', '5', '15', '60', 'D', 'W', 'M'
        """
        return self._run_tv_command([self.tv_path, "timeframe", timeframe], timeout=10)

    def scroll_to_date(self, date: str) -> dict:
        """
        Force the chart to jump back to a specific date to load older data into memory.
        Args:
            date: Format 'YYYY-MM-DD'
        """
        # The TV CLI 'scroll' command takes the date as an argument or --date flag.
        # We try the standard format.
        return self._run_tv_command([self.tv_path, "scroll", date], timeout=15)

    def get_ohlcv(self) -> dict:
        """Get OHLCV bar data from the current chart view."""
        return self._run_tv_command([self.tv_path, "ohlcv"], timeout=10)

    def get_chart_bars(self, count: int = 200) -> dict:
        """
        Get historical OHLCV bars directly from TradingView Desktop.
        
        Args:
            count: Number of bars to fetch (max 500).
            
        Returns:
            dict with 'bars' list of {time, open, high, low, close, volume} dicts.
        """
        count = min(count, 500)
        return self._run_tv_command([self.tv_path, "ohlcv", "--count", str(count)], timeout=15)

    def take_screenshot(self) -> dict:
        """Take a screenshot of the current chart."""
        screenshots_dir = self.project_root / "data" / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time())
        filename = f"tv_screenshot_{timestamp}.png"
        filepath = str(screenshots_dir / filename)
        command = [self.tv_path, "screenshot", filepath]
        result = self._run_tv_command(command, timeout=10)
        if "error" not in result:
            result["filepath"] = filepath
        return result

    # ──────────────────────────────────────────────────────────────────────
    # Indicator Values — Read live indicator data from TradingView
    # ──────────────────────────────────────────────────────────────────────

    def get_indicator_values(self) -> dict:
        """
        Read current indicator values from TradingView's data window.
        Returns whatever studies are loaded on the chart (RSI, EMA, MACD, etc.)
        along with their current computed values.
        """
        return self._run_tv_command([self.tv_path, "values"], timeout=10)

    # ──────────────────────────────────────────────────────────────────────
    # Replay Mode — Step through historical data bar-by-bar
    # ──────────────────────────────────────────────────────────────────────

    def replay_start(self, date: str) -> dict:
        """
        Start TradingView's replay mode from a specific date.
        
        Args:
            date: Start date in YYYY-MM-DD format (e.g. '2024-12-01')
        """
        return self._run_tv_command([self.tv_path, "replay", "start", "-d", date], timeout=15)

    def replay_step(self) -> dict:
        """Advance one bar in replay mode."""
        return self._run_tv_command([self.tv_path, "replay", "step"], timeout=5)

    def replay_stop(self) -> dict:
        """Stop replay mode and return to real-time."""
        return self._run_tv_command([self.tv_path, "replay", "stop"], timeout=10)

    def replay_status(self) -> dict:
        """Check whether replay mode is currently active."""
        return self._run_tv_command([self.tv_path, "replay", "status"], timeout=5)

    def replay_autoplay(self) -> dict:
        """Toggle autoplay in replay mode."""
        return self._run_tv_command([self.tv_path, "replay", "autoplay"], timeout=5)

    def replay_trade(self, side: str = "buy") -> dict:
        """
        Execute a trade inside replay mode.
        
        Args:
            side: 'buy', 'sell', or 'close'
        """
        return self._run_tv_command([self.tv_path, "replay", "trade"], timeout=5)

    # ──────────────────────────────────────────────────────────────────────
    # Indicator Management — Add/remove studies on the chart
    # ──────────────────────────────────────────────────────────────────────

    def add_indicator(self, name: str) -> dict:
        """
        Add an indicator/study to the chart.
        
        Args:
            name: Indicator name as TradingView knows it (e.g. 'RSI', 'EMA', 'MACD')
        """
        return self._run_tv_command([self.tv_path, "indicator", "add", name], timeout=10)

    def remove_indicator(self, name: str) -> dict:
        """Remove an indicator from the chart."""
        return self._run_tv_command([self.tv_path, "indicator", "remove", name], timeout=10)

    # ──────────────────────────────────────────────────────────────────────
    # Strategy Data — Read Pine Script strategy results from TradingView
    # ──────────────────────────────────────────────────────────────────────

    def get_strategy_performance(self) -> dict:
        """Get strategy performance metrics from a loaded Pine strategy."""
        result = self._run_tv_command([self.tv_path, "data", "strategy"], timeout=10)
        if isinstance(result, dict) and result.get("error"):
            fallback = self.get_strategy_report_summary()
            if fallback.get("total_trades", 0) > 0 or fallback.get("strategy_name"):
                fallback["internal_api_error"] = result.get("error")
                return fallback
        return result

    def get_strategy_report_summary(self) -> dict:
        """Scrape the visible Strategy Report summary when TradingView's internal API is stale."""
        text_result = self._run_tv_command([
            self.tv_path,
            "ui",
            "eval",
            "document.body.innerText",
        ], timeout=10)
        report_text = str(text_result.get("result", "")) if isinstance(text_result, dict) else ""
        if not report_text:
            return {"success": False, "error": "Strategy report text not available", "source": "dom_text"}

        normalized = (
            report_text
            .replace("−", "-")
            .replace("\u202f", "")
            .replace("\xa0", " ")
            .replace(",", "")
        )

        def number_after(label: str, pattern: str = r"[-+]?\d+(?:\.\d+)?"):
            match = re.search(label + r"\s+" + pattern, normalized, re.IGNORECASE)
            if not match:
                return None
            value = match.group(0).split()[-1].replace("%", "")
            try:
                return float(value)
            except ValueError:
                return None

        def int_after(label: str):
            value = number_after(label, r"\d+(?:\.\d+)?")
            return int(value) if value is not None else 0

        strategy_name = None
        name_match = re.search(r"Strategy Report\s+(.+?)\s+\w{3} \d{1,2}, \d{4}", report_text, re.DOTALL)
        if name_match:
            strategy_name = name_match.group(1).strip().splitlines()[0]

        total_trades = int_after("Total trades")
        win_rate = number_after("Profitable trades", r"[-+]?\d+(?:\.\d+)?%") or 0
        max_drawdown_pct = number_after(r"Max equity drawdown\s+[-+]?\d+(?:\.\d+)?\s+USD", r"[-+]?\d+(?:\.\d+)?%") or 0
        return_pct = number_after(r"Total P&L\s+[-+]?\d+(?:\.\d+)?\s+USD", r"[-+]?\d+(?:\.\d+)?%") or 0

        wins = losses = 0
        wins_match = re.search(r"Profitable trades\s+[-+]?\d+(?:\.\d+)?%\s+(\d+)\s*/\s*(\d+)", normalized, re.IGNORECASE)
        if wins_match:
            wins = int(wins_match.group(1))
            total_from_ratio = int(wins_match.group(2))
            if not total_trades:
                total_trades = total_from_ratio
            losses = max(total_trades - wins, 0)

        return {
            "success": True,
            "source": "dom_text",
            "name": strategy_name or "Strategy Report",
            "total_trades": total_trades,
            "winning_trades": wins,
            "losing_trades": losses,
            "win_rate": win_rate,
            "net_profit_pct": return_pct,
            "max_drawdown_pct": max_drawdown_pct,
            "metric_count": 5,
        }

    def get_strategy_trades(self, max_trades: int | None = 5000) -> dict:
        """
        Get official Strategy Tester trade rows when TradingView exposes them.

        The bundled tv CLI caps `data trades` at 20 rows, so Nancy first tries a
        no-cap internal model read, then the CLI endpoint, then a visible
        Strategy Tester UI table scrape. None of these synthesize trades; if all
        fail, the caller can still fall back to estimated chart markers.
        """
        requested = self._bounded_trade_limit(max_trades)
        attempts = []

        internal = self._get_strategy_trades_internal_no_cap(requested)
        attempts.append(self._trade_attempt_summary("internal_api_no_cap", internal))
        internal_trades = self._coerce_trade_list(internal)
        if internal_trades:
            internal["attempts"] = attempts
            return internal

        cli_limit = min(requested, 20)
        cli = self._run_tv_command([self.tv_path, "data", "trades", "-n", str(cli_limit)], timeout=10)
        attempts.append(self._trade_attempt_summary("internal_api_cli", cli))
        cli_trades = self._coerce_trade_list(cli)
        if cli_trades:
            cli["attempts"] = attempts
            cli["source"] = cli.get("source") or "internal_api_cli"
            cli["limited_by_cli"] = requested > cli_limit
            cli["requested_max"] = requested
            return cli

        ui_rows = self.get_strategy_trade_rows_from_ui(requested)
        attempts.append(self._trade_attempt_summary("strategy_tester_ui", ui_rows))
        ui_trades = self._coerce_trade_list(ui_rows)
        if ui_trades:
            ui_rows["attempts"] = attempts
            return ui_rows

        result = internal if isinstance(internal, dict) else {}
        if not result or "error" not in result:
            result = cli if isinstance(cli, dict) else {}
        if not result or "error" not in result:
            result = ui_rows if isinstance(ui_rows, dict) else {}
        result.setdefault("success", False)
        result.setdefault("trades", [])
        result.setdefault("trade_count", 0)
        result.setdefault("source", "unavailable")
        result["attempts"] = attempts
        return result

    def _bounded_trade_limit(self, max_trades: int | None) -> int:
        try:
            return max(1, min(int(max_trades or 5000), 10000))
        except (TypeError, ValueError):
            return 5000

    def _coerce_trade_list(self, result: dict) -> list:
        if not isinstance(result, dict):
            return []
        trades = result.get("trades", [])
        return trades if isinstance(trades, list) else []

    def _trade_attempt_summary(self, name: str, result: dict) -> dict:
        trades = self._coerce_trade_list(result)
        return {
            "name": name,
            "source": result.get("source") if isinstance(result, dict) else None,
            "trade_count": len(trades),
            "error": result.get("error") if isinstance(result, dict) else "No result",
        }

    def _get_strategy_trades_internal_no_cap(self, max_trades: int = 5000) -> dict:
        """Read TradingView's strategy order/trade model directly without the CLI's 20-row cap."""
        limit = self._bounded_trade_limit(max_trades)
        js = rf"""
        (function() {{
          try {{
            var chartApi = window.TradingViewApi && window.TradingViewApi._activeChartWidgetWV && window.TradingViewApi._activeChartWidgetWV.value && window.TradingViewApi._activeChartWidgetWV.value();
            var chart = chartApi && chartApi._chartWidget;
            if (!chart) return {{ success: false, trades: [], source: 'internal_api_no_cap', error: 'Chart widget not found.' }};
            var sources = chart.model().model().dataSources();
            var strat = null;
            for (var i = 0; i < sources.length; i++) {{
              var s = sources[i];
              if (!s || !s.metaInfo) continue;
              var meta = null;
              try {{ meta = s.metaInfo(); }} catch (_) {{ meta = null; }}
              if ((meta && meta.is_price_study === false) && (s.ordersData || s.tradesData || s.reportData || s.performance || s._orders)) {{ strat = s; break; }}
            }}
            if (!strat) return {{ success: false, trades: [], source: 'internal_api_no_cap', error: 'No strategy found on chart.' }};

            function unwrap(value) {{
              try {{ if (value && typeof value.value === 'function') return value.value(); }} catch (_) {{}}
              return value;
            }}
            function callMaybe(fn, owner) {{
              try {{ return typeof fn === 'function' ? fn.call(owner) : fn; }} catch (_) {{ return null; }}
            }}
            function asArray(value, depth) {{
              value = unwrap(value);
              if (!value || depth > 3) return null;
              if (Array.isArray(value)) return value;
              if (typeof value.toArray === 'function') {{ try {{ var arr = value.toArray(); if (Array.isArray(arr)) return arr; }} catch (_) {{}} }}
              if (Array.isArray(value._items)) return value._items;
              if (Array.isArray(value.items)) return value.items;
              if (Array.isArray(value.data)) return value.data;
              if (Array.isArray(value.trades)) return value.trades;
              if (Array.isArray(value.orders)) return value.orders;
              if (typeof value === 'object') {{
                var keys = Object.keys(value);
                for (var k = 0; k < keys.length; k++) {{
                  var found = asArray(value[keys[k]], depth + 1);
                  if (found && found.length) return found;
                }}
              }}
              return null;
            }}
            function primitive(value) {{
              value = unwrap(value);
              var t = typeof value;
              if (value === null || value === undefined || t === 'function' || t === 'object') return undefined;
              return value;
            }}
            function simplify(row) {{
              row = unwrap(row);
              var out = {{}};
              if (!row || typeof row !== 'object') return out;
              var keys = Object.keys(row);
              for (var k = 0; k < keys.length; k++) {{
                var key = keys[k];
                var value = primitive(row[key]);
                if (value !== undefined) out[key] = value;
              }}
              if (out.time === undefined) {{
                var timeKeys = keys.filter(function(key) {{ return /(^|_)(time|timestamp|date|barTime|entryTime|exitTime)($|_)/i.test(key); }});
                for (var ti = 0; ti < timeKeys.length; ti++) {{ var tv = primitive(row[timeKeys[ti]]); if (tv !== undefined) {{ out.time = tv; break; }} }}
              }}
              if (out.price === undefined) {{
                var priceKeys = keys.filter(function(key) {{ return /(price|fillPrice|entryPrice|exitPrice)/i.test(key); }});
                for (var pi = 0; pi < priceKeys.length; pi++) {{ var pv = primitive(row[priceKeys[pi]]); if (pv !== undefined) {{ out.price = pv; break; }} }}
              }}
              if (out.type === undefined) {{
                var typeKeys = keys.filter(function(key) {{ return /(type|side|direction|action|orderType|position)/i.test(key); }});
                for (var yi = 0; yi < typeKeys.length; yi++) {{ var yv = primitive(row[typeKeys[yi]]); if (yv !== undefined) {{ out.type = String(yv); break; }} }}
              }}
              return out;
            }}

            var candidates = [
              callMaybe(strat.ordersData, strat), strat._orders, callMaybe(strat.tradesData, strat), strat.tradesData,
              strat.orders, strat.trades, strat._trades, callMaybe(strat.reportData, strat), callMaybe(strat.performance, strat)
            ];
            var orders = null;
            for (var c = 0; c < candidates.length; c++) {{
              orders = asArray(candidates[c], 0);
              if (orders && orders.length) break;
            }}
            if (!orders || !orders.length) return {{ success: false, trades: [], source: 'internal_api_no_cap', error: 'No strategy order/trade array was exposed by TradingView internals.' }};
            var result = [];
            for (var t = 0; t < Math.min(orders.length, {limit}); t++) {{
              var simple = simplify(orders[t]);
              if (Object.keys(simple).length) result.push(simple);
            }}
            return {{ success: true, source: 'internal_api_no_cap', trade_count: result.length, total_available: orders.length, requested_max: {limit}, trades: result }};
          }} catch (e) {{
            return {{ success: false, trades: [], source: 'internal_api_no_cap', error: e && e.message ? e.message : String(e) }};
          }}
        }})()
        """
        result = self._run_tv_command([self.tv_path, "ui", "eval", js], timeout=15)
        payload = result.get("result") if isinstance(result, dict) and "result" in result else result
        if isinstance(payload, dict):
            return payload
        return {"success": False, "trades": [], "source": "internal_api_no_cap", "error": "Unexpected UI eval result"}

    def get_strategy_trade_rows_from_ui(self, max_trades: int = 5000) -> dict:
        """Scrape visible official rows from the Strategy Tester/List of Trades UI."""
        limit = self._bounded_trade_limit(max_trades)
        self._run_tv_command([self.tv_path, "ui", "panel", "strategy-tester", "open"], timeout=10)
        time.sleep(0.7)
        for label in ("List of trades", "List of Trades", "Trades", "Performance Summary"):
            clicked = self._run_tv_command([self.tv_path, "ui", "click", "-b", "text", "-v", label], timeout=5)
            if isinstance(clicked, dict) and "error" not in clicked:
                time.sleep(0.8)
                break

        payload = self._read_visible_strategy_trade_rows(limit)
        trades = self._parse_strategy_trade_ui_rows(payload.get("rows", []), limit)
        seen = {self._trade_row_key(trade) for trade in trades}

        # TradingView virtualizes long trade lists. If there is a scrollable
        # row container, walk it page by page and collect newly rendered rows.
        for _ in range(60):
            if len(trades) >= limit:
                break
            scroll = self._scroll_strategy_trade_rows()
            if not scroll.get("scrolled"):
                break
            time.sleep(0.25)
            next_payload = self._read_visible_strategy_trade_rows(limit)
            for trade in self._parse_strategy_trade_ui_rows(next_payload.get("rows", []), limit):
                key = self._trade_row_key(trade)
                if key not in seen:
                    seen.add(key)
                    trades.append(trade)
                    if len(trades) >= limit:
                        break

        payload["trades"] = trades
        payload["trade_count"] = len(trades)
        payload["source"] = "strategy_tester_ui"
        payload["scrolled"] = len(trades) > len(self._parse_strategy_trade_ui_rows(payload.get("rows", []), limit))
        if not trades:
            payload.setdefault("error", "No parseable visible Strategy Tester trade rows found.")
        return payload


    def _read_visible_strategy_trade_rows(self, limit: int) -> dict:
        js = rf"""
        (function() {{
          try {{
            var panel = document.querySelector('[data-name="backtesting"]') || document.querySelector('[class*="strategyReport"]') || document.querySelector('[class*="layout__area--bottom"]');
            if (!panel) return {{ success: false, source: 'strategy_tester_ui', trades: [], error: 'Strategy Tester panel not found.' }};
            function visible(el) {{
              if (!el) return false;
              var rect = el.getBoundingClientRect();
              return rect.width > 0 && rect.height > 0 && window.getComputedStyle(el).visibility !== 'hidden';
            }}
            function clean(text) {{ return String(text || '').replace(/\u2212/g, '-').replace(/\u202f/g, ' ').replace(/\xa0/g, ' ').replace(/\s+/g, ' ').trim(); }}
            var selectors = '[role="row"], tr, [data-rowindex], [class*="row"], [class*="Row"]';
            var rawRows = Array.from(panel.querySelectorAll(selectors)).filter(visible).map(function(row) {{
              var cells = Array.from(row.querySelectorAll('[role="cell"], td, th, [class*="cell"], [class*="Cell"]')).filter(visible).map(function(cell) {{ return clean(cell.innerText || cell.textContent); }}).filter(Boolean);
              var text = clean(row.innerText || row.textContent);
              if (cells.length < 2 && text) cells = text.split(/\n+/).map(clean).filter(Boolean);
              return {{ text: text, cells: cells }};
            }}).filter(function(row) {{
              if (!row.text || row.text.length > 500) return false;
              if (/^(strategy tester|performance summary|overview)$/i.test(row.text)) return false;
              return row.cells.length >= 2 || /\d{{4}}-|\b\w{{3}}\s+\d{{1,2}},\s+\d{{4}}/.test(row.text);
            }});
            var panelText = clean(panel.innerText || panel.textContent).slice(0, 4000);
            return {{ success: true, source: 'strategy_tester_ui', raw_row_count: rawRows.length, rows: rawRows.slice(0, {limit}), text_sample: panelText }};
          }} catch (e) {{
            return {{ success: false, source: 'strategy_tester_ui', trades: [], error: e && e.message ? e.message : String(e) }};
          }}
        }})()
        """
        result = self._run_tv_command([self.tv_path, "ui", "eval", js], timeout=15)
        payload = result.get("result") if isinstance(result, dict) and "result" in result else result
        if isinstance(payload, dict):
            return payload
        return {"success": False, "source": "strategy_tester_ui", "trades": [], "rows": [], "error": "Unexpected UI eval result"}

    def _scroll_strategy_trade_rows(self) -> dict:
        js = r"""
        (function() {
          var panel = document.querySelector('[data-name="backtesting"]') || document.querySelector('[class*="strategyReport"]') || document.querySelector('[class*="layout__area--bottom"]');
          if (!panel) return { scrolled: false, error: 'Strategy Tester panel not found.' };
          var candidates = Array.from(panel.querySelectorAll('*')).filter(function(el) {
            return el.scrollHeight > el.clientHeight + 20 && el.clientHeight > 40;
          }).sort(function(a, b) { return (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight); });
          var scroller = candidates[0] || panel;
          var before = scroller.scrollTop || 0;
          var step = Math.max(120, Math.floor((scroller.clientHeight || 300) * 0.85));
          scroller.scrollTop = Math.min(before + step, Math.max(0, scroller.scrollHeight - scroller.clientHeight));
          return { scrolled: (scroller.scrollTop || 0) > before, before: before, after: scroller.scrollTop || 0, max: Math.max(0, scroller.scrollHeight - scroller.clientHeight) };
        })()
        """
        result = self._run_tv_command([self.tv_path, "ui", "eval", js], timeout=5)
        payload = result.get("result") if isinstance(result, dict) and "result" in result else result
        return payload if isinstance(payload, dict) else {"scrolled": False}

    def _trade_row_key(self, trade: dict) -> tuple:
        return (
            str(trade.get("time", "")),
            str(trade.get("action", trade.get("type", ""))),
            str(trade.get("price", "")),
            str(trade.get("profit_pct", "")),
        )

    def _parse_strategy_trade_ui_rows(self, rows: list, max_trades: int) -> list[dict]:
        parsed = []
        for row in rows if isinstance(rows, list) else []:
            if len(parsed) >= max_trades:
                break
            cells = row.get("cells", []) if isinstance(row, dict) else []
            text = row.get("text", "") if isinstance(row, dict) else str(row)
            values = [str(cell).strip() for cell in cells if str(cell).strip()]
            joined = " ".join(values) if values else str(text)
            lowered = joined.lower()
            if not joined or any(header in lowered for header in ("net profit", "total trades", "max drawdown", "profit factor")):
                continue
            if "date/time" in lowered or ("trade" in lowered and "price" in lowered):
                continue

            date_match = re.search(r"\d{4}-\d{1,2}-\d{1,2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?", joined)
            if not date_match:
                date_match = re.search(r"[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}(?:,?\s+\d{1,2}:\d{2}(?::\d{2})?)?", joined)
            if not date_match:
                continue
            time_value = date_match.group(0)

            type_text = next((cell for cell in values if re.search(r"\b(long|short|entry|exit|close|buy|sell)\b", cell, re.IGNORECASE)), "")
            action = "CLOSE" if re.search(r"\b(exit|close)\b", type_text, re.IGNORECASE) else ("BUY" if re.search(r"\b(long|buy)\b", type_text, re.IGNORECASE) else ("SELL" if re.search(r"\b(short|sell)\b", type_text, re.IGNORECASE) else "TRADE"))

            price = None
            date_cell_idx = next((
                idx for idx, cell in enumerate(values)
                if time_value in cell or (len(cell) >= 8 and cell in time_value)
            ), -1)
            candidate_cells = values[date_cell_idx + 1:] if date_cell_idx >= 0 else values
            for cell in candidate_cells:
                if "%" in cell or re.search(r"\b(usd|eur|p&l|profit|drawdown|run-up)\b", cell, re.IGNORECASE):
                    continue
                number = re.search(r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?", cell)
                if number:
                    try:
                        price = float(number.group(0).replace(",", ""))
                        break
                    except ValueError:
                        pass
            if price is None:
                continue

            pct = None
            pct_match = re.search(r"[-+]?\d+(?:\.\d+)?\s*%", joined)
            if pct_match:
                try:
                    pct = float(pct_match.group(0).replace("%", "").strip())
                except ValueError:
                    pct = None

            parsed.append({
                "time": time_value,
                "price": price,
                "type": type_text or action,
                "action": action,
                "profit_pct": pct if pct is not None else 0,
                "source": "strategy_tester_ui",
                "raw": joined[:300],
            })
        return parsed

    def get_strategy_equity(self) -> dict:
        """Get the equity curve from a loaded Pine strategy."""
        return self._run_tv_command([self.tv_path, "data", "equity"], timeout=10)

    # ──────────────────────────────────────────────────────────────────────
    # Drawing Tools — Annotate the chart
    # ──────────────────────────────────────────────────────────────────────

    def draw_list(self) -> dict:
        """List all drawings on the current chart."""
        return self._run_tv_command([self.tv_path, "draw", "list"], timeout=5)

    def draw_clear(self) -> dict:
        """Clear all drawings from the chart."""
        return self._run_tv_command([self.tv_path, "draw", "clear"], timeout=5)

    # ──────────────────────────────────────────────────────────────────────
    # Pine Script Tools
    # ──────────────────────────────────────────────────────────────────────

    def pine_get(self) -> dict:
        """Get the currently loaded Pine Script source code."""
        return self._run_tv_command([self.tv_path, "pine", "get"], timeout=10)

    def open_pine_editor(self) -> dict:
        """Open/focus the Pine Editor bottom panel."""
        return self._run_tv_command([self.tv_path, "ui", "panel", "pine-editor", "open"], timeout=10)

    def pine_new(self) -> dict:
        """Create a new blank Pine Script if the editor has no active script."""
        return self._run_tv_command([self.tv_path, "pine", "new"], timeout=15)

    def pine_set(self, code: str) -> dict:
        """Set/load Pine Script code into TradingView's editor via stdin."""
        return self._run_tv_command([self.tv_path, "pine", "set"], timeout=15, input_str=code)

    def pine_compile(self) -> dict:
        """Compile the current Pine Script in the editor."""
        return self._run_tv_command([self.tv_path, "pine", "compile"], timeout=15)

    # ──────────────────────────────────────────────────────────────────────
    # Streaming — Monitor chart for changes
    # ──────────────────────────────────────────────────────────────────────

    def stream_quote(self) -> dict:
        """Get a single streaming quote snapshot."""
        return self._run_tv_command([self.tv_path, "stream", "quote"], timeout=5)


if __name__ == "__main__":
    print("=" * 50)
    print("TradingView Control - Quick Test")
    print("=" * 50)
    
    tv = TradingViewControl()
    
    print("\n--- Testing get_status() ---")
    status = tv.get_status()
    print(json.dumps(status, indent=2))
    
    print("\n--- Testing get_state() ---")
    state = tv.get_state()
    print(json.dumps(state, indent=2))
    
    print("\n--- Testing get_indicator_values() ---")
    values = tv.get_indicator_values()
    print(json.dumps(values, indent=2))
    
    print("\nTest complete.")

