"""Request/response schemas. The report itself is emitted as a plain dict with
camelCase keys to exactly match the frontend's EvidentiaReport shape, so these
Pydantic models are only used for input validation and typing."""

from typing import Any, Dict, List

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    market: str = "EMEA"
    persona: str = "Support Agent"
    customPersona: str = ""
    selectedDocumentIds: List[str] = Field(default_factory=list)


# A DocumentSection as produced by the document reader.
DocumentSection = Dict[str, Any]
# The final report is a dict with camelCase keys (EvidentiaReport).
EvidentiaReport = Dict[str, Any]
