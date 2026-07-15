"""Email delivery.

`SMTPEmailSender` is a real, working sender (stdlib `smtplib`) and is the only
backend production accepts — password reset and email verification are only
genuinely usable if the mail is genuinely delivered.

The other senders exist for development and tests, and each fails in a way that
would be dangerous in production:

* `ConsoleEmailSender` writes the link — a single-use account-takeover credential —
  into the application log.
* `NoopEmailSender` silently discards it, so the flow *looks* like it works while
  no user ever receives a link.

`validate_production_config` therefore refuses both (see `main.py`), and the
console sender additionally refuses to emit anything if it somehow finds itself
running in production.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import List, Protocol
from urllib.parse import quote

from app.core.config import get_settings

logger = logging.getLogger("evidentia.email")


@dataclass
class OutboundEmail:
    to: str
    subject: str
    body: str


class EmailSender(Protocol):
    def send(self, message: OutboundEmail) -> None:  # pragma: no cover - protocol
        ...


class ConsoleEmailSender:
    """DEVELOPMENT ONLY. Logs the message, including the single-use link."""

    def send(self, message: OutboundEmail) -> None:
        if get_settings().is_production():
            # Belt and braces: startup validation already refuses this backend, but
            # never write an account-takeover credential into a production log.
            logger.error("[email] console sender is disabled in production; message dropped")
            return
        logger.info("[email] to=%s subject=%s\n%s", message.to, message.subject, message.body)


class NoopEmailSender:
    """Drops the message. Used when email is intentionally disabled."""

    def send(self, message: OutboundEmail) -> None:
        return None


class SMTPEmailSender:
    """Real delivery over SMTP (stdlib `smtplib`, no third-party dependency).

    This is the only sender that actually delivers, and therefore the only one
    production accepts. Failures are raised, not swallowed: the caller decides
    whether a delivery failure should abort the flow (it never aborts registration,
    but it must not be reported to the user as a sent email).
    """

    def send(self, message: OutboundEmail) -> None:
        import smtplib
        from email.message import EmailMessage

        settings = get_settings()

        msg = EmailMessage()
        msg["From"] = settings.evidentia_smtp_from
        msg["To"] = message.to
        msg["Subject"] = message.subject
        msg.set_content(message.body)

        with smtplib.SMTP(
            settings.evidentia_smtp_host,
            settings.evidentia_smtp_port,
            timeout=settings.evidentia_smtp_timeout_seconds,
        ) as smtp:
            if settings.evidentia_smtp_starttls:
                smtp.starttls()
            if settings.evidentia_smtp_user:
                smtp.login(settings.evidentia_smtp_user, settings.evidentia_smtp_password)
            smtp.send_message(msg)

        # Never log the body: it contains a single-use reset/verification token.
        logger.info("[email] delivered to=%s subject=%s", message.to, message.subject)


class MemoryEmailSender:
    """Captures messages in-process. Used by the test suite to assert that the
    verification/reset flows actually deliver a usable token."""

    def __init__(self) -> None:
        self.outbox: List[OutboundEmail] = []

    def send(self, message: OutboundEmail) -> None:
        self.outbox.append(message)


@lru_cache
def get_email_sender() -> EmailSender:
    backend = (get_settings().evidentia_email_backend or "console").lower()
    if backend == "smtp":
        return SMTPEmailSender()
    if backend == "noop":
        return NoopEmailSender()
    return ConsoleEmailSender()


def _app_url() -> str:
    return (get_settings().evidentia_public_app_url or "").rstrip("/")


def send_verification_email(to: str, token: str) -> None:
    link = f"{_app_url()}/verify-email?token={quote(token)}"
    get_email_sender().send(
        OutboundEmail(
            to=to,
            subject="Verify your Evidentia email address",
            body=(
                "Confirm your email address to activate your Evidentia account:\n\n"
                f"{link}\n\n"
                f"This link expires in {get_settings().email_verification_ttl_hours} hours."
            ),
        )
    )


def send_password_reset_email(to: str, token: str) -> None:
    link = f"{_app_url()}/reset-password?token={quote(token)}"
    get_email_sender().send(
        OutboundEmail(
            to=to,
            subject="Reset your Evidentia password",
            body=(
                "A password reset was requested for this address. If it wasn't you, "
                "ignore this email — nothing has changed.\n\n"
                f"{link}\n\n"
                f"This link expires in {get_settings().password_reset_ttl_minutes} minutes "
                "and can be used once."
            ),
        )
    )
