# ---------------------------------------------------------------------------
# Project Nancy – FastAPI Application Entry Point
# ---------------------------------------------------------------------------
# This is the main web server file.  FastAPI automatically generates
# interactive API docs at /docs when the server is running.
# ---------------------------------------------------------------------------

# FastAPI is the web framework that handles HTTP requests and routing
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import queue as queue_module
from typing import Any, List, Optional
import json

# Import the database engine and Base class so we can create tables on startup
from app.database.db import engine, Base

# Import all table models so SQLAlchemy registers them with Base before
# create_all() is called – without this, tables would not be created
from app.models.schemas import Strategy, Trade, Log

# Import MCP tool instances so Nancy has access to market data and broker
from app.mcp.tradingview import TradingViewMCP
from app.mcp.broker import BrokerMCP

# Import the backtester's core analysis function
from app.agent.backtester import process_chat
from app.agent.backtest_runner import BacktestRunner
from app.agent.strategy_engine import StrategyEngine
from app.agent import memory

from app.mcp.tradingview_control import TradingViewControl
from app.logger import system_logger

# ---------------------------------------------------------------------------
# Startup: create all database tables if they don't already exist.
# This is idempotent – running it multiple times is safe.
# ---------------------------------------------------------------------------
Base.metadata.create_all(bind=engine)

# ---------------------------------------------------------------------------
# Initialise MCP tool instances.  These are created once at startup and
# reused for the lifetime of the process.
# ---------------------------------------------------------------------------
tradingview = TradingViewMCP()
broker = BrokerMCP()

# Initialize TradingView control instance
tv_control = TradingViewControl()

# ---------------------------------------------------------------------------
# Create the FastAPI application instance
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Project Nancy",
    version="0.1.0",
    description="An AI-powered Pinescript v6 backtesting agent",
)

# Allow the Jetro canvas frame (served from a different origin) to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

system_logger.system("Nancy", "Project Nancy v0.1.0 — server online. All systems nominal.")

@app.get("/dashboard")
def serve_dashboard():
    return FileResponse("app/static/index.html")


# ---------------------------------------------------------------------------
# Request / Response Pydantic models for the /chat endpoint
# ---------------------------------------------------------------------------

class Point(BaseModel):
    # Lightweight Charts can represent time as a unix timestamp, date string,
    # or business-day object depending on interval. Keep this permissive so
    # chart annotations never make ordinary chat requests fail validation.
    time: Any = None
    price: float | int | str | None = None

class Drawing(BaseModel):
    id: int | float | str | None = None
    start: Point | None = None
    end: Point | None = None
    color: str | None = None
    label: str | None = None

class ChatRequest(BaseModel):
    """
    The body of a POST /chat request.
    """
    message: str
    drawings: Optional[List[Drawing]] = None


class BacktestRequest(BaseModel):
    """
    The body of a POST /backtest/run request.
    Can be used to trigger a backtest directly (bypassing Nancy's LLM parsing).
    """
    symbol: str = "EURUSD"
    timeframe: str = "5"
    start_date: str = "2024-01-01"
    max_bars: int = 200
    step_delay: float = 0.3
    strategy: dict = {}
    pine_code: Optional[str] = None


class ChatResponse(BaseModel):
    """
    The shape of a successful POST /chat response.
    """
    type: str
    chat_response: str | None = None
    strategy_name: str | None = None
    summary: str | None = None
    entry_conditions: list | None = None
    exit_conditions: list | None = None
    risk_assessment: str | None = None
    verdict: str | None = None
    reasoning: str | None = None

    # Backtest request fields returned by /chat when Nancy should run/replay a strategy
    symbol: str | None = None
    timeframe: str | None = None
    start_date: str | None = None
    max_bars: int | None = None
    step_delay: float | None = None
    strategy: dict | None = None
    pine_code: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health_check():
    """
    Health check endpoint.
    """
    return {
        "status": "online",
        "agent": "Nancy",
        "version": "0.1.0",
    }


