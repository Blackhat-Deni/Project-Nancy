"""
RAG Ingestion Pipeline for Project Nancy
-----------------------------------------
This module reads PDF trading-strategy documents from the data/strategies/
folder, splits them into searchable chunks, converts those chunks into
numerical embeddings, and stores everything in a ChromaDB vector database
so that Nancy can later retrieve the most relevant strategy knowledge
when answering questions.
"""

import os
import pathlib

# ---------------------------------------------------------------------------
# Docling – reads PDFs (including scanned ones) and extracts clean text.
# We use DocumentConverter which handles layout analysis, OCR, and table
# extraction under the hood.
# ---------------------------------------------------------------------------
from docling.document_converter import DocumentConverter

# ---------------------------------------------------------------------------
# SentenceTransformer – turns plain-English text into a fixed-size vector
# (an "embedding") that captures the meaning of the text.  Two pieces of
# text with similar meaning will have vectors that are close together,
# which is what makes semantic search possible.
# ---------------------------------------------------------------------------
from sentence_transformers import SentenceTransformer

# ---------------------------------------------------------------------------
# ChromaDB – a lightweight vector database that stores embeddings on disk
# and lets us query them with "find me the chunks closest to this query
# embedding."  We persist the database to data/chromadb/ so that we do not
# have to re-ingest every time the app restarts.
# ---------------------------------------------------------------------------
import chromadb

# ---------------------------------------------------------------------------
# Path configuration
# ---------------------------------------------------------------------------
# All paths are relative to the project root (two levels up from this file).
# This keeps things portable – it does not matter where the user clones the
# repo.
# ---------------------------------------------------------------------------
PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
STRATEGIES_DIR = PROJECT_ROOT / "data" / "strategies"
CHROMADB_DIR = PROJECT_ROOT / "data" / "chromadb"

# ---------------------------------------------------------------------------
# Chunking parameters
# ---------------------------------------------------------------------------
CHUNK_SIZE = 500   # Maximum number of characters per chunk
CHUNK_OVERLAP = 50  # Number of characters shared between consecutive chunks

# Why do we overlap chunks?
# -------------------------
# When we split a long document into fixed-size pieces, important ideas can
# land right at the boundary between two chunks.  If we cut cleanly with no
# overlap, a sentence that starts at the end of chunk A and finishes at the
# beginning of chunk B would be broken in half, and neither chunk would
# contain the full thought.  By letting the end of one chunk "bleed into"
# the beginning of the next chunk by 50 characters, we make sure that
# boundary sentences appear in full in at least one chunk, so we never lose
# context when searching.

# ---------------------------------------------------------------------------
# Embedding model
# ---------------------------------------------------------------------------
# all-MiniLM-L6-v2 is a compact, fast sentence-transformer model that
# produces 384-dimensional embeddings.  It is a good balance between speed
# and quality for a local RAG pipeline.
# ---------------------------------------------------------------------------
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"


def get_chromadb_collection():
    """
    Connect to (or create) the ChromaDB collection called nancy_strategies.

    We use PersistentClient so that the database is saved to disk at
    data/chromadb/.  Every time we call this function we get back the same
    collection – ChromaDB will create it on the first run and just open it
    on subsequent runs.
    """
    # Make sure the directory exists before ChromaDB tries to write there
    CHROMADB_DIR.mkdir(parents=True, exist_ok=True)

    # PersistentClient stores data on disk at the given path
    client = chromadb.PersistentClient(path=str(CHROMADB_DIR))

    # get_or_create_collection will reuse the collection if it already
    # exists, or create a new empty one if this is the first run
    collection = client.get_or_create_collection(name="nancy_strategies")

    return collection


def load_embedding_model():
    """
    Load the sentence-transformer model into memory.

    The first time this runs it will download the model weights from
    HuggingFace (~80 MB).  After that, the weights are cached locally and
    load instantly.
    """
    print(f"[INFO] Loading embedding model: {EMBEDDING_MODEL_NAME}")
    model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    print("[INFO] Embedding model loaded successfully.")
    return model


