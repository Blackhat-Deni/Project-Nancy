"""
Backtester Agent – The Core Intelligence of Project Nancy
----------------------------------------------------------
This module is Nancy's brain.  It loads a local Llama language model,
wraps it in a carefully engineered system prompt, retrieves relevant
Pinescript documentation from ChromaDB, and uses all of that to produce
a structured, validated analysis of any Pinescript trading strategy.

Design principle: every analysis must be traceable and explainable.
Nancy never guesses – if she cannot understand something, she says so.
"""

import json
from app.logger import system_logger
import os
import pathlib

# ---------------------------------------------------------------------------
# python-dotenv – reads the .env file and injects its values into the
# environment so we can access them with os.getenv().
# ---------------------------------------------------------------------------
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# llama-cpp-python – a Python binding for llama.cpp, which lets us run
# quantized GGUF models locally without needing an external API or GPU
# (though GPU layers can be offloaded if available).
# ---------------------------------------------------------------------------
from llama_cpp import Llama

# ---------------------------------------------------------------------------
# Pydantic – used to define and validate the exact JSON structure we expect
# back from the language model.  If the model returns something that doesn't
# match the schema, Pydantic raises a clear validation error.
# ---------------------------------------------------------------------------
from pydantic import BaseModel, ValidationError

# ---------------------------------------------------------------------------
# Import the retrieval functions from our RAG module so we can pull
# relevant Pinescript documentation before sending the prompt.
# ---------------------------------------------------------------------------
from app.rag.retriever import retrieve, format_context
from app.agent import memory

# ---------------------------------------------------------------------------
# Load environment variables from the .env file at project root
# ---------------------------------------------------------------------------
# resolve() makes the path absolute; parents[2] moves two levels up from
# this file (app/agent/ -> app/ -> project root)
PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# Module-level variable to hold the loaded model instance.
# We use a simple cache here so the model is only loaded once per process –
# loading a 4 GB model file on every request would be far too slow.
# ---------------------------------------------------------------------------
_model_instance: Llama | None = None


# ---------------------------------------------------------------------------
# Pydantic model – defines the exact JSON schema Nancy must return.
# ---------------------------------------------------------------------------

class BacktestStrategy(BaseModel):
    """Structured strategy definition for backtest execution."""
    name: str = "Unnamed Strategy"
    indicators: list[str] = []
    entry_rules: dict = {}    # {"long": [...], "short": [...]}
    exit_rules: list[str] = []
    risk_rules: list[str] = []


class AgentResponse(BaseModel):
    """
    Validates the structured JSON output produced by Nancy.

    The response can be a chat message, a strategy analysis, or a backtest request.
    """

    type: str  # 'chat', 'analysis', or 'backtest_request'

    chat_response: str | None = None

    # Strategy analysis fields
    strategy_name: str | None = None
    summary: str | None = None
    entry_conditions: list[str] | None = None
    exit_conditions: list[str] | None = None
    risk_assessment: str | None = None
    verdict: str | None = None
    reasoning: str | None = None

    # Backtest request fields
    symbol: str | None = None
    timeframe: str | None = None
    start_date: str | None = None
    max_bars: int | None = None
    strategy: BacktestStrategy | None = None


# ---------------------------------------------------------------------------
# System prompt – this is the instruction sheet Nancy reads before every
# analysis.  It defines her identity, thinking process, and output format.
# ---------------------------------------------------------------------------