@app.get("/logs/stream")
async def log_stream():
    """
    Server-Sent Events endpoint — streams real-time system log events
    to any connected client (e.g. the Nancy Dashboard).
    Each event is a JSON string with level, component, message, and time.
    """
    listener_q = system_logger.subscribe()

    async def event_generator():
        try:
            while True:
                # Poll the queue in a non-blocking way so we don't starve
                # the event loop while waiting for log events.
                try:
                    payload = listener_q.get_nowait()
                    yield payload
                except queue_module.Empty:
                    # No event yet — yield a keep-alive comment so the
                    # browser connection doesn't time out.
                    yield ": keep-alive\n\n"
                    await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            # Client disconnected — clean up the listener queue
            system_logger.unsubscribe(listener_q)
            raise

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/chat", response_model=ChatResponse)
def chat_with_nancy(request: ChatRequest):
    """
    Process user chat or strategy analysis.
    """
    system_logger.info("API", f"POST /chat — message length: {len(request.message)} chars")
    try:
        # Include drawing context if present
        drawing_context = ""
        if request.drawings:
            drawing_context = "\n\n[USER DRAWINGS ON CHART]:\n"
            for d in request.drawings:
                if not d.start or not d.end:
                    continue
                label = f" [{d.label}]" if d.label else ""
                drawing_context += (
                    f"- Line{label}: from (Time: {d.start.time}, Price: {d.start.price}) "
                    f"to (Time: {d.end.time}, Price: {d.end.price})\n"
                )
        
        full_message = request.message + drawing_context

        # ── Pre-LLM Backtest Intent Detection ─────────────────────────
        # If the user says "backtest this", "run it on the chart", etc.
        # and we have Pinescript code in the conversation history,
        # build the backtest config directly — bypassing the LLM.
        # This avoids context window overflow with the 4096-token limit.
        backtest_keywords = [
            "backtest", "run it", "test it", "run this", "try it",
            "simulate", "replay", "execute", "on the chart",
            "on the lightgraph", "on the graph", "run the strategy",
            "test the strategy", "backtest it", "start the backtest",
        ]
        msg_lower = request.message.lower().strip()

        # Follow-up requests like "show me the replay on the chart" should reuse
        # the last successful backtest instead of asking the LLM to rediscover code.
        if memory.wants_chart_replay(request.message) and memory.get_last_backtest_config():
            replay_config = memory.get_last_backtest_config() or {}
            replay_config.setdefault("type", "backtest_request")
            if not replay_config.get("pine_code"):
                replay_config["pine_code"] = memory.get_last_pine_code()
            replay_config["chat_response"] = memory.explain_latest_backtest(request.message)
            system_logger.info("API", "Chart replay follow-up detected — replaying latest backtest config")
            return replay_config

        if memory.wants_backtest_explanation(request.message) and memory.get_last_backtest_summary():
            system_logger.info("API", "Backtest explanation follow-up detected — answering from runtime memory")
            return {"type": "chat", "chat_response": memory.explain_latest_backtest(request.message)}

        is_backtest_intent = any(kw in msg_lower for kw in backtest_keywords)
        
        if is_backtest_intent:
            from app.agent.backtester import _conversation_history, _extract_backtest_from_pine
            
            # Look for Pinescript code in recent history or current message
            raw_code_source = request.message
            pine_code = None
            
            # Check current message first
            if "//@version=" not in request.message and "strategy(" not in request.message and "indicator(" not in request.message:
                # Check history
                for hist_msg in reversed(_conversation_history):
                    if hist_msg["role"] == "user" and (
                        "//@version=" in hist_msg["content"] or
                        "strategy(" in hist_msg["content"] or
                        "indicator(" in hist_msg["content"]
                    ):
                        raw_code_source = hist_msg["content"]
                        break

                if "//@version=" not in raw_code_source and "strategy(" not in raw_code_source and "indicator(" not in raw_code_source:
                    remembered_pine = memory.get_last_pine_code()
                    if remembered_pine:
                        raw_code_source = remembered_pine
            
            # Extract code from the raw source
            start_idx = -1
            if "//@version=" in raw_code_source:
                start_idx = raw_code_source.find("//@version=")
            elif "strategy(" in raw_code_source:
                start_idx = raw_code_source.find("strategy(")
            elif "indicator(" in raw_code_source:
                start_idx = raw_code_source.find("indicator(")
                
            if start_idx != -1:
                pine_code = raw_code_source[start_idx:]
                
                # Remove trailing English phrases from the end of the code
                for keyword in ["backtest this", "run it", "test it", "try it", "simulate", "on the chart"]:
                    if keyword in pine_code.lower():
                        kw_idx = pine_code.lower().rfind(keyword)
                        pine_code = pine_code[:kw_idx].strip()
                        
                # Fix version if missing or mangled
                if pine_code.startswith("Version="):
                    pine_code = "//@version=" + pine_code[8:]
                elif not pine_code.startswith("//@version"):
                    pine_code = "//@version=6\n" + pine_code
                    
                # TradingView requires the version tag to be on its OWN LINE.
                # If the user pasted `//@version=5 strategy(...)` on one line, we MUST split it.
                if pine_code.startswith("//@version="):
                    first_line_end = pine_code.find('\n')
                    if first_line_end == -1:
                        first_line_end = len(pine_code)
                    first_line = pine_code[:first_line_end]
                    
                    if len(first_line) > 14 and ("strategy(" in first_line or "indicator(" in first_line):
                        # Find the space after the version
                        space_idx = first_line.find(" ")
                        if space_idx != -1 and space_idx < 15:
                            pine_code = first_line[:space_idx] + "\n" + first_line[space_idx:].strip() + pine_code[first_line_end:]

            if pine_code:
                system_logger.info("API", "Backtest intent detected with strategy code — building config directly")
                memory.remember_pine_code(pine_code)
                backtest_config = _extract_backtest_from_pine(pine_code, msg_lower)
                backtest_config["pine_code"] = pine_code
                memory.remember_backtest_config(backtest_config)
                
                # Save to conversation history, but truncate massive scripts to save context tokens
                hist_msg = request.message
                if len(hist_msg) > 500:
                    hist_msg = "[Pine Script omitted from history to save context tokens] " + hist_msg[-100:]
                
                _conversation_history.append({"role": "user", "content": hist_msg})
                _conversation_history.append({"role": "assistant", "content": json.dumps(backtest_config)})
                
                return backtest_config

            remembered_config = memory.get_last_backtest_config()
            if remembered_config:
                remembered_config.setdefault("type", "backtest_request")
                if not remembered_config.get("pine_code"):
                    remembered_config["pine_code"] = memory.get_last_pine_code()
                remembered_config["chat_response"] = memory.explain_latest_backtest(request.message)
                system_logger.info("API", "Backtest intent detected without code — reusing latest backtest config")
                return remembered_config

        # ── Standard LLM Processing ───────────────────────────────────
        # Pass the message to Nancy's core processing function.
        # process_chat() returns either a validated dict on success
        # or an error dict with an "error" key on failure.
        result = process_chat(full_message)

        # If the backtester returned an error dict, surface it as an HTTP 500
        # so the client knows something went wrong internally
        if "error" in result:
            raise HTTPException(
                status_code=500,
                detail={
                    "error": result["error"],
                    "message": result.get("message", "Unknown error"),
                    "raw_output": result.get("raw_output", ""),
                }
            )

        # On success, check if it's a backtest request — route accordingly
        resp_type = result.get("type", "")
        
        if resp_type == "backtest_request":
            # Nancy parsed the user's message as a backtest command.
            # Return the parsed config so the frontend can start the SSE backtest stream.
            system_logger.info("API", "Nancy detected backtest intent — returning parsed config for SSE streaming")
            memory.remember_backtest_config(result)
            return result
        
        return result

    except HTTPException:
        # Re-raise HTTPExceptions directly so FastAPI handles them properly
        raise

    except Exception as e:
        # Catch any other unexpected error and return a clean 500 response
        # rather than leaking a raw Python traceback to the client
        raise HTTPException(
            status_code=500,
            detail={
                "error": "INTERNAL_SERVER_ERROR",
                "message": str(e),
            }
        )

