# ---------------------------------------------------------------------------
# Project Nancy – FastAPI Application Entry Point
# ---------------------------------------------------------------------------
# This is the main web server file.  FastAPI automatically generates
# interactive API docs at /docs when the server is running.
# ---------------------------------------------------------------------------

# FastAPI is the web framework that handles HTTP requests and routing
from fastapi import FastAPI, HTTPException

# JSONResponse lets us return custom status codes alongside JSON bodies
from fastapi.responses import JSONResponse

# Pydantic BaseModel is used to define the shape of request/response bodies.
# FastAPI uses these models to validate incoming data and serialise outgoing data.
from pydantic import BaseModel

# Import the database engine and Base class so we can create tables on startup
from app.database.db import engine, Base

# Import all table models so SQLAlchemy registers them with Base before
# create_all() is called – without this, tables would not be created
from app.models.schemas import Strategy, Trade, Log

# Import MCP tool instances so Nancy has access to market data and broker
from app.mcp.tradingview import TradingViewMCP
from app.mcp.broker import BrokerMCP

# Import the backtester's core analysis function
from app.agent.backtester import analyze_strategy

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

# ---------------------------------------------------------------------------
# Create the FastAPI application instance
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Project Nancy",
    version="0.1.0",
    description="An AI-powered Pinescript v6 backtesting agent",
)


# ---------------------------------------------------------------------------
# Request / Response Pydantic models for the /backtest endpoint
# ---------------------------------------------------------------------------

class BacktestRequest(BaseModel):
    """
    The body of a POST /backtest request.

    The caller sends the raw Pinescript v6 code they want Nancy to analyze.
    FastAPI will automatically return a 422 Unprocessable Entity error if
    this field is missing or not a string.
    """
    # The full text of the Pinescript strategy to analyze
    strategy_code: str


class BacktestResponse(BaseModel):
    """
    The shape of a successful POST /backtest response.

    This mirrors the BacktestResult Pydantic model in backtester.py.
    Declaring it here lets FastAPI generate accurate OpenAPI documentation
    for the endpoint at /docs.
    """
    # The strategy name extracted from the strategy() call in the code
    strategy_name: str

    # A plain-English paragraph describing what the strategy does overall
    summary: str

    # A list of conditions that trigger a trade entry
    entry_conditions: list

    # A list of conditions that trigger a trade exit
    exit_conditions: list

    # A narrative assessment of the strategy's risk management
    risk_assessment: str

    # Binary verdict: "VIABLE" or "NOT_VIABLE"
    verdict: str

    # Detailed reasoning that supports the verdict
    reasoning: str


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


@app.post("/backtest", response_model=BacktestResponse)
def backtest_strategy(request: BacktestRequest):
    """
    Analyze a Pinescript v6 trading strategy using Nancy's AI agent.

    Nancy will:
    1. Retrieve relevant Pinescript documentation from ChromaDB (RAG)
    2. Build a structured prompt combining that context + the strategy code
    3. Run the prompt through the local Llama model
    4. Parse and validate the JSON response
    5. Return the structured analysis to the caller

    Request body:
        strategy_code (str): The full text of the Pinescript v6 strategy.

    Returns:
        BacktestResponse: A structured analysis including entry/exit
        conditions, risk assessment, verdict, and reasoning.
    """
    try:
        # Pass the strategy code to Nancy's core analysis function.
        # analyze_strategy() returns either a validated dict on success
        # or an error dict with an "error" key on failure.
        result = analyze_strategy(request.strategy_code)

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


# ---------------------------------------------------------------------------
# Run the app directly with Uvicorn when executing this file as a script:
#   python app/main.py
# In production, prefer running via:
#   uvicorn app.main:app --host 0.0.0.0 --port 8000
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
