"""
RAG Retrieval Module for Project Nancy
---------------------------------------
This module handles the "search" side of the RAG pipeline.  Given a
plain-English question, it converts the question into an embedding,
searches ChromaDB for the most semantically similar document chunks,
and returns them in a format ready to be injected into a language model
prompt as context.
"""

import pathlib

# ---------------------------------------------------------------------------
# SentenceTransformer – we use the same model that was used during ingestion
# so that query embeddings live in the same vector space as the stored
# document embeddings.  If you change the model here, you must also change
# it in ingestion.py and re-ingest all documents.
# ---------------------------------------------------------------------------
from sentence_transformers import SentenceTransformer

# ---------------------------------------------------------------------------
# ChromaDB – we open the same persistent database that the ingestion
# pipeline wrote to, so we can search the chunks that were stored there.
# ---------------------------------------------------------------------------
import chromadb

# ---------------------------------------------------------------------------
# Path configuration – must match what ingestion.py uses so we point at
# the same database on disk.
# ---------------------------------------------------------------------------
PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
CHROMADB_DIR = PROJECT_ROOT / "data" / "chromadb"

# ---------------------------------------------------------------------------
# Embedding model name – must be identical to the one used in ingestion.py
# so that queries and documents are encoded in the same vector space.
# ---------------------------------------------------------------------------
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"


def get_retriever():
    """
    Load the ChromaDB collection and the embedding model, then return
    both as a tuple: (collection, model).

    This is the setup step – call it once at startup and reuse the
    returned objects for every query so you don't reload the model or
    reconnect to the database on every search.
    """

    # Connect to the persisted ChromaDB database on disk
    # This is the same database that ingestion.py writes to
    client = chromadb.PersistentClient(path=str(CHROMADB_DIR))

    # Open the nancy_strategies collection (it must already exist from
    # a previous ingestion run – if it doesn't, this will raise an error)
    collection = client.get_collection(name="nancy_strategies")
    print(f"[INFO] Connected to ChromaDB collection 'nancy_strategies' ({collection.count()} chunks)")

    # Load the same embedding model used during ingestion so that query
    # vectors are directly comparable to document vectors
    print(f"[INFO] Loading embedding model: {EMBEDDING_MODEL_NAME}")
    model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    print("[INFO] Embedding model loaded successfully.")

    return collection, model


def retrieve(query: str, top_k: int = 5) -> list[dict]:
    """
    Search the vector database for the chunks most relevant to a query.

    Parameters
    ----------
    query : str
        A plain-English question or phrase, e.g.
        "how does RSI work in Pinescript"
    top_k : int
        How many results to return (default 5).  A higher number gives
        more context but also adds more tokens to the prompt.

    Returns
    -------
    list[dict]
        A list of dictionaries, one per result, each containing:
        - "text"   : the original chunk text
        - "source" : the filename the chunk came from
        - "score"  : the distance score (lower = more relevant)
    """

    # Step 1: Load the retriever (collection + model)
    # In a production app you would cache these instead of reloading
    # every time, but this keeps the function self-contained for now.
    collection, model = get_retriever()

    # Step 2: Convert the query string into an embedding vector
    # This produces a 384-dimensional float vector that captures the
    # meaning of the query, just like we did for document chunks during
    # ingestion.
    print(f"[INFO] Encoding query: \"{query}\"")
    query_embedding = model.encode([query]).tolist()

    # Step 3: Ask ChromaDB to find the closest chunk embeddings
    # ChromaDB uses cosine distance by default – lower distance means
    # the chunk's meaning is closer to the query's meaning.
    print(f"[INFO] Searching for top {top_k} relevant chunks...")
    results = collection.query(
        query_embeddings=query_embedding,
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    # Step 4: Unpack the ChromaDB results into a clean list of dicts
    # ChromaDB returns nested lists (one list per query), so we index
    # into [0] because we only sent a single query.
    documents = results["documents"][0]
    metadatas = results["metadatas"][0]
    distances = results["distances"][0]

    output = []
    for text, meta, dist in zip(documents, metadatas, distances):
        output.append({
            "text": text,
            "source": meta.get("source_file", "unknown"),
            "score": round(dist, 4),
        })

    print(f"[INFO] Found {len(output)} results.")
    return output


def format_context(results: list) -> str:
    """
    Take the list of result dicts from retrieve() and format them into a
    single string that can be injected into a language model prompt as
    context.

    Each chunk is labelled with its source filename so the model knows
    where the information came from.  Chunks are separated by a divider
    line for readability.

    Example output
    --------------
    [Source: strategy_guide.md]
    RSI (Relative Strength Index) measures the speed and magnitude of
    price movements...

    ---

    [Source: indicators.md]
    To use RSI in a Pine Script strategy, call ta.rsi(close, 14)...
    """

    # If there are no results, return a message saying so – this prevents
    # the model from hallucinating when it has no context to work with.
    if not results:
        return "[No relevant documents found in the knowledge base.]"

    sections = []
    for i, result in enumerate(results, start=1):
        # Label each chunk with a number and its source file
        header = f"[Source: {result['source']}]"
        sections.append(f"{header}\n{result['text']}")

    # Join all chunks with a divider line between them
    return "\n\n---\n\n".join(sections)


# ---------------------------------------------------------------------------
# Test block – run this file directly to try a sample query:
#   python app/rag/retriever.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Define a test query about Pine Script strategies
    test_query = "how to write a strategy entry in Pinescript"

    print(f"\n{'='*60}")
    print(f"TEST QUERY: \"{test_query}\"")
    print(f"{'='*60}\n")

    # Retrieve the top 3 most relevant chunks
    results = retrieve(query=test_query, top_k=3)

    # Print each result with its source and relevance score
    for i, result in enumerate(results, start=1):
        print(f"\n--- Result {i} ---")
        print(f"Source: {result['source']}")
        print(f"Score:  {result['score']} (lower = more relevant)")
        print(f"Text:\n{result['text'][:300]}...")  # Show first 300 chars

    # Also demonstrate the format_context function
    print(f"\n{'='*60}")
    print("FORMATTED CONTEXT (ready for prompt injection):")
    print(f"{'='*60}\n")
    print(format_context(results))
