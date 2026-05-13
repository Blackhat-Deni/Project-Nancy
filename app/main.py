# ---------------------------------------------------------------------------
# Project Nancy – FastAPI Application Entry Point
# ---------------------------------------------------------------------------
# This is the main web server file.  FastAPI automatically generates
# interactive API docs at /docs when the server is running.
# ---------------------------------------------------------------------------

# FastAPI is the web framework that handles HTTP requests and routing
from fastapi import FastAPI, HTTPException

# JSONResponse lets us return custom status codes alongside JSON bodies
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

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
from app.mcp.tradingview_control import TradingViewControl

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

app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/dashboard")
def serve_dashboard():
    return FileResponse("app/static/index.html")


# ---------------------------------------------------------------------------
# Request / Response Pydantic models for the /chat endpoint
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    """
    The body of a POST /chat request.
    """
    message: str


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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health_check():
    """
    Health check endpoint.

    Returns a simple status object so load balancers, monitoring tools,
    and developers can confirm the server is up and running.
    """
    return {
        "status": "online",
        "agent": "Nancy",
        "version": "0.1.0",
    }


@app.post("/chat", response_model=ChatResponse)
def chat_with_nancy(request: ChatRequest):
    """
    Process user chat or strategy analysis.
    """
    try:
        # Pass the message to Nancy's core processing function.
        # process_chat() returns either a validated dict on success
        # or an error dict with an "error" key on failure.
        result = process_chat(request.message)

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

        # On success, return the analysis dict – FastAPI will validate it
        # against BacktestResponse and serialise it as JSON automatically
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

@app.get("/tv/quote/{symbol}")
def tradingview_quote(symbol: str):
    # Get live OHLCV quote directly from TradingView
    return tv_control.get_quote(symbol)

@app.get("/tv/history/{symbol}")
def tradingview_history(symbol: str, interval: str = "5min", outputsize: int = 200):
    # Get historical candlestick data from Twelve Data via MCP
    return tradingview.get_candles(symbol, interval=interval, outputsize=outputsize)

@app.post("/tv/symbol/{symbol}")
def tradingview_switch(symbol: str):
    # Switch the active TradingView chart to the given symbol
    return tv_control.switch_symbol(symbol)


# ---------------------------------------------------------------------------
# Run the app directly with Uvicorn when executing this file as a script:
#   python app/main.py
# In production, prefer running via:
#   uvicorn app.main:app --host 0.0.0.0 --port 8000
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