def extract_text_from_pdf(pdf_path: str) -> str:
    """
    Use Docling's DocumentConverter to read a PDF and return its full text.

    Docling handles complex PDF layouts, multi-column text, tables, and
    even scanned pages (via built-in OCR).  We call .convert() which
    returns a result object, then .document.export_to_markdown() to get
    the text as a single markdown-formatted string.
    """
    print(f"[INFO] Converting PDF with Docling: {os.path.basename(pdf_path)}")

    # Create a fresh converter instance for each file
    converter = DocumentConverter()

    # .convert() does all the heavy lifting – layout detection, OCR, etc.
    result = converter.convert(pdf_path)

    # Export the structured document as markdown text.  Markdown preserves
    # headings and table structure while being easy to chunk.
    full_text = result.document.export_to_markdown()

    print(f"[INFO] Extracted {len(full_text)} characters from {os.path.basename(pdf_path)}")
    return full_text


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    Split a long string into smaller pieces of at most `chunk_size`
    characters, with `overlap` characters shared between consecutive
    chunks.

    Example with chunk_size=10 and overlap=3:
        "ABCDEFGHIJKLMNOP"
        ->  ["ABCDEFGHIJ", "HIJKLMNOP"]
        The "HIJ" part appears in both chunks so nothing is lost at the
        boundary.

    Returns a list of non-empty chunk strings.
    """
    chunks = []
    start = 0

    while start < len(text):
        # Grab up to chunk_size characters starting from 'start'
        end = start + chunk_size
        chunk = text[start:end]

        # Only keep chunks that contain actual content (skip empty ones)
        if chunk.strip():
            chunks.append(chunk)

        # Move the window forward by (chunk_size - overlap) so the next
        # chunk starts 'overlap' characters before the end of the current one
        start += chunk_size - overlap

    return chunks


def get_ingested_filenames(collection) -> set:
    """
    Ask ChromaDB which filenames have already been ingested.

    We store the source filename in each document's metadata, so we can
    query all existing metadata and collect the unique filenames.  This
    lets us skip files that have already been processed, avoiding
    duplicate entries.
    """
    # Fetch all metadata from the collection (we do not need the actual
    # embeddings or documents for this check)
    existing = collection.get(include=["metadatas"])

    # Pull out the "source_file" field from every metadata dict
    ingested = set()
    if existing and existing["metadatas"]:
        for meta in existing["metadatas"]:
            if meta and "source_file" in meta:
                ingested.add(meta["source_file"])

    return ingested


def ingest_documents():
    """
    Main ingestion pipeline – scans data/strategies/ for PDF, MD, and TXT files,
    converts PDFs with Docling, reads others directly, chunks the text,
    generates embeddings, and stores everything in ChromaDB.

    Files that have already been ingested (based on filename) are skipped
    so that running this function multiple times is safe and fast.
    """

    # ------------------------------------------------------------------
    # Step 1: Make sure the strategies directory exists
    # ------------------------------------------------------------------
    if not STRATEGIES_DIR.exists():
        print(f"[ERROR] Strategies directory not found: {STRATEGIES_DIR}")
        print("[ERROR] Please create it and add your files there.")
        return

    # ------------------------------------------------------------------
    # Step 2: Scan for supported files (.pdf, .md, .txt) recursively
    # ------------------------------------------------------------------
    extensions = ["**/*.pdf", "**/*.md", "**/*.txt"]
    strategy_files = []
    for ext in extensions:
        strategy_files.extend(STRATEGIES_DIR.glob(ext))
    
    strategy_files = sorted(strategy_files)

    if not strategy_files:
        print(f"[WARNING] No supported files found in {STRATEGIES_DIR}")
        print("[WARNING] Add .pdf, .md, or .txt files to data/strategies/ and run again.")
        return

    print(f"[INFO] Found {len(strategy_files)} file(s) in {STRATEGIES_DIR}")

    # ------------------------------------------------------------------
    # Step 3: Connect to ChromaDB and check what has already been ingested
    # ------------------------------------------------------------------
    collection = get_chromadb_collection()
    already_ingested = get_ingested_filenames(collection)

    if already_ingested:
        print(f"[INFO] Already ingested files: {already_ingested}")

    # ------------------------------------------------------------------
    # Step 4: Load the embedding model once (reuse for every file)
    # ------------------------------------------------------------------
    model = load_embedding_model()

    # ------------------------------------------------------------------
    # Step 5: Process each file one by one
    # ------------------------------------------------------------------
    total_chunks_added = 0

    for file_path in strategy_files:
        filename = file_path.name

        # Skip files that have already been ingested
        if filename in already_ingested:
            print(f"[SKIP] {filename} has already been ingested – skipping.")
            continue

        print(f"\n{'='*60}")
        print(f"[PROCESSING] {filename}")
        print(f"{'='*60}")

        # --------------------------------------------------------------
        # Step 5a: Extract text from the file
        # --------------------------------------------------------------
        try:
            if file_path.suffix.lower() == ".pdf":
                # Use Docling for PDFs (handles layout, OCR, tables, etc.)
                full_text = extract_text_from_pdf(str(file_path))
            else:
                # Use built-in open() for markdown and text files
                # Docling is not needed for these simple text-based formats
                print(f"[INFO] Reading {file_path.suffix[1:]} file directly: {filename}")
                with open(file_path, "r", encoding="utf-8") as f:
                    full_text = f.read()
        except Exception as e:
            print(f"[ERROR] Failed to process {filename}: {e}")
            continue

        # Safety check – skip if no text could be extracted or read
        if not full_text.strip():
            print(f"[WARNING] No text extracted from {filename} – skipping.")
            continue

        # --------------------------------------------------------------
        # Step 5b: Split the extracted text into overlapping chunks
        # --------------------------------------------------------------
        chunks = chunk_text(full_text)
        print(f"[INFO] Split into {len(chunks)} chunks (size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP})")

        # --------------------------------------------------------------
        # Step 5c: Generate an embedding for each chunk
        # The model.encode() call turns each chunk string into a
        # 384-dimensional float vector that captures its meaning.
        # --------------------------------------------------------------
        print(f"[INFO] Generating embeddings for {len(chunks)} chunks...")
        embeddings = model.encode(chunks, show_progress_bar=True).tolist()

        # --------------------------------------------------------------
        # Step 5d: Prepare the data for ChromaDB
        # Each entry needs:
        #   - a unique ID (we use filename + chunk index)
        #   - the embedding vector
        #   - the original text (so we can return it in search results)
        #   - metadata (source filename and chunk index for traceability)
        # --------------------------------------------------------------
        ids = []
        metadatas = []

        for i, chunk in enumerate(chunks):
            # Build a unique, human-readable ID for each chunk
            chunk_id = f"{filename}::chunk_{i:04d}"
            ids.append(chunk_id)

            # Attach metadata so we can trace every chunk back to its
            # source file and know its position in the document
            metadatas.append({
                "source_file": filename,
                "chunk_index": i,
                "total_chunks": len(chunks),
            })

        # --------------------------------------------------------------
        # Step 5e: Store chunks + embeddings + metadata in ChromaDB
        # We use .add() which inserts new records.  Because we skip
        # already-ingested files above, we will never have ID collisions.
        # --------------------------------------------------------------
        print(f"[INFO] Storing {len(chunks)} chunks in ChromaDB...")
        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=chunks,
            metadatas=metadatas,
        )

        total_chunks_added += len(chunks)
        print(f"[DONE] {filename} – {len(chunks)} chunks ingested successfully.")

    # ------------------------------------------------------------------
    # Step 6: Print a summary of the ingestion run
    # ------------------------------------------------------------------
    print(f"\n{'='*60}")
    print(f"[SUMMARY] Ingestion complete.")
    print(f"[SUMMARY] New chunks added this run: {total_chunks_added}")
    print(f"[SUMMARY] Total chunks in collection: {collection.count()}")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# Entry point – run the ingestion pipeline directly from the command line:
#   python -m app.rag.ingestion
# or:
#   python app/rag/ingestion.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    ingest_documents()