def get_system_prompt() -> str:
    arch_path = PROJECT_ROOT / "ARCHITECTURE.md"
    arch_content = "Architecture documentation not found."
    if arch_path.exists():
        with open(arch_path, "r", encoding="utf-8") as f:
            arch_content = f.read().strip()

    return f"""You are Nancy, an expert trading assistant and Pinescript v6 backtesting agent.

Your goal is to converse with the user and help them with trading concepts, or analyze Pinescript v6 strategies when explicitly asked. You do not execute trades. You do not give financial advice.

## Your Identity & Architecture
You are an AI agent part of "Project Nancy". Below are the details of your internal technical architecture. You must use this exact information to natively answer any questions the user asks about how you work, what databases you use, or your technical stack. Do NOT tell the user to read a document or refer to a section; summarize the answer yourself naturally using the details below:

{arch_content}

## How You Think

1. Read the user's message carefully.
2. If the user asks about your architecture, stack, or how you work, answer their question conversationally using the details from "Your Identity & Architecture" above. Do not refer them to a document.
3. If it is a general chat or a trading question (e.g. "hi", "how are you", "what is rsi?"), respond normally as a helpful AI assistant.
4. If the user explicitly provides Pinescript code or asks you to analyze a strategy, perform your backtesting analysis step-by-step:
   - Understand the strategy logic.
   - Evaluate entry conditions.
   - Evaluate exit conditions.
   - Assess risk management.
   - Form a verdict (VIABLE or NOT_VIABLE).

## Rules You Must Follow

- Never guess. If something is unclear, say so.
- Never hallucinate Pinescript functions or behaviors — use only what is shown in the code and the provided reference context.
- Never execute or simulate trades — analysis only.

## Output Format

You must ALWAYS respond with exactly ONE of the following JSON structures and nothing else — no preamble, no markdown formatting outside the JSON block.

If it is a general chat or question:
{{
  "type": "chat",
  "chat_response": "Your conversational response here."
}}

If it is a strategy analysis:
{{
  "type": "analysis",
  "strategy_name": "the name from the strategy() call, or 'Unnamed Strategy' if not found",
  "summary": "a plain English paragraph describing what the strategy does",
  "entry_conditions": ["condition 1", "condition 2"],
  "exit_conditions": ["condition 1", "condition 2"],
  "risk_assessment": "a paragraph assessing the risk management of this strategy",
  "verdict": "VIABLE or NOT_VIABLE",
  "reasoning": "a detailed explanation of your verdict, referencing specific parts of the code"
}}

If the user asks to BACKTEST a strategy (e.g. "backtest RSI crossover on EURUSD from January", "run EMA strategy on BTCUSDT 1h"), parse their request into this structure:
{{
  "type": "backtest_request",
  "symbol": "EURUSD",
  "timeframe": "5",
  "start_date": "2024-01-01",
  "max_bars": 200,
  "strategy": {{
    "name": "EMA Crossover 8/21",
    "indicators": ["ema_8", "ema_21"],
    "entry_rules": {{
      "long": ["Price is above EMA(8)", "EMA(8) crosses above EMA(21)"],
      "short": ["Price is below EMA(8)", "EMA(8) crosses below EMA(21)"]
    }},
    "exit_rules": ["Reverse cross of EMA(8) and EMA(21)", "Stop loss at 1% from entry"],
    "risk_rules": ["Risk maximum 1% of portfolio per trade"]
  }}
}}

IMPORTANT for backtest_request:
- Extract the symbol from the user's message. Default to "EURUSD" if not specified.
- Extract timeframe as a number in minutes ("1", "5", "15", "60"). Default to "5" if not specified.
- Extract start_date in YYYY-MM-DD format. Default to "2024-01-01" if not specified.
- Parse their described strategy into clear entry_rules (long/short), exit_rules, and the list of indicators needed.
- max_bars defaults to 200 unless the user specifies a duration.
- If the user previously gave you Pinescript code and now asks to "backtest it" or "run it on the chart", you MUST extract the strategy rules FROM that Pinescript code. Look at the entry conditions, exit conditions, indicators used, and risk management rules in the code, and translate them into the backtest_request JSON format.
- Keywords that indicate a backtest request: "backtest", "run it", "test it on the chart", "run this strategy", "simulate", "replay", "try it", "execute it", "on the lightgraph", "on the chart".
- When the user says things like "backtest this" or "run it on the chart" after providing strategy code, ALWAYS respond with a backtest_request, NOT an analysis or chat response."""


