"""Server-side configuration for the Evidentia backend.

Secrets are read from backend/.env (via pydantic-settings). They are owned by
the backend and are never returned in API responses or exposed to the frontend.
"""

import base64
import binascii
import math
import re
import zlib
from collections import Counter
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_JWT_SECRET = "evidentia-dev-secret"

MIN_SECRET_DISTINCT_CHARS = 8

# Production secrets (the JWT signing key and the BFF shared secret) must be
# *cryptographically generated* values, not merely long ones. Both must survive
# offline guessing — the JWT key signs every access token in every tenant, and the
# BFF secret is the credential that makes trusting `X-Forwarded-For` sound — so we
# require each to be the base64url or hex encoding of at least this many random bytes.
SECRET_MIN_RANDOM_BYTES = 32
BFF_SECRET_GENERATION_HINT = (
    'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(32))"'
)
JWT_SECRET_GENERATION_HINT = (
    'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
)

# Entropy floors for the *decoded* bytes. A uniformly random 32-byte secret sits
# far above these; a repetitive one does not.
MIN_SECRET_BYTE_ENTROPY = 4.0  # bits/byte; 32 random bytes ≈ 4.9
MIN_SECRET_INCOMPRESSIBLE_RATIO = 0.95  # random bytes never deflate below their size
MIN_SECRET_CHAR_CLASSES = 2  # lower / upper / digit / -_ ; an English word list has 1

# Per-character floors are alphabet-relative, because hex draws on 16 symbols and
# base64url on 64: a genuine hex secret legitimately shows lower per-character
# entropy and longer runs of consecutive symbols than a genuine base64url one.
# Applying one threshold to both rejects real `secrets.token_hex(32)` output.
# Calibrated against 200k generated secrets of each kind (0 false rejections).
# (min bits/char, sequential-run length that proves the value is not random)
_HEX_CHAR_LIMITS = (3.2, 8)
_B64URL_CHAR_LIMITS = (3.5, 6)

WEAK_SHARED_SECRETS = {
    "secret",
    "changeme",
    "change-me",
    "password",
    "bff",
    "bff-secret",
    "evidentia",
    "evidentia-bff",
    "test",
    "dev",
}

# Substrings that betray a hand-picked secret regardless of how long it is padded out.
WEAK_SECRET_SUBSTRINGS = (
    "password",
    "passwd",
    "secret",
    "changeme",
    "letmein",
    "qwerty",
    "admin",
    "evidentia",
    "production",
    "staging",
    "default",
    "example",
    "12345678",
    "abcdefgh",
)
WEAK_JWT_SECRETS = {
    DEFAULT_JWT_SECRET,
    "secret",
    "changeme",
    "change-me",
    "password",
    "jwt-secret",
    "dev",
    "development",
    "test",
    "evidentia",
    "evidentia-secret",
}


def _shannon_entropy(symbols) -> float:
    """Bits per symbol of the value's own distribution.

    An upper bound on real entropy, never a lower one: `abcd1234` repeated scores
    3.0 bits/char even though the string carries almost no unpredictability at all.
    That is exactly why it is one signal among several, not the whole test.
    """
    if not symbols:
        return 0.0
    total = len(symbols)
    return -sum(
        (n / total) * math.log2(n / total) for n in Counter(symbols).values()
    )


def _repeated_block(value: str) -> Optional[str]:
    """The shortest block the string is a whole repetition of, if any.

    `abcd1234abcd1234abcd1234abcd1234` is 32 characters with 8 distinct ones — it
    sails through a length-plus-variety check while being worth ~8 characters of
    guessing. Detected by rotating the string against itself: a string is periodic
    iff it reappears inside its own doubled copy before position len().
    """
    if len(value) < 2:
        return None
    doubled = (value + value)[1:-1]
    if value not in doubled:
        return None
    period = doubled.index(value) + 1
    return value[:period]


