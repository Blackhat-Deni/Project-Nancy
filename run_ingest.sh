#!/bin/bash
cd "/home/deni/Project Nancy V.1.0/project-nancy"
export PYTHONPATH=.
.venv/bin/python app/rag/ingestion.py > ingestion.log 2>&1
