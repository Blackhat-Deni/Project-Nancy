"""
System Logger – Real-Time PubSub Event Logger for Project Nancy
---------------------------------------------------------------
This module provides a central logger that:
  1. Prints all events to the console (for developer visibility).
  2. Pushes all events to all connected SSE clients in real time.
  3. Maintains a short history buffer so newly connected dashboards
     immediately see recent activity instead of a blank log panel.

Usage (from any module in the project):
    from app.logger import system_logger
    system_logger.info("RAG", "Querying ChromaDB for top 5 chunks...")
    system_logger.warning("LLM", "Model returned unexpected token count")
    system_logger.error("Broker", "Connection timeout after 5s")
"""

import json
import queue
import time
import threading
from collections import deque
from typing import Literal


# ---------------------------------------------------------------------------
# Type alias for log levels
# ---------------------------------------------------------------------------
LogLevel = Literal["info", "warning", "error", "system"]

# Max number of log entries to keep in history for late-joining clients
HISTORY_LIMIT = 60


class PubSubLogger:
    """
    A thread-safe publish-subscribe logger that broadcasts structured log
    events to all registered SSE listener queues.
    """

    def __init__(self):
        self._lock = threading.Lock()
        # Active listener queues — one per connected SSE client
        self._listeners: list[queue.Queue] = []
        # Ring buffer of SSE-formatted strings for fast history replay to new clients
        self._history: deque = deque(maxlen=HISTORY_LIMIT)
        # Ring buffer of raw log dicts — used by the /logs/history REST endpoint
        # and consumed by the Nancy MCP observer server
        self._raw_history: deque = deque(maxlen=HISTORY_LIMIT)

    # ------------------------------------------------------------------
    # Subscription management
    # ------------------------------------------------------------------

    def subscribe(self) -> queue.Queue:
        """
        Register a new SSE listener and return its dedicated queue.
        Pre-fill the queue with recent history so the client gets
        context immediately on connect.
        """
        q: queue.Queue = queue.Queue()
        with self._lock:
            # Replay history into the new queue immediately
            for entry in self._history:
                q.put(entry)
            self._listeners.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        """Remove a listener queue when the SSE client disconnects."""
        with self._lock:
            try:
                self._listeners.remove(q)
            except ValueError:
                pass  # Already removed — that's fine

    # ------------------------------------------------------------------
    # Internal publish method
    # ------------------------------------------------------------------

    def _publish(self, level: LogLevel, component: str, message: str) -> None:
        """
        Build a log payload, store it in history, and push it to all
        active listener queues.
        """
        entry = {
            "level": level,
            "component": component,
            "message": message,
            "time": time.strftime("%H:%M:%S"),
            "ts": int(time.time() * 1000),   # ms epoch for frontend ordering
        }

        # SSE payload string — the `data:` prefix is part of the SSE spec
        sse_payload = f"data: {json.dumps(entry)}\n\n"

        # Also emit to console for developer visibility
        icon = {"info": "●", "warning": "▲", "error": "✖", "system": "◈"}.get(level, "●")
        print(f"[{level.upper():<7}] {icon} [{component}] {message}")

        with self._lock:
            # Store raw dict for REST/MCP consumers
            self._raw_history.append(entry)
            # Store SSE string for streaming clients
            self._history.append(sse_payload)
            dead_listeners = []
            for q in self._listeners:
                try:
                    q.put_nowait(sse_payload)
                except queue.Full:
                    dead_listeners.append(q)
            for q in dead_listeners:
                self._listeners.remove(q)

    # ------------------------------------------------------------------
    # Public logging methods
    # ------------------------------------------------------------------

    def info(self, component: str, message: str) -> None:
        """Log an informational message."""
        self._publish("info", component, message)

    def warning(self, component: str, message: str) -> None:
        """Log a warning message."""
        self._publish("warning", component, message)

    def error(self, component: str, message: str) -> None:
        """Log an error message."""
        self._publish("error", component, message)

    def system(self, component: str, message: str) -> None:
        """Log a system-level event (startup, shutdown, etc.)."""
        self._publish("system", component, message)

    def get_history(self, count: int = 50) -> list[dict]:
        """Return the last `count` raw log entries as a list of dicts.
        Safe to call from any thread — acquires the lock briefly."""
        with self._lock:
            entries = list(self._raw_history)
        return entries[-count:]


# ---------------------------------------------------------------------------
# Module-level singleton — import this everywhere instead of creating new
# instances, so all logs go through the same pub-sub bus.
# ---------------------------------------------------------------------------
system_logger = PubSubLogger()