def load_backtester() -> Llama:
    """
    Load the Llama model from disk using the settings in the .env file.

    This function reads three environment variables:
    - MODEL_PATH         : relative path to the .gguf model file
    - MODEL_CONTEXT_SIZE : number of tokens the model can see at once
    - MODEL_GPU_LAYERS   : how many transformer layers to offload to GPU
                           (set to 0 to run entirely on CPU)

    The first call loads the model from disk (this takes a few seconds).
    Subsequent calls return the already-loaded instance immediately,
    thanks to the module-level _model_instance cache.
    """
    global _model_instance

    # Return cached instance if the model has already been loaded
    if _model_instance is not None:
        return _model_instance

    # Read configuration from .env (loaded at module import time above)
    model_path_rel = os.getenv("MODEL_PATH", "models/model.gguf")
    context_size = int(os.getenv("MODEL_CONTEXT_SIZE", "4096"))
    gpu_layers = int(os.getenv("MODEL_GPU_LAYERS", "0"))

    # Resolve the model path relative to the project root
    model_path = str(PROJECT_ROOT / model_path_rel)

    system_logger.system("LLM", f"Loading Llama model from: {model_path}")
    system_logger.system("LLM", f"Context size: {context_size} | GPU layers: {gpu_layers}")

    # Load the GGUF model via llama-cpp-python
    # verbose=False suppresses the low-level C++ logs for cleaner output
    _model_instance = Llama(
        model_path=model_path,
        n_ctx=context_size,       # maximum token context window
        n_gpu_layers=gpu_layers,  # layers to run on GPU (0 = CPU only)
        verbose=False,
    )

    system_logger.system("LLM", "Llama model loaded and ready.")
    return _model_instance


# ---------------------------------------------------------------------------
# Conversation history — allows Nancy to remember previous messages
# ---------------------------------------------------------------------------
_conversation_history: list[dict] = []
MAX_HISTORY_MESSAGES = 10  # Compact rolling chat memory; runtime artifacts live in memory.py
MAX_HISTORY = MAX_HISTORY_MESSAGES


