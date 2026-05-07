# Import the create_engine function to connect to the database
from sqlalchemy import create_engine

# Import sessionmaker to create database sessions for running queries
from sqlalchemy.orm import sessionmaker, declarative_base

# Define the path to the SQLite database file stored in the data folder
DATABASE_URL = "sqlite:///data/nancy.db"

# Create the database engine that manages the connection to the SQLite file
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

# Create a session factory that produces new database sessions when called
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create a Base class that all database table models will inherit from
Base = declarative_base()