def _longest_sequential_run(value: str) -> int:
    """Longest run of consecutive code points, ascending or descending."""
    longest = run = 1
    for i in range(1, len(value)):
        delta = ord(value[i]) - ord(value[i - 1])
        run = run + 1 if delta in (1, -1) else 1
        longest = max(longest, run)
    return longest


def _decode_random_bytes(value: str):
    """Decode the secret as base64url or hex.

    Returns (decoded_bytes, per-character limits for that alphabet), or (None, None)
    if the value is neither encoding.

    Requiring an encoding is what turns "long enough" into "generated": you cannot
    accidentally type 43 characters that happen to be a valid base64url encoding of
    32 bytes, but you can very easily type 43 characters of English.
    """
    if re.fullmatch(r"[0-9a-fA-F]+", value) and len(value) % 2 == 0:
        try:
            return binascii.unhexlify(value), _HEX_CHAR_LIMITS
        except (binascii.Error, ValueError):
            pass
    if re.fullmatch(r"[A-Za-z0-9_-]+", value):
        try:
            return (
                base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)),
                _B64URL_CHAR_LIMITS,
            )
        except (binascii.Error, ValueError):
            return None, None
    return None, None


def _character_classes(value: str) -> int:
    return sum(
        (
            any(c.islower() for c in value),
            any(c.isupper() for c in value),
            any(c.isdigit() for c in value),
            any(c in "-_" for c in value),
        )
    )


def _generated_secret_problem(
    raw: str,
    *,
    env_var: str,
    hint: str,
    weak_values: frozenset | set,
) -> Optional[str]:
    """Why this value is not a production-grade generated secret, or None.

    A gate of "32 characters plus 8 distinct characters" accepts
    `abcd1234abcd1234abcd1234abcd1234` — a value an attacker guesses in seconds.
    Enforcing *length* is not enforcing *unpredictability*. So we require the
    shape of a generated secret (a valid base64url or hex encoding of at least
    `SECRET_MIN_RANDOM_BYTES` random bytes) and reject the recognizable shapes
    of a chosen one.
    """
    secret = (raw or "").strip()
    if not secret:
        return f"{env_var} must be set. {hint}"

    lowered = secret.lower()
    if lowered in weak_values or any(w in lowered for w in WEAK_SECRET_SUBSTRINGS):
        return (
            f"{env_var} contains a known/guessable value and must not be used "
            f"in production. {hint}"
        )

    block = _repeated_block(secret)
    if block is not None:
        return (
            f"{env_var} is the block {block!r} repeated; it has only as much "
            f"entropy as that block. {hint}"
        )

    if _character_classes(secret) < MIN_SECRET_CHAR_CLASSES:
        # A run of English words is a valid base64url string and decodes to
        # perfectly random-looking bytes (base64 whitens the bits), so the decoded
        # checks below cannot see it. Its give-away is the alphabet: generated
        # secrets mix letter cases and digits, word lists do not.
        return (
            f"{env_var} draws on too narrow a character set to be a generated "
            f"base64url/hex secret. {hint}"
        )

    # The encoding must be established before the per-character floors, because
    # those floors depend on the alphabet the secret is drawn from.
    decoded, char_limits = _decode_random_bytes(secret)
    if decoded is None:
        return (
            f"{env_var} must be the base64url or hex encoding of at least "
            f"{SECRET_MIN_RANDOM_BYTES} random bytes. {hint}"
        )
    if len(decoded) < SECRET_MIN_RANDOM_BYTES:
        return (
            f"{env_var} decodes to only {len(decoded)} bytes; at least "
            f"{SECRET_MIN_RANDOM_BYTES} random bytes are required. "
            f"{hint}"
        )

    min_char_entropy, min_sequential_run = char_limits

    if _longest_sequential_run(secret) >= min_sequential_run:
        # Also invisible to the decoded checks: "abcdef...xyzABC" decodes to bytes
        # that look uniformly random. Only the encoded form shows the pattern.
        return (
            f"{env_var} contains a long run of sequential characters, so it is "
            f"not randomly generated. {hint}"
        )

    if len(set(secret)) < MIN_SECRET_DISTINCT_CHARS:
        return (
            f"{env_var} has too little variety to be a high-entropy secret. "
            f"{hint}"
        )

    if _shannon_entropy(secret) < min_char_entropy:
        return (
            f"{env_var} has too low an estimated entropy to be a generated "
            f"secret. {hint}"
        )

    # Random bytes do not compress. A patterned secret that survived every check
    # above (because the pattern is not an exact whole repetition) still will not
    # survive deflate.
    packed = zlib.compress(decoded, 9)[2:-4]  # strip the zlib header/checksum
    if len(packed) < MIN_SECRET_INCOMPRESSIBLE_RATIO * len(decoded):
        return (
            f"{env_var} is highly compressible, so it is repetitive rather "
            f"than random. {hint}"
        )

    if _shannon_entropy(decoded) < MIN_SECRET_BYTE_ENTROPY:
        return (
            f"{env_var} decodes to low-entropy bytes, so it is not a "
            f"cryptographically generated secret. {hint}"
        )

    return None


