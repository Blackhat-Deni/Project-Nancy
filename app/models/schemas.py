# Import Column types and ForeignKey for defining table columns
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey

# Import datetime to auto-set timestamps when rows are created
from datetime import datetime

# Import the Base class that all table models inherit from
from app.database.db import Base


# Strategy table — stores trading strategies that Nancy can use
class Strategy(Base):
    __tablename__ = "strategies"

    # Unique identifier for each strategy, auto incremented
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # Name of the strategy, must be provided and must be unique
    name = Column(String, nullable=False, unique=True)

    # Optional description explaining what the strategy does
    description = Column(String, nullable=True)

    # Timestamp of when the strategy was created, auto set to current time
    created_at = Column(DateTime, default=datetime.utcnow)


# Trade table — stores individual trades executed by a strategy
class Trade(Base):
    __tablename__ = "trades"

    # Unique identifier for each trade, auto incremented
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # Links this trade to a specific strategy by its id
    strategy_id = Column(Integer, ForeignKey("strategies.id"), nullable=False)

    # The currency pair being traded (e.g. EURUSD)
    pair = Column(String, nullable=False)

    # The direction of the trade, either 'buy' or 'sell'
    direction = Column(String, nullable=False)

    # The price at which the trade was entered
    entry_price = Column(Float, nullable=False)

    # The result of the trade, filled in after the trade closes
    outcome = Column(String, nullable=True)

    # Timestamp of when the trade was created, auto set to current time
    created_at = Column(DateTime, default=datetime.utcnow)


# Log table — stores system logs for monitoring and debugging
class Log(Base):
    __tablename__ = "logs"

    # Unique identifier for each log entry, auto incremented
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # Severity level of the log, either 'info', 'warning', or 'error'
    level = Column(String, nullable=False)

    # The log message describing what happened
    message = Column(String, nullable=False)

    # Timestamp of when the log was created, auto set to current time
    created_at = Column(DateTime, default=datetime.utcnow)
