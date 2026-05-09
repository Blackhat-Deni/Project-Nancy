# TradingView MCP — Real implementation using Twelve Data API
# Twelve Data provides REST endpoints for forex prices, candles, and indicators.
# Docs: https://twelvedata.com/docs

import os
import requests
from dotenv import load_dotenv

# Load environment variables from the .env file in the project root
load_dotenv()


class TradingViewMCP:
    """
    Market data connector that uses the Twelve Data API to fetch live
    forex prices, OHLCV candlesticks, and RSI-based trading signals.
    """

    def __init__(self):
        # Read the Twelve Data API key from the .env file
        self.api_key = os.getenv("TWELVE_DATA_API_KEY")

        # Mark the connection as inactive until we successfully hit the API
        self.connected = False

        # Base URL for all Twelve Data REST endpoints
        self.base_url = "https://api.twelvedata.com"

        if not self.api_key:
            print("[WARNING] TWELVE_DATA_API_KEY not found in environment. "
                  "Make sure your .env file is correctly configured.")

    # ──────────────────────────────────────────────────────────────────────────
    # Helper: convert a compact pair string like "EURUSD" → "EUR/USD"
    # Twelve Data expects the slash-separated format for forex symbols.
    # ──────────────────────────────────────────────────────────────────────────
    def _format_pair(self, pair: str) -> str:
        """Insert a slash after the first three characters if none is present."""
        pair = pair.upper().strip()
        if "/" not in pair and len(pair) == 6:
            return f"{pair[:3]}/{pair[3:]}"
        return pair

    # ──────────────────────────────────────────────────────────────────────────
    # get_price — fetch the latest bid/ask mid-price for a forex pair
    # ──────────────────────────────────────────────────────────────────────────
    def get_price(self, pair: str) -> dict:
        """
        Fetch the current market price for a currency pair.

        Args:
            pair: Pair string such as "EURUSD" or "EUR/USD".

        Returns:
            dict with keys: pair, price (float), status ("ok" | "error"),
            and optionally error_message.
        """
        symbol = self._format_pair(pair)

        try:
            # Hit the /price endpoint — returns a single float price value
            response = requests.get(
                f"{self.base_url}/price",
                params={"symbol": symbol, "apikey": self.api_key},
                timeout=10,
            )
            response.raise_for_status()  # raise an error for 4xx / 5xx responses
            data = response.json()

            # Twelve Data returns {"price": "1.08540"} on success
            # or {"code": 400, "message": "..."} on failure
            if "price" in data:
                self.connected = True
                return {
                    "pair": symbol,
                    "price": float(data["price"]),
                    "status": "ok",
                }
            else:
                # API returned an error payload
                return {
                    "pair": symbol,
                    "price": None,
                    "status": "error",
                    "error_message": data.get("message", "Unknown API error"),
                }

        except requests.exceptions.RequestException as e:
            # Network error, timeout, or non-2xx status
            return {
                "pair": symbol,
                "price": None,
                "status": "error",
                "error_message": str(e),
            }

    # ──────────────────────────────────────────────────────────────────────────
    # get_candles — fetch OHLCV candlestick bars from the time_series endpoint
    # ──────────────────────────────────────────────────────────────────────────
    def get_candles(self, pair: str, interval: str = "5min", outputsize: int = 15) -> list:
        """
        Fetch historical OHLCV candlestick data for a currency pair.

        Args:
            pair:       Pair string such as "EURUSD".
            interval:   Bar size — e.g. "1min", "5min", "15min", "1h", "1day".
            outputsize: Number of bars to return (max 5000 on paid plans).

        Returns:
            List of dicts, each containing: datetime, open, high, low,
            close, volume. Returns an empty list on error and prints the reason.
        """
        symbol = self._format_pair(pair)

        try:
            response = requests.get(
                f"{self.base_url}/time_series",
                params={
                    "symbol": symbol,
                    "interval": interval,
                    "outputsize": outputsize,
                    "apikey": self.api_key,
                },
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()

            # Successful response has a "values" list of OHLCV dicts
            if data.get("status") == "ok" and "values" in data:
                candles = []
                for bar in data["values"]:
                    candles.append({
                        "datetime": bar.get("datetime"),
                        "open":     float(bar.get("open", 0)),
                        "high":     float(bar.get("high", 0)),
                        "low":      float(bar.get("low", 0)),
                        "close":    float(bar.get("close", 0)),
                        "volume":   float(bar.get("volume", 0)),
                    })
                return candles
            else:
                print(f"[get_candles] API error: {data.get('message', 'Unknown error')}")
                return []

        except requests.exceptions.RequestException as e:
            print(f"[get_candles] Request failed: {e}")
            return []

    # ──────────────────────────────────────────────────────────────────────────
    # get_signal — use the 14-period RSI to generate a simple trading signal
    # ──────────────────────────────────────────────────────────────────────────
    def get_signal(self, pair: str) -> dict:
        """
        Derive a BUY / SELL / NEUTRAL signal from the 14-period RSI.

        RSI interpretation used here:
          - RSI < 30  → oversold → BUY signal
          - RSI > 70  → overbought → SELL signal
          - Otherwise → NEUTRAL

        Args:
            pair: Pair string such as "EURUSD".

        Returns:
            dict with keys: pair, rsi (float), signal ("BUY"|"SELL"|"NEUTRAL"),
            status ("ok" | "error"), and optionally error_message.
        """
        symbol = self._format_pair(pair)

        try:
            response = requests.get(
                f"{self.base_url}/rsi",
                params={
                    "symbol": symbol,
                    "interval": "5min",
                    "time_period": 14,   # standard RSI lookback period
                    "apikey": self.api_key,
                },
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()

            # Successful response looks like: {"values": [{"datetime": ..., "rsi": "45.12"}, ...]}
            if data.get("status") == "ok" and "values" in data:
                # Use the most recent RSI value (first element in the list)
                latest_rsi = float(data["values"][0]["rsi"])

                # Determine the signal based on classic overbought/oversold thresholds
                if latest_rsi < 30:
                    signal = "BUY"
                elif latest_rsi > 70:
                    signal = "SELL"
                else:
                    signal = "NEUTRAL"

                return {
                    "pair": symbol,
                    "rsi": latest_rsi,
                    "signal": signal,
                    "status": "ok",
                }
            else:
                return {
                    "pair": symbol,
                    "rsi": None,
                    "signal": None,
                    "status": "error",
                    "error_message": data.get("message", "Unknown API error"),
                }

        except requests.exceptions.RequestException as e:
            return {
                "pair": symbol,
                "rsi": None,
                "signal": None,
                "status": "error",
                "error_message": str(e),
            }


# ──────────────────────────────────────────────────────────────────────────────
# Quick smoke-test — run this file directly to verify your API key works:
#   python app/mcp/tradingview.py
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tv = TradingViewMCP()

    print("=" * 50)
    print("TEST 1 — get_price('EURUSD')")
    price_result = tv.get_price("EURUSD")
    print(price_result)

    print("=" * 50)
    print("TEST 2 — get_candles('EURUSD', interval='5min', outputsize=15)")
    candles = tv.get_candles("EURUSD", interval="5min", outputsize=15)
    if candles:
        print(f"Received {len(candles)} candles. Most recent bar:")
        print(candles[0])
    else:
        print("No candles returned.")

    print("=" * 50)
    print("TEST 3 — get_signal('EURUSD')")
    signal_result = tv.get_signal("EURUSD")
    print(signal_result)
    print("=" * 50)
