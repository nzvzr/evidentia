"""Evidentia FastAPI backend entrypoint."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents.document_reader import list_documents
from app.agents.orchestrator import run_pipeline
from app.models.schemas import GenerateRequest

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Evidentia Backend", version="1.0.0")

# The frontend (and Next.js API route) may call this directly in local dev.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/documents")
def documents():
    return {"documents": list_documents()}


@app.post("/api/generate-workflow")
def generate_workflow(body: GenerateRequest):
    # run_pipeline never raises for LLM issues; it falls back to deterministic.
    return run_pipeline(
        market=body.market,
        persona=body.persona,
        custom_persona=body.customPersona,
        selected_document_ids=body.selectedDocumentIds,
    )
