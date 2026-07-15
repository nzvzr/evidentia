"""Request/response schemas.

The report itself is emitted as a plain dict with camelCase keys to exactly
match the frontend's EvidentiaReport shape; these Pydantic models cover input
validation for the CRUD endpoints.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

# Long enough to resist offline cracking, capped to bound bcrypt/SHA work per
# request. (bcrypt's own 72-byte limit is handled by the SHA-256 pre-hash.)
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 256

# RFC 5321 caps an address at 254 characters. Enforced explicitly: EmailStr
# validates *shape*, not length, and an unbounded string reaches the DB index and
# the bcrypt/normalisation path.
MAX_EMAIL_LENGTH = 254

# Opaque tokens are 43 chars (256 bits, url-safe base64). The cap is generous but
# finite so a multi-megabyte "token" cannot be pushed into a hash/lookup.
MAX_TOKEN_LENGTH = 512

# Generation inputs. The document cap bounds the pipeline's fan-out (and the LLM
# context assembled from it) per request.
MAX_SELECTED_DOCUMENTS = 50
MAX_DOCUMENT_ID_LENGTH = 200
MAX_CUSTOM_PERSONA_LENGTH = 500

# Document upload text. Bounded well under the request body cap.
MAX_CONTENT_TEXT_LENGTH = 200_000


def _validate_password(value: str) -> str:
    if len(value) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(value) > MAX_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at most {MAX_PASSWORD_LENGTH} characters")
    if value.strip() == "":
        raise ValueError("Password must not be blank")
    return value


def _validate_email_length(value: str) -> str:
    if len(value) > MAX_EMAIL_LENGTH:
        raise ValueError(f"Email must be at most {MAX_EMAIL_LENGTH} characters")
    return value


class GenerateRequest(BaseModel):
    market: str = Field(default="EMEA", max_length=64)
    persona: str = Field(default="Support Agent", max_length=120)
    customPersona: str = Field(default="", max_length=MAX_CUSTOM_PERSONA_LENGTH)
    selectedDocumentIds: List[str] = Field(
        default_factory=list, max_length=MAX_SELECTED_DOCUMENTS
    )

    @field_validator("selectedDocumentIds")
    @classmethod
    def _check_document_ids(cls, value: List[str]) -> List[str]:
        for doc_id in value:
            if len(doc_id) > MAX_DOCUMENT_ID_LENGTH:
                raise ValueError("Document id is too long")
        return value


# `companyId` is deliberately not a field on these: the owning tenant comes from
# the authenticated CompanyContext, so a client cannot write into another tenant.
class DocumentCreate(BaseModel):
    title: str = Field(max_length=300)
    slug: Optional[str] = Field(default=None, max_length=300)
    type: Optional[str] = Field(default=None, max_length=80)
    category: Optional[str] = Field(default=None, max_length=80)
    contentText: Optional[str] = Field(default=None, max_length=MAX_CONTENT_TEXT_LENGTH)
    metadata: Optional[Dict[str, Any]] = None


class PersonaCreate(BaseModel):
    name: str = Field(max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    roleType: Optional[str] = Field(default=None, max_length=80)
    metadata: Optional[Dict[str, Any]] = None


class CompanyCreate(BaseModel):
    name: str = Field(max_length=200)
    slug: Optional[str] = Field(default=None, max_length=200)


# --- auth ---------------------------------------------------------------


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: Optional[str] = Field(default=None, max_length=200)
    # Organization to create and own. Defaults to a personal organization.
    company: Optional[str] = Field(default=None, max_length=200)

    _check_password = field_validator("password")(_validate_password)
    _check_email = field_validator("email")(_validate_email_length)


class LoginRequest(BaseModel):
    email: EmailStr
    # Not length-validated against the *policy* (an old password may predate a
    # rule change) but still bounded, so login cannot be used to force unbounded
    # hashing work.
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)

    _check_email = field_validator("email")(_validate_email_length)


class RefreshRequest(BaseModel):
    refreshToken: str = Field(max_length=MAX_TOKEN_LENGTH)


class LogoutRequest(BaseModel):
    refreshToken: Optional[str] = Field(default=None, max_length=MAX_TOKEN_LENGTH)


class VerifyEmailRequest(BaseModel):
    email: EmailStr

    _check_email = field_validator("email")(_validate_email_length)


class VerifyEmailConfirm(BaseModel):
    token: str = Field(max_length=MAX_TOKEN_LENGTH)


class PasswordResetRequest(BaseModel):
    email: EmailStr

    _check_email = field_validator("email")(_validate_email_length)


class PasswordResetConfirm(BaseModel):
    token: str = Field(max_length=MAX_TOKEN_LENGTH)
    password: str

    _check_password = field_validator("password")(_validate_password)


class MemberInvite(BaseModel):
    """Grant an existing user a role in the caller's company."""

    email: EmailStr
    role: str = Field(default="member", max_length=20)

    _check_email = field_validator("email")(_validate_email_length)


class MemberRoleUpdate(BaseModel):
    role: str = Field(max_length=20)


class OwnershipTransfer(BaseModel):
    userId: str = Field(max_length=36)


class ReportCreate(BaseModel):
    """A generated EvidentiaReport.

    `companyId`/`userId` are intentionally absent: ownership is derived from the
    authenticated session, never accepted from the client. Accepting them was
    the tenant-forgery hole in the previous version.
    """

    report: Dict[str, Any]
    personaId: Optional[str] = None


# A DocumentSection as produced by the document reader.
DocumentSection = Dict[str, Any]
# The final report is a dict with camelCase keys (EvidentiaReport).
EvidentiaReport = Dict[str, Any]
