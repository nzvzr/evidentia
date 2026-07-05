"""Request/response schemas.

The report itself is emitted as a plain dict with camelCase keys to exactly
match the frontend's EvidentiaReport shape; these Pydantic models cover input
validation for the CRUD endpoints.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    market: str = "EMEA"
    persona: str = "Support Agent"
    customPersona: str = ""
    selectedDocumentIds: List[str] = Field(default_factory=list)


class DocumentCreate(BaseModel):
    title: str
    slug: Optional[str] = None
    type: Optional[str] = None
    category: Optional[str] = None
    contentText: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    companyId: Optional[str] = None


class PersonaCreate(BaseModel):
    name: str
    description: Optional[str] = None
    roleType: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    companyId: Optional[str] = None


class CompanyCreate(BaseModel):
    name: str
    slug: Optional[str] = None


class RegisterRequest(BaseModel):
    email: str
    name: Optional[str] = None
    password: Optional[str] = None


class ReportCreate(BaseModel):
    """A generated EvidentiaReport plus optional ownership metadata."""

    report: Dict[str, Any]
    companyId: Optional[str] = None
    userId: Optional[str] = None
    personaId: Optional[str] = None


# A DocumentSection as produced by the document reader.
DocumentSection = Dict[str, Any]
# The final report is a dict with camelCase keys (EvidentiaReport).
EvidentiaReport = Dict[str, Any]
