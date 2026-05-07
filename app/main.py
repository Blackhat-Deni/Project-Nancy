# Import the FastAPI framework to build the web application
from fastapi import FastAPI

# Import the database engine and Base class from the database module
from app.database.db import engine, Base

# Import all table models so SQLAlchemy registers them with Base
from app.models.schemas import Strategy, Trade, Log

# Import MCP tools so Nancy has access to market data and broker on startup
from app.mcp.tradingview import TradingViewMCP
from app.mcp.broker import BrokerMCP

# Create all database tables if they don't already exist
Base.metadata.create_all(bind=engine)

# Initialize MCP tool instances
tradingview = TradingViewMCP()
broker = BrokerMCP()

# Create the FastAPI app instance with a title and version number
app = FastAPI(title="Project Nancy", version="0.1.0")


# Define a health-check endpoint that returns the current status of the agent
@app.get("/health")
def health_check():
    return {
        "status": "online",
        "agent": "Nancy",
        "version": "0.1.0"
    }


# Run the app directly using Uvicorn when this file is executed as a script
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
