"""
scanner.py — Core Gmail POS Inquiry scanner powered by OpenAI.

Pipeline per email
------------------
  1. Fetch all unread messages with subject containing "POS Inquiry".
  2. Analyse sentiment via OpenAI (returns label, score, one-line summary).
  3. Generate a professional reply via OpenAI tailored to that sentiment.
  4. Save the reply as a Gmail Draft (threaded with the original).
  5. Mark the original message as read.
"""

import base64
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.mime.text import MIMEText
from typing import Optional

from openai import OpenAI
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from auth import get_gmail_credentials

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Data models
# ─────────────────────────────────────────────

@dataclass
class EmailMessage:
    msg_id: str
    thread_id: str
    sender: str
    subject: str
    body: str
    received_at: datetime


@dataclass
class ScanResult:
    email: EmailMessage
    sentiment: str           # "positive" | "neutral" | "negative"
    sentiment_score: float   # –1.0 … +1.0
    sentiment_summary: str
    draft_id: str
    draft_body: str
    processed_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ─────────────────────────────────────────────
# Gmail helpers
# ─────────────────────────────────────────────

def _decode_body(payload: dict) -> str:
    """Recursively extract the plain-text body from a Gmail message payload."""
    mime_type = payload.get("mimeType", "")
    if mime_type == "text/plain":
        data = payload.get("body", {}).get("data", "")
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    if mime_type.startswith("multipart/"):
        for part in payload.get("parts", []):
            text = _decode_body(part)
            if text:
                return text
    return ""


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def fetch_unread_pos_emails(service) -> list[EmailMessage]:
    """Return every unread Gmail message whose subject contains 'POS Inquiry'."""
    query = 'is:unread subject:"POS Inquiry"'
    messages: list[EmailMessage] = []

    try:
        resp = service.users().messages().list(
            userId="me", q=query, maxResults=50
        ).execute()
        items = resp.get("messages", [])
    except HttpError as exc:
        logger.error("Gmail list error: %s", exc)
        return messages

    for item in items:
        try:
            full = service.users().messages().get(
                userId="me", id=item["id"], format="full"
            ).execute()
            headers = full["payload"].get("headers", [])
            body = _decode_body(full["payload"])
            received_at = datetime.fromtimestamp(
                int(full.get("internalDate", 0)) / 1000, tz=timezone.utc
            )
            messages.append(
                EmailMessage(
                    msg_id=full["id"],
                    thread_id=full["threadId"],
                    sender=_header(headers, "From"),
                    subject=_header(headers, "Subject"),
                    body=body.strip(),
                    received_at=received_at,
                )
            )
        except HttpError as exc:
            logger.warning("Could not fetch message %s: %s", item["id"], exc)

    logger.info("Found %d unread POS Inquiry email(s).", len(messages))
    return messages


def create_draft(service, to: str, subject: str, body: str, thread_id: str) -> str:
    """Save a draft reply in Gmail and return its draft ID."""
    reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    mime = MIMEText(body, "plain")
    mime["To"] = to
    mime["Subject"] = reply_subject
    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()

    draft = service.users().drafts().create(
        userId="me",
        body={"message": {"threadId": thread_id, "raw": raw}},
    ).execute()
    return draft["id"]


def mark_as_read(service, msg_id: str) -> None:
    """Remove the UNREAD label from a message."""
    service.users().messages().modify(
        userId="me",
        id=msg_id,
        body={"removeLabelIds": ["UNREAD"]},
    ).execute()


# ─────────────────────────────────────────────
# OpenAI helpers
# ─────────────────────────────────────────────

_SENTIMENT_SYSTEM = """
You are an expert email analyst for a Point-of-Sale (POS) software company.
Given a customer email body, analyze its sentiment and respond ONLY with valid
JSON — no markdown fences, no extra text — in exactly this shape:

{
  "sentiment": "<positive|neutral|negative>",
  "score": <float between -1.0 and 1.0>,
  "summary": "<one concise sentence describing the customer's emotional tone>"
}
""".strip()

_REPLY_SYSTEM = """
You are a professional customer-support agent for a POS (Point-of-Sale) software
company called SwiftPOS.

Write a concise, warm, and helpful reply to the customer email provided.

Rules:
- Greet the customer by first name if identifiable, otherwise use "there".
- Acknowledge their specific concern.
- Provide a clear, actionable response.
- If the sentiment is negative, express genuine empathy before offering a solution.
- If the sentiment is positive, mirror their enthusiasm.
- Close with: "Best regards,\nAlex\nSwiftPOS Support Team"
- Plain text only — no markdown, no bullet symbols.
- Maximum 200 words.
""".strip()


def analyse_sentiment(
    client: OpenAI, body: str, model: str
) -> tuple[str, float, str]:
    """Return (label, score, summary) for the email body."""
    import json

    completion = client.chat.completions.create(
        model=model,
        temperature=0,
        max_tokens=200,
        messages=[
            {"role": "system", "content": _SENTIMENT_SYSTEM},
            {"role": "user", "content": body},
        ],
    )
    raw = completion.choices[0].message.content or ""
    raw = re.sub(r"```[a-z]*", "", raw).strip("`").strip()

    try:
        data = json.loads(raw)
        return (
            data.get("sentiment", "neutral"),
            float(data.get("score", 0.0)),
            data.get("summary", ""),
        )
    except (json.JSONDecodeError, ValueError):
        logger.warning("Could not parse sentiment JSON: %s", raw)
        return "neutral", 0.0, raw


def generate_reply(
    client: OpenAI, body: str, sentiment: str, model: str
) -> str:
    """Generate and return a professional reply body."""
    user_prompt = (
        f"Customer sentiment: {sentiment}\n\n"
        f"Customer email:\n{body}"
    )
    completion = client.chat.completions.create(
        model=model,
        temperature=0.7,
        max_tokens=400,
        messages=[
            {"role": "system", "content": _REPLY_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
    )
    return (completion.choices[0].message.content or "").strip()


# ─────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────

def run_scan(
    openai_api_key: Optional[str] = None,
    openai_model: str = "gpt-4o",
) -> list[ScanResult]:
    """
    Main entry point.  Scans Gmail, analyses sentiment, drafts replies,
    marks emails as read, and returns a ScanResult for each processed email.
    """
    import os

    creds = get_gmail_credentials()
    gmail = build("gmail", "v1", credentials=creds)

    api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY is not set.  "
            "Export it or add it to your .env file."
        )
    openai_client = OpenAI(api_key=api_key)

    emails = fetch_unread_pos_emails(gmail)
    results: list[ScanResult] = []

    for email in emails:
        logger.info("Processing %s from %s", email.msg_id, email.sender)

        sentiment, score, summary = analyse_sentiment(
            openai_client, email.body, openai_model
        )
        reply_body = generate_reply(
            openai_client, email.body, sentiment, openai_model
        )

        try:
            draft_id = create_draft(
                gmail,
                to=email.sender,
                subject=email.subject,
                body=reply_body,
                thread_id=email.thread_id,
            )
            mark_as_read(gmail, email.msg_id)
            logger.info(
                "Draft %s saved; email %s marked read.", draft_id, email.msg_id
            )
            results.append(
                ScanResult(
                    email=email,
                    sentiment=sentiment,
                    sentiment_score=score,
                    sentiment_summary=summary,
                    draft_id=draft_id,
                    draft_body=reply_body,
                )
            )
        except HttpError as exc:
            logger.error("Gmail write error for %s: %s", email.msg_id, exc)

    return results