@app.get("/tv/status")
def tradingview_status():
    # Check if TradingView desktop is connected via CDP
    return tv_control.get_status()

@app.get("/tv/state")
def tradingview_state():
    # Get current chart state (symbol, timeframe, studies)
    return tv_control.get_state()

@app.get("/tv/values")
def tradingview_values():
    # Get current indicator values from TradingView's data window
    return tv_control.get_indicator_values()

@app.get("/tv/quote/{symbol}")
def tradingview_quote(symbol: str):
    # Get live OHLCV quote directly from TradingView
    return tv_control.get_quote(symbol)

@app.get("/tv/history/{symbol}")
def tradingview_history(symbol: str, interval: str = "5min", outputsize: int = 200):
    # Get historical candlestick data directly from TradingView Desktop (no API key needed)
    # First switch symbol if it doesn't match the current chart
    result = tv_control.get_chart_bars(count=outputsize)
    if "error" in result:
        return result
    bars = result.get("bars", [])
    if not bars:
        return []
    # Return in reverse chronological order to match the old Twelve Data format
    # that the frontend expects (newest first)
    formatted = []
    for bar in reversed(bars):
        formatted.append({
            "datetime": bar.get("datetime", ""),  # may not exist in TV format
            "open": bar.get("open", 0),
            "high": bar.get("high", 0),
            "low": bar.get("low", 0),
            "close": bar.get("close", 0),
            "volume": bar.get("volume", 0),
            "time": bar.get("time", 0),  # unix timestamp from TV
        })
    return formatted

