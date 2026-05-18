"""
Strategy Engine — Rule Evaluation & Trade Tracking
----------------------------------------------------
This module takes a structured strategy definition (similar to rules.json)
and evaluates entry/exit rules against live indicator values from TradingView.
It also tracks simulated positions, P&L, and trade history during backtests.
"""

import time
from dataclasses import dataclass, field
from typing import Optional
from app.logger import system_logger


@dataclass
class Trade:
    """A single trade record."""
    id: int
    side: str              # 'long' or 'short'
    entry_price: float
    entry_time: str
    exit_price: Optional[float] = None
    exit_time: Optional[str] = None
    pnl: float = 0.0
    pnl_pct: float = 0.0
    status: str = "open"   # 'open' or 'closed'


class StrategyEngine:
    """
    Evaluates strategy rules against indicator values and manages positions.
    
    Usage:
        engine = StrategyEngine(rules)
        action = engine.evaluate(indicator_values)
        if action in ('buy', 'sell'):
            engine.record_entry(action, price, timestamp)
        elif action == 'close':
            engine.record_exit(price, timestamp)
    """

    def __init__(self, rules: dict):
        """
        Args:
            rules: A strategy definition dict with keys:
                - name: str
                - indicators: list[str]
                - entry_rules: { long: [str], short: [str] }
                - exit_rules: [str]
                - risk_rules: [str]
        """
        self.rules = rules
        self.name = rules.get("name", "Unnamed Strategy")
        self.position: Optional[str] = None  # None, 'long', or 'short'
        self.entry_price: Optional[float] = None
        self.trades: list[Trade] = []
        self.equity_curve: list[dict] = []
        self.starting_balance = 10000.0
        self.balance = self.starting_balance
        self.trade_counter = 0
        self.bars_processed = 0

    def evaluate(self, indicator_values: dict, price: float = 0.0) -> str:
        """
        Evaluate the current indicator values against the strategy rules.
        
        This uses a keyword-matching approach: it scans the entry/exit rule
        descriptions for indicator names (like 'RSI', 'EMA', 'VWAP') and
        checks if the corresponding indicator value satisfies the condition
        (e.g., RSI < 30, EMA crossover, price above VWAP).
        
        Args:
            indicator_values: Dict of indicator name -> current value(s)
                              as returned by tv values
            price: Current bar close price
            
        Returns:
            One of: 'buy', 'sell', 'close', 'hold'
        """
        self.bars_processed += 1
        
        entry_rules = self.rules.get("entry_rules", {})
        exit_rules = self.rules.get("exit_rules", [])
        
        # If we have a position, check exit conditions first
        if self.position is not None:
            should_exit = self._check_exit_conditions(indicator_values, exit_rules, price)
            if should_exit:
                return "close"
        
        # If no position, check entry conditions
        if self.position is None:
            # Check long entry
            long_rules = entry_rules.get("long", [])
            if long_rules and self._check_entry_conditions(indicator_values, long_rules, "long", price):
                return "buy"
            
            # Check short entry
            short_rules = entry_rules.get("short", [])
            if short_rules and self._check_entry_conditions(indicator_values, short_rules, "short", price):
                return "sell"
        
        return "hold"

    def _check_entry_conditions(self, values: dict, rules: list, side: str, price: float) -> bool:
        """
        Check if ALL entry conditions for a given side are met.
        Uses keyword matching against indicator values.
        """
        if not values or not rules:
            return False
        
        conditions_met = 0
        total_conditions = len(rules)
        
        for rule in rules:
            rule_lower = rule.lower()
            
            # Try to match the rule against known indicator patterns
            if self._match_rule(rule_lower, values, price, side):
                conditions_met += 1
        
        # All conditions must pass
        return conditions_met == total_conditions

    def _check_exit_conditions(self, values: dict, rules: list, price: float) -> bool:
        """Check if ANY exit condition is met."""
        if not rules:
            # Default exit: simple trailing stop at 1%
            if self.position == "long" and self.entry_price:
                return price < self.entry_price * 0.99
            elif self.position == "short" and self.entry_price:
                return price > self.entry_price * 1.01
            return False
        
        for rule in rules:
            rule_lower = rule.lower()
            if self._match_rule(rule_lower, values, price, self.position):
                return True
        
        return False

    def _match_rule(self, rule: str, values: dict, price: float, side: str) -> bool:
        """
        Attempt to evaluate a natural-language rule against indicator values.
        
        This is a best-effort keyword matcher. It looks for indicator names
        in the rule text and checks their values against thresholds.
        """
        # Flatten indicator values into a simple dict for easy lookup
        flat = self._flatten_values(values)
        
        # RSI-based rules
        if "rsi" in rule:
            rsi_val = self._find_indicator(flat, "rsi")
            if rsi_val is not None:
                if "below 30" in rule or "< 30" in rule or "under 30" in rule:
                    return rsi_val < 30
                elif "above 70" in rule or "> 70" in rule or "over 70" in rule:
                    return rsi_val > 70
                elif "above 50" in rule or "> 50" in rule:
                    return rsi_val > 50
                elif "below 50" in rule or "< 50" in rule:
                    return rsi_val < 50
                elif "crosses" in rule and "above" in rule:
                    return rsi_val > 50  # Simplified cross detection
                elif "crosses" in rule and "below" in rule:
                    return rsi_val < 50
        
        # EMA / MA based rules (price above/below)
        if "ema" in rule or "moving average" in rule or "ma(" in rule:
            ema_val = self._find_indicator(flat, "ema")
            if ema_val is None:
                ema_val = self._find_indicator(flat, "ma")
            if ema_val is not None:
                if "above" in rule or "over" in rule:
                    return price > ema_val
                elif "below" in rule or "under" in rule:
                    return price < ema_val
                elif "cross" in rule:
                    # Simplified: just check relative position
                    if side == "long":
                        return price > ema_val
                    else:
                        return price < ema_val
        
        # VWAP based rules
        if "vwap" in rule:
            vwap_val = self._find_indicator(flat, "vwap")
            if vwap_val is not None:
                if "above" in rule or "over" in rule:
                    return price > vwap_val
                elif "below" in rule or "under" in rule:
                    return price < vwap_val
        
        # MACD based rules
        if "macd" in rule:
            macd_val = self._find_indicator(flat, "macd")
            if macd_val is not None:
                if "above" in rule or "positive" in rule or "bullish" in rule:
                    return macd_val > 0
                elif "below" in rule or "negative" in rule or "bearish" in rule:
                    return macd_val < 0
        
        # If we can't parse the rule, assume it passes (permissive)
        # This prevents unknown rules from blocking all trades
        system_logger.warning("Strategy", f"Could not parse rule: '{rule}' — assuming PASS")
        return True

    def _flatten_values(self, values: dict) -> dict:
        """Flatten nested indicator values into {name_lower: float_value}."""
        flat = {}
        if isinstance(values, dict):
            for key, val in values.items():
                key_lower = key.lower().strip()
                if isinstance(val, (int, float)):
                    flat[key_lower] = float(val)
                elif isinstance(val, str):
                    try:
                        flat[key_lower] = float(val)
                    except ValueError:
                        pass
                elif isinstance(val, dict):
                    # Nested indicator with sub-values
                    for sub_key, sub_val in val.items():
                        combined = f"{key_lower}_{sub_key.lower().strip()}"
                        if isinstance(sub_val, (int, float)):
                            flat[combined] = float(sub_val)
                        elif isinstance(sub_val, str):
                            try:
                                flat[combined] = float(sub_val)
                            except ValueError:
                                pass
                elif isinstance(val, list) and len(val) > 0:
                    # Take the first value if it's a list
                    first = val[0]
                    if isinstance(first, (int, float)):
                        flat[key_lower] = float(first)
                    elif isinstance(first, dict):
                        for sub_key, sub_val in first.items():
                            combined = f"{key_lower}_{sub_key.lower().strip()}"
                            if isinstance(sub_val, (int, float)):
                                flat[combined] = float(sub_val)
        return flat

    def _find_indicator(self, flat: dict, name: str) -> Optional[float]:
        """Find an indicator value by partial name match."""
        name_lower = name.lower()
        # Exact match first
        if name_lower in flat:
            return flat[name_lower]
        # Partial match
        for key, val in flat.items():
            if name_lower in key:
                return val
        return None

    def record_entry(self, side: str, price: float, timestamp: str):
        """Record a new trade entry."""
        self.trade_counter += 1
        self.position = "long" if side == "buy" else "short"
        self.entry_price = price
        
        trade = Trade(
            id=self.trade_counter,
            side=self.position,
            entry_price=price,
            entry_time=timestamp,
        )
        self.trades.append(trade)
        system_logger.info("Strategy", f"ENTRY #{self.trade_counter}: {self.position.upper()} @ {price} [{timestamp}]")

    def record_exit(self, price: float, timestamp: str):
        """Record a trade exit and compute P&L."""
        if not self.trades or self.position is None:
            return
        
        trade = self.trades[-1]
        trade.exit_price = price
        trade.exit_time = timestamp
        trade.status = "closed"
        
        # Calculate P&L
        if trade.side == "long":
            trade.pnl = price - trade.entry_price
            trade.pnl_pct = (trade.pnl / trade.entry_price) * 100
        else:
            trade.pnl = trade.entry_price - price
            trade.pnl_pct = (trade.pnl / trade.entry_price) * 100
        
        # Update balance
        position_size = self.balance * 0.01  # 1% risk per trade
        self.balance += position_size * (trade.pnl_pct / 100)
        
        system_logger.info("Strategy", 
            f"EXIT  #{trade.id}: {trade.side.upper()} @ {price} | "
            f"P&L: {trade.pnl:+.5f} ({trade.pnl_pct:+.2f}%) [{timestamp}]"
        )
        
        self.position = None
        self.entry_price = None

    def record_equity(self, timestamp: str, price: float):
        """Record a point on the equity curve."""
        unrealized = 0.0
        if self.position and self.entry_price:
            if self.position == "long":
                unrealized = (price - self.entry_price) / self.entry_price * 100
            else:
                unrealized = (self.entry_price - price) / self.entry_price * 100
        
        self.equity_curve.append({
            "time": timestamp,
            "balance": self.balance,
            "unrealized_pnl_pct": unrealized,
        })

    def get_summary(self) -> dict:
        """
        Compile a complete backtest summary with statistics.
        
        Returns:
            Dict with strategy name, total trades, win rate, P&L, etc.
        """
        closed_trades = [t for t in self.trades if t.status == "closed"]
        winning = [t for t in closed_trades if t.pnl > 0]
        losing = [t for t in closed_trades if t.pnl < 0]
        
        total_pnl = sum(t.pnl for t in closed_trades)
        total_pnl_pct = sum(t.pnl_pct for t in closed_trades)
        win_rate = (len(winning) / len(closed_trades) * 100) if closed_trades else 0
        
        avg_win = (sum(t.pnl_pct for t in winning) / len(winning)) if winning else 0
        avg_loss = (sum(t.pnl_pct for t in losing) / len(losing)) if losing else 0
        
        max_drawdown = 0.0
        peak_balance = self.starting_balance
        for eq in self.equity_curve:
            if eq["balance"] > peak_balance:
                peak_balance = eq["balance"]
            dd = (peak_balance - eq["balance"]) / peak_balance * 100
            if dd > max_drawdown:
                max_drawdown = dd
        
        return {
            "strategy_name": self.name,
            "bars_processed": self.bars_processed,
            "total_trades": len(closed_trades),
            "open_trades": len([t for t in self.trades if t.status == "open"]),
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "win_rate": round(win_rate, 1),
            "total_pnl_pct": round(total_pnl_pct, 2),
            "avg_win_pct": round(avg_win, 2),
            "avg_loss_pct": round(avg_loss, 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "final_balance": round(self.balance, 2),
            "starting_balance": self.starting_balance,
            "return_pct": round((self.balance - self.starting_balance) / self.starting_balance * 100, 2),
            "trades": [
                {
                    "id": t.id,
                    "side": t.side,
                    "entry_price": t.entry_price,
                    "entry_time": t.entry_time,
                    "exit_price": t.exit_price,
                    "exit_time": t.exit_time,
                    "pnl": round(t.pnl, 5),
                    "pnl_pct": round(t.pnl_pct, 2),
                    "status": t.status,
                }
                for t in self.trades
            ],
        }
