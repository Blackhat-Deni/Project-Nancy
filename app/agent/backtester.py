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

class BacktestResult(BaseModel):
    """
    Validates the structured JSON output produced by Nancy.

    Every field is required – if the model omits any of them, Pydantic
    will raise a ValidationError, which we catch and turn into an error
    dictionary so the caller always gets a predictable response shape.
    """

    # The name of the strategy as understood by the model
    strategy_name: str

    # A plain-English paragraph describing what the strategy does overall
    summary: str

    # A list of conditions that trigger a trade entry (e.g. "RSI < 30")
    entry_conditions: list[str]

    # A list of conditions that trigger a trade exit (e.g. "RSI > 70")
    exit_conditions: list[str]

    # A narrative assessment of the strategy's risk profile
    risk_assessment: str

    # Binary verdict – must be exactly "VIABLE" or "NOT_VIABLE"
    verdict: str

    # Detailed step-by-step reasoning that supports the verdict
    reasoning: str


# ---------------------------------------------------------------------------
# System prompt – this is the instruction sheet Nancy reads before every
# analysis.  It defines her identity, thinking process, and output format.
# ---------------------------------------------------------------------------

BACKTESTER_SYSTEM_PROMPT = """You are Nancy, an expert Pinescript v6 backtesting agent.

Your sole purpose is to analyze trading strategies written in Pinescript v6 and produce a clear, structured evaluation. You do not execute trades. You do not give financial advice. You only analyze code.

## How You Think (follow this order every time)

1. **Understand the strategy logic** – Read the entire script carefully. Identify what indicators or calculations are used and what they measure.
2. **Evaluate entry conditions** – Identify every condition that causes the strategy to open a position. Think about when in the market cycle these would trigger.
3. **Evaluate exit conditions** – Identify every condition that causes the strategy to close a position. Consider whether exits are well-defined or open-ended.
4. **Assess risk management** – Look for stop-losses, position sizing, drawdown limits, or any other risk controls. If none are present, say so explicitly.
5. **Form a verdict** – Based on the above, decide if the strategy is VIABLE (logically sound and testable) or NOT_VIABLE (has logical errors, missing conditions, or is too incomplete to test).

## Rules You Must Follow

- Always think step by step in the order above.
- Never guess. If something is unclear or missing from the code, say so in the `reasoning` field.
- Never hallucinate Pinescript functions or behaviors — use only what is shown in the code and the provided reference context.
- Never execute or simulate trades — analysis only.
- If the input is not valid Pinescript, set verdict to NOT_VIABLE and explain why in reasoning.

## Output Format

You must ALWAYS respond with this exact JSON structure and nothing else — no preamble, no explanation outside the JSON:

{
  "strategy_name": "the name from the strategy() call, or 'Unnamed Strategy' if not found",
  "summary": "a plain English paragraph describing what the strategy does",
  "entry_conditions": ["condition 1", "condition 2"],
  "exit_conditions": ["condition 1", "condition 2"],
  "risk_assessment": "a paragraph assessing the risk management of this strategy",
  "verdict": "VIABLE or NOT_VIABLE",
  "reasoning": "a detailed explanation of your verdict, referencing specific parts of the code"
}"""


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

    print(f"[INFO] Loading Llama model from: {model_path}")
    print(f"[INFO] Context size: {context_size} | GPU layers: {gpu_layers}")

    # Load the GGUF model via llama-cpp-python
    # verbose=False suppresses the low-level C++ logs for cleaner output
    _model_instance = Llama(
        model_path=model_path,
        n_ctx=context_size,       # maximum token context window
        n_gpu_layers=gpu_layers,  # layers to run on GPU (0 = CPU only)
        verbose=False,
    )

    print("[INFO] Llama model loaded successfully.")
    return _model_instance


def analyze_strategy(strategy_code: str) -> dict:
    """
    The main analysis function.  Takes raw Pinescript code and returns a
    validated dictionary describing the strategy.

    Pipeline:
    1. Retrieve relevant Pinescript v6 documentation from ChromaDB using
       the strategy code as the search query (RAG lookup).
    2. Format the retrieved chunks into a clean context block.
    3. Load the model and run inference using chat completion format.
    4. Parse and validate the JSON response with Pydantic.
    5. Return the result as a plain Python dictionary.

    Parameters
    ----------
    strategy_code : str
        The full text of a Pinescript v6 strategy.

    Returns
    -------
    dict
        A validated BacktestResult as a dict on success, or an error
        dict with an "error" key if something went wrong.
    """

    # ------------------------------------------------------------------
    # Step 1: RAG lookup – find relevant Pinescript reference material
    # ------------------------------------------------------------------
    print("[INFO] Retrieving relevant Pinescript context from ChromaDB...")
    try:
        rag_results = retrieve(query=strategy_code, top_k=5)
        context_block = format_context(rag_results)
    except Exception as e:
        print(f"[WARNING] RAG retrieval failed: {e}. Continuing without context.")
        context_block = "[No Pinescript reference context available.]"

    # ------------------------------------------------------------------
    # Step 3: Load the model and run inference using chat completion format
    # ------------------------------------------------------------------
    # This uses the correct message format that Llama 3.1 was trained on.
    # We pass the system prompt separately from the user instructions,
    # which helps the model stay in character and follow constraints.
    model = load_backtester()

    print("[INFO] Sending prompt to Llama model for analysis...")
    response = model.create_chat_completion(
        messages=[
            {
                "role": "system",
                "content": BACKTESTER_SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": f"""## Pinescript v6 Reference Context
The following documentation was retrieved from the knowledge base:
{context_block}

## Strategy Code to Analyze
Analyze this Pinescript v6 strategy and respond with ONLY a JSON object:
````pinescript
{strategy_code}
```"""
            }
        ],
        max_tokens=1024,
        temperature=0.1,
    )

    # Extract the text response from the chat completion result structure
    raw_output = response["choices"][0]["message"]["content"].strip()
    print(f"[INFO] Raw model output:\n{raw_output}")

    # ------------------------------------------------------------------
    # Step 4: Parse and validate the JSON response
    # ------------------------------------------------------------------
    try:
        # First, parse the raw string as JSON
        parsed_json = json.loads(raw_output)

        # Then validate it against our Pydantic schema – this ensures all
        # required fields are present and have the right types
        result = BacktestResult(**parsed_json)

        # Return the validated result as a plain dict for easy serialisation
        return result.model_dump()

    except json.JSONDecodeError as e:
        # The model produced text that isn't valid JSON at all
        return {
            "error": "JSON_DECODE_ERROR",
            "message": f"Model output was not valid JSON: {e}",
            "raw_output": raw_output,
        }

    except ValidationError as e:
        # The model produced valid JSON but it didn't match our schema
        # (e.g. a required field was missing or had the wrong type)
        return {
            "error": "VALIDATION_ERROR",
            "message": f"Model output did not match expected schema: {e}",
            "raw_output": raw_output,
        }

    except Exception as e:
        # Catch-all for any other unexpected error
        return {
            "error": "UNKNOWN_ERROR",
            "message": str(e),
            "raw_output": raw_output if "raw_output" in locals() else "",
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
    result = analyze_strategy(test_strategy)

    # Pretty-print the result dictionary as formatted JSON
    print("\n[RESULT]")
    print(json.dumps(result, indent=2))