@app.post("/tv/symbol/{symbol}")
def tradingview_switch(symbol: str):
    # Switch the active TradingView chart to the given symbol
    return tv_control.switch_symbol(symbol)

@app.post("/tv/timeframe/{timeframe}")
def tradingview_timeframe(timeframe: str):
    # Switch the chart timeframe
    return tv_control.set_timeframe(timeframe)

@app.get("/tv/replay/status")
def tradingview_replay_status():
    return tv_control.replay_status()

@app.post("/tv/replay/start")
def tradingview_replay_start(date: str = "2024-01-01"):
    return tv_control.replay_start(date)

@app.post("/tv/replay/step")
def tradingview_replay_step():
    return tv_control.replay_step()

@app.post("/tv/replay/stop")
def tradingview_replay_stop():
    return tv_control.replay_stop()


@app.get("/backtest/stream/{symbol}")
async def backtest_stream(symbol: str, interval: str = "5min", outputsize: int = 200, speed: float = 1.0):
    """
    Stream historical candlestick data to simulate a live backtest (legacy/fallback).
    Uses TradingView Desktop data directly via CDP (no API key needed).
    """
    result = tv_control.get_chart_bars(count=outputsize)
    if not result or "error" in result:
        raise HTTPException(status_code=400, detail="Failed to fetch history from TradingView")
    bars = result.get("bars", [])
    if not bars:
        raise HTTPException(status_code=400, detail="No bar data available from TradingView")
    # Bars from TV are already in chronological order
    chronological_data = [{"datetime": "", "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"], "volume": b.get("volume", 0), "time": b["time"]} for b in bars]
    
    async def event_generator():
        try:
            initial_batch = chronological_data[:20]
            remaining_data = chronological_data[20:]
            
            yield f"data: {json.dumps({'type': 'initial', 'data': initial_batch})}\n\n"
            await asyncio.sleep(1.0)
            
            system_logger.info("Backtest", f"Starting playback for {symbol} ({len(remaining_data)} ticks remaining)")
            
            for candle in remaining_data:
                payload = json.dumps({"type": "tick", "data": candle})
                yield f"data: {payload}\n\n"
                await asyncio.sleep(max(0.1, speed))
                
            system_logger.info("Backtest", "Playback complete")
            yield f"data: {json.dumps({'type': 'complete'})}\n\n"
            
        except asyncio.CancelledError:
            system_logger.warning("Backtest", "Client disconnected, stopping playback")
            raise

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/backtest/replay/latest")
async def backtest_replay_latest(speed: float = 0.3):
    """
    Replay the latest Nancy backtest from runtime memory.
    This powers the chart toolbar button, so it uses the same strategy context
    as the chat-driven backtest instead of the legacy price-only stream.
    """
    remembered_config = memory.get_last_backtest_config()

    async def event_generator():
        if not remembered_config:
            yield f"data: {json.dumps({'type': 'error', 'message': 'No previous Nancy backtest is available yet. Run a strategy from chat first.'})}\n\n"
            return

        config = dict(remembered_config)
        config.setdefault("type", "backtest_request")
        config["step_delay"] = max(0.05, float(speed or config.get("step_delay", 0.3)))
        if not config.get("pine_code"):
            config["pine_code"] = memory.get_last_pine_code()

        system_logger.info("API", f"GET /backtest/replay/latest — replaying {config.get('symbol', 'EURUSD')} latest strategy")
        memory.remember_backtest_config(config)
        runner = BacktestRunner(tv_control)
        async for event in runner.run(config):
            yield event

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/backtest/run")
async def backtest_run(request: BacktestRequest):
    """
    Run a full backtest using TradingView's replay mode.
    Returns an SSE stream of events (setup, step, trade, complete, error).
    
    The frontend POSTs the strategy config (parsed by Nancy's LLM from the user's
    natural language message), and this endpoint orchestrates the entire replay.
    """
    system_logger.info("API", f"POST /backtest/run — {request.symbol} / {request.timeframe}min from {request.start_date}")
    system_logger.info("API", f"Pine code present in request: {request.pine_code is not None}")
    
    runner = BacktestRunner(tv_control)
    
    # Use request.pine_code if sent, otherwise fallback to the remembered script.
    pine_code_to_use = request.pine_code or memory.get_last_pine_code()
    
    backtest_config = {
        "symbol": request.symbol,
        "timeframe": request.timeframe,
        "start_date": request.start_date,
        "max_bars": request.max_bars,
        "step_delay": request.step_delay,
        "strategy": request.strategy,
        "pine_code": pine_code_to_use,
    }
    memory.remember_backtest_config(backtest_config)
    
    return StreamingResponse(
        runner.run(backtest_config),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# MCP Observer endpoints — read-only, consumed by nancy_mcp_server.py
# ---------------------------------------------------------------------------

@app.get("/logs/history")
def logs_history(count: int = 50):
    """
    Return the last `count` log entries as a JSON array.
    Used by the Nancy MCP observer server so Claude Desktop can
    inspect the live system log without an SSE connection.
    """
    return system_logger.get_history(count=count)


@app.get("/system/info")
def system_info():
    """
    Return a comprehensive snapshot of the current runtime state.
    Claude Desktop uses this via the MCP server to understand
    what is loaded, what is connected, and how the system is configured.
    """
    import os
    import pathlib

    project_root = pathlib.Path(__file__).resolve().parents[1]

    # Check if the Llama model is loaded in memory
    from app.agent.backtester import _model_instance
    model_loaded = _model_instance is not None

    # Try to get ChromaDB stats
    chroma_info = {"status": "unknown"}
    try:
        import chromadb
        chroma_path = project_root / "data" / "chromadb"
        client = chromadb.PersistentClient(path=str(chroma_path))
        col = client.get_collection("nancy_strategies")
        chroma_info = {
            "status": "connected",
            "collection": "nancy_strategies",
            "chunk_count": col.count(),
            "path": str(chroma_path),
        }
    except Exception as e:
        chroma_info = {"status": "error", "detail": str(e)}

    # Count active SSE listeners
    active_listeners = len(system_logger._listeners)

    # Read env config (mask secret values)
    env_path = project_root / ".env"
    env_config = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                # Mask anything that looks like a key/token/password
                if any(s in key.upper() for s in ("KEY", "TOKEN", "SECRET", "PASS", "PASSWORD")):
                    env_config[key] = "***masked***"
                else:
                    env_config[key] = val

    return {
        "status": "online",
        "version": "0.1.0",
        "llm": {
            "loaded": model_loaded,
            "model_path": env_config.get("MODEL_PATH", "not set"),
            "context_size": env_config.get("MODEL_CONTEXT_SIZE", "not set"),
            "gpu_layers": env_config.get("MODEL_GPU_LAYERS", "not set"),
        },
        "chromadb": chroma_info,
        "logger": {
            "active_sse_clients": active_listeners,
            "log_history_count": len(system_logger._raw_history),
        },
        "env_config": env_config,
        "project_root": str(project_root),
    }


# ---------------------------------------------------------------------------
# Run the app directly with Uvicorn when executing this file as a script:
#   python app/main.py
# In production, prefer running via:
#   uvicorn app.main:app --host 0.0.0.0 --port 8000
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