def bff_secret_problem(raw: str) -> Optional[str]:
    """Why this value is not a usable BFF secret in production, or None.

    A guessable BFF secret is exactly as good as no BFF secret: the attacker
    reaches the backend directly, forges `X-Forwarded-For`, and every per-IP
    limit stops working.
    """
    return _generated_secret_problem(
        raw,
        env_var="EVIDENTIA_BFF_SECRET",
        hint=BFF_SECRET_GENERATION_HINT,
        weak_values=WEAK_SHARED_SECRETS,
    )


def jwt_secret_problem(raw: str) -> Optional[str]:
    """Why this value is not a usable JWT signing key in production, or None.

    Same gate as the BFF secret, and for a stronger reason: an attacker who
    recovers this key by offline guessing can mint an access token for any user
    in any tenant — it forfeits every other control in the system. The old gate
    (≥32 chars, ≥8 distinct) accepted `abcd1234abcd1234abcd1234abcd1234`.
    """
    return _generated_secret_problem(
        raw,
        env_var="JWT_SECRET",
        hint=JWT_SECRET_GENERATION_HINT,
        weak_values=WEAK_JWT_SECRETS,
    )


class Settings(BaseSettings):
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    evidentia_use_llm: bool = False
    evidentia_llm_provider: str = "openai"
    evidentia_llm_model: str = "gpt-4o-mini"
    # off | summary | full  (default: summary — one LLM call)
    evidentia_llm_intensity: str = "summary"
    evidentia_max_context_chars: int = 6000
    evidentia_max_output_tokens: int = 700
    evidentia_enable_cache: bool = True
    # minimum relevance score for the deterministic grounding-repair scorer to
    # accept a replacement citation; below this an item is marked insufficient.
    evidentia_repair_min_relevance: float = 2.0
    # minimum evidence-support strength (signal terms + 2×phrases) for a risk or
    # workflow step to be emitted as grounded from a source section.
    evidentia_min_evidence_support: int = 2
    # minimum predicted incremental overall-quality gain (points) for the auto
    # router to select full mode over summary. Calibrated high on the v1 benchmark
    # because full is on average worse than summary; see docs/ai/DECISIONS.md.
    evidentia_router_full_gain_threshold: float = 0.2

    # --- persistence ---
    database_url: str = ""
    evidentia_db_enabled: bool = True

    # --- tenant document corpus (ingestion plan, M1+) ---
    # Master switch for the customer-document ingestion feature. OFF (the
    # default) means today's behavior byte-for-byte: generation reads only the
    # bundled demo corpus, and the M1 schema/seams are inert. All ingestion
    # schema migrations land before this flag ever turns on; turning it off is
    # the whole rollback (reports are snapshots — nothing to migrate back).
    evidentia_tenant_corpus_enabled: bool = False

    # M4 rollout gate. This is deliberately independent from ingestion: an
    # operator may ingest/finalize documents before allowing those documents to
    # drive authenticated reports. Disabled never means "use the demo corpus".
    evidentia_tenant_generation_enabled: bool = False
    # Deterministic Stage-1 retrieval bounds (tenant-lexical-v1). These limits
    # are part of the snapshot identity and therefore audit-visible.
    evidentia_tenant_retrieval_max_documents: int = 50
    evidentia_tenant_retrieval_max_candidate_sections: int = 500
    evidentia_tenant_retrieval_max_selected_sections: int = 40
    evidentia_tenant_retrieval_max_total_chars: int = 60_000
    evidentia_tenant_retrieval_per_document_cap: int = 10
    evidentia_tenant_evidence_excerpt_chars: int = 1_200
    # Shared report cache is process-local; keep it bounded. Tenant keys include
    # company + immutable snapshot identity, so entries cannot cross tenants.
    evidentia_report_cache_max_entries: int = 128

    # --- document ingestion (M2: MD/TXT upload + worker) ---
    # Per-file byte cap, enforced while the upload streams (Content-Length is
    # never trusted alone). MD/TXT only in M2, so the cap is modest; later
    # formats raise it deliberately.
    evidentia_upload_max_file_bytes: int = 2 * 1024 * 1024
    # Extracted-character cap: oversized text fails with a typed error, never
    # silently truncated.
    evidentia_max_extracted_chars: int = 1_000_000
    # Files accepted per upload request (M2: exactly one).
    evidentia_upload_max_files: int = 1
    # Quota foundations (abuse bounds now, plan-tier levers later).
    evidentia_tenant_max_documents: int = 500
    evidentia_tenant_max_total_bytes: int = 100 * 1024 * 1024
    # Ingestion worker: bounded in-process pool (single-instance posture).
    evidentia_ingestion_worker_count: int = 1
    evidentia_ingestion_poll_seconds: float = 2.0
    # A running job whose heartbeat is older than this is considered abandoned
    # and is requeued (or terminally failed at the attempts cap).
    evidentia_ingestion_stale_seconds: int = 300
    evidentia_ingestion_max_attempts: int = 3

    # --- auth ---
    # Signing key for access tokens. MUST be set in production; startup fails if
    # it is left at the dev default while evidentia_env == "production".
    jwt_secret: str = "evidentia-dev-secret"
    jwt_algorithm: str = "HS256"
    # Access tokens are short-lived; the refresh token is the long-lived,
    # revocable credential (rotated on every use).
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    email_verification_ttl_hours: int = 24
    password_reset_ttl_minutes: int = 60
    # When true, unverified users may authenticate but are blocked from
    # tenant-scoped write endpoints.
    evidentia_require_email_verification: bool = False
    # Where verification/reset links point (the frontend origin).
    evidentia_public_app_url: str = "http://localhost:3000"
    # Email delivery backend: "smtp" (real delivery), "console" (log the link,
    # DEVELOPMENT ONLY), or "noop" (drop). Production requires "smtp" + a host.
    evidentia_email_backend: str = "console"
    evidentia_smtp_host: str = ""
    evidentia_smtp_port: int = 587
    evidentia_smtp_user: str = ""
    evidentia_smtp_password: str = ""
    evidentia_smtp_starttls: bool = True
    evidentia_smtp_from: str = "no-reply@evidentia.app"
    evidentia_smtp_timeout_seconds: int = 10

    # --- rate limiting ---
    # Counters are per-process and in-memory; see core/ratelimit.py.
    evidentia_rate_limit_enabled: bool = True
    # Hard cap on tracked rate-limit buckets. Past this, least-recently-used
    # buckets are evicted, so a flood of unique emails/tokens cannot exhaust memory.
    evidentia_rate_limit_max_keys: int = 100_000
    # Number of reverse proxies in front of this app whose X-Forwarded-For entries
    # can be trusted. 0 = ignore XFF entirely (use the TCP peer). Set to 1 when the
    # backend sits behind the Next.js BFF, or rate limits key on the BFF's single
    # IP and every user shares one budget. See core/client_ip.py.
    evidentia_trusted_proxy_count: int = 0
    # Shared secret proving a request arrived via the Next.js BFF. Mandatory in
    # production whenever evidentia_trusted_proxy_count > 0: without it, a directly
    # reachable backend would believe any client-supplied X-Forwarded-For.
    evidentia_bff_secret: str = ""

    # Auth limits: (requests, window seconds). Per-IP budgets are wider than
    # per-account ones — an office NAT shares an IP, but not an account.
    rl_login_ip_limit: int = 20
    rl_login_ip_window: int = 900
    rl_login_account_limit: int = 5
    rl_login_account_window: int = 900

    rl_register_ip_limit: int = 5
    rl_register_ip_window: int = 3600
    rl_register_account_limit: int = 3
    rl_register_account_window: int = 3600

    rl_refresh_ip_limit: int = 60
    rl_refresh_ip_window: int = 900
    rl_refresh_token_limit: int = 10
    rl_refresh_token_window: int = 900

    rl_password_reset_ip_limit: int = 10
    rl_password_reset_ip_window: int = 3600
    rl_password_reset_account_limit: int = 3
    rl_password_reset_account_window: int = 3600

    rl_reset_confirm_ip_limit: int = 10
    rl_reset_confirm_ip_window: int = 3600

    rl_verify_email_ip_limit: int = 20
    rl_verify_email_ip_window: int = 3600
    rl_verify_email_account_limit: int = 3
    rl_verify_email_account_window: int = 3600

    # Organization creation, per user (P1 quota: stops a verified user spamming
    # tenants). Registration still creates exactly one org for the registrant.
    rl_company_create_user_limit: int = 5
    rl_company_create_user_window: int = 86400

    # Upload limits (the ingestion-spending endpoints) — counted before any
    # multipart parsing work, per IP, per user and per tenant.
    rl_upload_ip_limit: int = 40
    rl_upload_ip_window: int = 3600
    rl_upload_user_limit: int = 20
    rl_upload_user_window: int = 3600
    rl_upload_tenant_limit: int = 60
    rl_upload_tenant_window: int = 3600

    # Generation limits (the LLM-spending endpoint) — deliberately separate from
    # and much tighter than the auth budgets, because each call costs money.
    rl_generate_user_limit: int = 10
    rl_generate_user_window: int = 3600
    rl_generate_tenant_limit: int = 30
    rl_generate_tenant_window: int = 3600
    rl_generate_ip_limit: int = 20
    rl_generate_ip_window: int = 3600

    # Export limits (the DOCX renderer endpoint). Rendering is CPU-only and
    # deterministic — no LLM spend — but it is still bounded per IP/user/tenant so
    # a single caller cannot pin a worker producing megabytes of DOCX in a loop.
    rl_export_user_limit: int = 60
    rl_export_user_window: int = 3600
    rl_export_tenant_limit: int = 120
    rl_export_tenant_window: int = 3600
    rl_export_ip_limit: int = 120
    rl_export_ip_window: int = 3600

    # Hard cap on a single rendered artifact. A report that projects to more bytes
    # than this is refused rather than streamed — a safety valve against a
    # pathological (or hostile) snapshot inflating the output.
    evidentia_export_max_bytes: int = 12 * 1024 * 1024

    # --- request limits ---
    # Hard cap on request body bytes, enforced before parsing (see main.py).
    evidentia_max_body_bytes: int = 512 * 1024

    # --- deployment ---
    evidentia_env: str = "development"
    # Comma-separated allowed CORS origins, or "*" for any (keyless public demo).
    evidentia_cors_origins: str = "*"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    def is_llm_enabled(self) -> bool:
        if not self.evidentia_use_llm:
            return False
        if self.evidentia_llm_provider == "openai":
            return bool(self.openai_api_key)
        if self.evidentia_llm_provider == "anthropic":
            return bool(self.anthropic_api_key)
        return False

    def effective_intensity(self) -> str:
        """Configured intensity: 'off' unless the LLM is enabled and a mode is set.

        May return 'auto' — the orchestrator resolves it to off/summary/full based
        on document/persona/confidence signals from the deterministic baseline.
        """
        if not self.is_llm_enabled():
            return "off"
        val = (self.evidentia_llm_intensity or "summary").lower()
        if val not in ("off", "summary", "full", "auto"):
            val = "summary"
        return val

    def active_provider(self) -> str:
        return self.evidentia_llm_provider if self.effective_intensity() != "off" else "none"

    def active_model(self):
        return self.evidentia_llm_model if self.effective_intensity() != "off" else None

    def resolved_database_url(self) -> str:
        """DATABASE_URL if set, else a local SQLite file for dev."""
        return self.database_url or "sqlite:///./evidentia.db"

    def is_db_enabled(self) -> bool:
        return self.evidentia_db_enabled

    def cors_origins(self) -> list[str]:
        raw = (self.evidentia_cors_origins or "*").strip()
        if raw == "*" or not raw:
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]

    def is_production(self) -> bool:
        return (self.evidentia_env or "development").lower() in ("production", "prod")

    def effective_jwt_secret(self) -> str:
        """The signing key.

        In production the key must be a *cryptographically generated* value — the
        base64url or hex encoding of at least 32 random bytes — not merely a long
        one (see `jwt_secret_problem`). A weak key here forfeits every other
        control in the system: an attacker who recovers it by offline guessing
        can mint an access token for any user in any tenant.

        This is validated on every call (not just at startup) so a mis-set key can
        never sign or verify a single token.
        """
        if not self.is_production():
            return self.jwt_secret

        secret = (self.jwt_secret or "").strip()
        if not secret:
            raise RuntimeError(
                f"JWT_SECRET must be set when EVIDENTIA_ENV=production. "
                f"{JWT_SECRET_GENERATION_HINT}"
            )
        problem = jwt_secret_problem(secret)
        if problem:
            raise RuntimeError(problem)
        return secret

    def validate_bff_secret(self) -> None:
        """A guessable BFF secret is the same as no BFF secret.

        The backend trusts `X-Forwarded-For` *because* only the BFF can reach it.
        If the secret can be guessed, an attacker reaches it directly, forges the
        header, and every per-IP limit in the system silently stops working. So the
        secret must actually be generated, not merely long — see `bff_secret_problem`.
        """
        secret = (self.evidentia_bff_secret or "").strip()
        if not secret:
            return  # absence is handled by the caller (it's a different problem)
        problem = bff_secret_problem(secret)
        if problem:
            raise RuntimeError(problem)

    def requires_email_verification(self) -> bool:
        return self.evidentia_require_email_verification

    def has_real_email_sender(self) -> bool:
        """True only when a sender that actually delivers mail is configured.

        `console` prints the link to the logs and `noop` throws it away. Both make
        password reset and email verification *look* like they work while silently
        failing (or leaking single-use credentials into a log aggregator).
        """
        backend = (self.evidentia_email_backend or "").lower()
        return backend == "smtp" and bool((self.evidentia_smtp_host or "").strip())

    def email_config_problem(self) -> str | None:
        """Why the mail configuration is not production-ready, or None if it is."""
        backend = (self.evidentia_email_backend or "").lower()
        if backend != "smtp":
            return (
                "EVIDENTIA_EMAIL_BACKEND must be 'smtp' in production (got "
                f"'{backend or 'unset'}'). 'console' writes single-use password-reset links "
                "to the logs and 'noop' discards them, so password reset and email "
                "verification would not actually work."
            )
        if not (self.evidentia_smtp_host or "").strip():
            return "EVIDENTIA_SMTP_HOST must be set when EVIDENTIA_EMAIL_BACKEND=smtp."
        return None


@lru_cache
def get_settings() -> Settings:
    return Settings()