def process_chat(message: str) -> dict:
    """
    The main analysis function.  Takes a user message (chat or code) and returns a
    validated dictionary describing the response.

    Pipeline:
    1. Retrieve relevant Pinescript v6 documentation from ChromaDB using
       the strategy code as the search query (RAG lookup).
    2. Format the retrieved chunks into a clean context block.
    3. Load the model and run inference using chat completion format
       WITH conversation history so Nancy remembers previous messages.
    4. Parse and validate the JSON response with Pydantic.
    5. Return the result as a plain Python dictionary.

    Parameters
    ----------
    message : str
        The user's message or Pinescript strategy code.

    Returns
    -------
    dict
        A validated BacktestResult as a dict on success, or an error
        dict with an "error" key if something went wrong.
    """
    global _conversation_history

    # ------------------------------------------------------------------
    # Step 1: RAG lookup – find relevant Pinescript reference material
    # ------------------------------------------------------------------
    system_logger.info("Agent", f"Message received — routing to RAG pipeline...")
    system_logger.info("RAG", "Querying ChromaDB for relevant Pinescript context...")
    try:
        rag_results = retrieve(query=message, top_k=2)
        context_block = format_context(rag_results)
        # Safety limit: truncate RAG context to ~1000 characters so it doesn't overflow
        if len(context_block) > 1000:
            context_block = context_block[:1000] + "... [context truncated]"
    except Exception as e:
        system_logger.warning("RAG", f"Retrieval failed: {e}. Continuing without context.")
        context_block = "[No Pinescript reference context available.]"

    # ------------------------------------------------------------------
    # Step 3: Load the model and run inference using chat completion format
    # ------------------------------------------------------------------
    # This uses the correct message format that Llama 3.1 was trained on.
    # We pass the system prompt separately from the user instructions,
    # which helps the model stay in character and follow constraints.
    # We also include conversation history so Nancy can remember
    # previously provided strategy code.
    system_logger.info("Agent", "RAG context injected into prompt — dispatching to LLM...")
    model = load_backtester()

    # Build the messages array with conversation history
    messages = [
        {
            "role": "system",
            "content": get_system_prompt()
        }
    ]

    # Add conversation history (last N exchanges)
    for hist in _conversation_history[-MAX_HISTORY:]:
        messages.append(hist)

    # Add the current user message with RAG context and runtime chart/backtest memory.
    runtime_context = memory.build_runtime_context()
    current_user_msg = f"""## Current Nancy Runtime Context
{runtime_context}

## Pinescript v6 Reference Context
The following documentation was retrieved from the knowledge base:
{context_block}

## User Message / Strategy Code
Analyze this user message or strategy code and respond with ONLY a JSON object:
```text
{message}
```"""
    messages.append({"role": "user", "content": current_user_msg})

    total_chars = sum(len(m["content"]) for m in messages)
    system_logger.info("LLM", f"Prompt details: {len(messages)} messages, total {total_chars} chars.")
    for idx, m in enumerate(messages):
        system_logger.info("LLM", f"Msg {idx} ({m['role']}): {len(m['content'])} chars")

    system_logger.info("LLM", f"Prompt received — {len(messages)} messages in context (incl. {len(_conversation_history)} history)")
    try:
        response = model.create_chat_completion(
            messages=messages,
            max_tokens=384,
            temperature=0.1,
        )
    except Exception as e:
        system_logger.error("LLM", f"LLM error: {e}")
        # To avoid breaking the app immediately, we can return a fallback
        raise e

    # Extract the text response from the chat completion result structure
    raw_output = response["choices"][0]["message"]["content"].strip()
    system_logger.info("LLM", f"Inference complete — {len(raw_output)} chars returned.")
    system_logger.info("Agent", "Parsing and validating model output...")

    # ------------------------------------------------------------------
    # Step 4: Parse and validate the JSON response
    # ------------------------------------------------------------------
    try:
        # First, parse the raw string as JSON
        parsed_json = json.loads(raw_output)

        # Then validate it against our Pydantic schema – this ensures all
        # required fields are present and have the right types
        result = AgentResponse(**parsed_json)

        # Return the validated result as a plain dict for easy serialisation
        resp_type = parsed_json.get("type", "unknown")
        system_logger.info("Agent", f"Response validated — type: {resp_type.upper()}. Sending to client.")

        # Save to conversation history so Nancy remembers this exchange
        # Store a condensed version of the user message (skip RAG context)
        hist_msg = message
        if len(hist_msg) > 500:
            hist_msg = "[Pine Script omitted from history to save context tokens] " + hist_msg[-100:]
            
        _conversation_history.append({"role": "user", "content": hist_msg})
        _conversation_history.append({"role": "assistant", "content": raw_output})
        # Trim history if it gets too long
        while len(_conversation_history) > MAX_HISTORY_MESSAGES:
            _conversation_history.pop(0)

        return result.model_dump()

    except json.JSONDecodeError as e:
        system_logger.error("Agent", f"JSON parse failed — model did not return valid JSON: {e}")
        return {
            "error": "JSON_DECODE_ERROR",
            "message": f"Model output was not valid JSON: {e}",
            "raw_output": raw_output,
        }

    except ValidationError as e:
        system_logger.error("Agent", f"Schema validation failed — missing or wrong fields: {e}")
        return {
            "error": "VALIDATION_ERROR",
            "message": f"Model output did not match expected schema: {e}",
            "raw_output": raw_output,
        }

    except Exception as e:
        system_logger.error("Agent", f"Unexpected error: {e}")
        return {
            "error": "UNKNOWN_ERROR",
            "message": str(e),
            "raw_output": raw_output if "raw_output" in locals() else "",
        }

def _extract_backtest_from_pine(pine_code: str, user_message: str) -> dict:
    """
    Extracts backtest configuration directly from Pine Script code using a lightweight LLM call.
    Bypasses RAG and history to save context tokens.
    """
    system_logger.info("Agent", "Extracting backtest config from Pine Script code directly...")
    model = load_backtester()
    
    from datetime import datetime
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    prompt = f"""
    You are an AI trading assistant. Today's date is {today_str}.
    Analyze the following Pine Script strategy and the user's request.
    Extract the entry rules, exit rules, indicators, and risk management parameters.
    Also extract the symbol, timeframe (in minutes, default "5"), start_date (YYYY-MM-DD, default "2024-01-01"), and max_bars (default 200).
    If the user asks for N days of data, calculate the start_date by subtracting N days from {today_str}.
    
    User request: {user_message}
    
    Pine Script:
    ```
    {pine_code}
    ```
    
    Respond ONLY with a JSON object in the following format:
    {{
        "type": "backtest_request",
        "symbol": "EURUSD",
        "timeframe": "5",
        "start_date": "2024-01-01",
        "max_bars": 200,
        "strategy": {{
            "name": "Strategy Name",
            "indicators": ["EMA 20", "RSI 14"],
            "entry_rules": {{"long": ["Buy when close crosses over EMA 20"], "short": []}},
            "exit_rules": ["Sell when close crosses under EMA 20"],
            "risk_rules": ["Stop loss 1%"]
        }}
    }}
    """
    
    response = model.create_chat_completion(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=384,
        temperature=0.1,
    )
    
    raw_output = response["choices"][0]["message"]["content"].strip()
    
    # Remove any markdown code blocks if the LLM adds them
    if raw_output.startswith("```json"):
        raw_output = raw_output[7:]
    if raw_output.startswith("```"):
        raw_output = raw_output[3:]
    if raw_output.endswith("```"):
        raw_output = raw_output[:-3]
    raw_output = raw_output.strip()
    
    try:
        parsed = json.loads(raw_output)
        parsed["type"] = "backtest_request"
        
        # Ensure default fields are present
        parsed.setdefault("symbol", "EURUSD")
        parsed.setdefault("timeframe", "5")
        parsed.setdefault("start_date", "2024-01-01")
        parsed.setdefault("max_bars", 200)
        
        # Ensure strategy fields
        if "strategy" not in parsed:
            parsed["strategy"] = {}
        strategy = parsed["strategy"]
        strategy.setdefault("name", "Extracted Strategy")
        strategy.setdefault("indicators", [])
        if isinstance(strategy.get("entry_rules"), list):
            strategy["entry_rules"] = {"long": strategy.get("entry_rules", []), "short": []}
        strategy.setdefault("entry_rules", {"long": [], "short": []})
        strategy.setdefault("exit_rules", [])
        strategy.setdefault("risk_rules", [])
        
        return parsed
    except Exception as e:
        system_logger.error("Agent", f"Failed to parse extraction output: {e} | Raw Output: {raw_output}")
        return {
            "type": "backtest_request",
            "symbol": "EURUSD",
            "timeframe": "5",
            "start_date": "2024-01-01",
            "max_bars": 200,
            "strategy": {
                "name": "Fallback Strategy",
                "indicators": [],
                "entry_rules": {"long": ["Follow Pinescript Logic"], "short": []},
                "exit_rules": [],
                "risk_rules": []
            }
        }


# ---------------------------------------------------------------------------
# Test block – run this file directly to do a quick end-to-end test:
#   python app/agent/backtester.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # A simple RSI-based strategy to use as the test input
    test_strategy = """//@version=6
strategy("RSI Strategy", overlay=true)
rsiValue = ta.rsi(close, 14)
if rsiValue < 30
    strategy.entry("Long", strategy.long)
if rsiValue > 70
    strategy.close("Long")"""

    print("\n" + "=" * 60)
    print("NANCY BACKTESTER – STRATEGY ANALYSIS TEST")
    print("=" * 60)
    print(f"\nInput Strategy:\n{test_strategy}\n")
    print("=" * 60 + "\n")

    # Run the full analysis pipeline
    result = process_chat(test_strategy)

    # Pretty-print the result dictionary as formatted JSON
    print("\n[RESULT]")
    print(json.dumps(result, indent=2))
