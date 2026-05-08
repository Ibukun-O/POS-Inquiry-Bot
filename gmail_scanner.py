"""
gmail_scanner.py
----------------
Python script that:
  1. Connects to Gmail via OAuth2 (no browser popup, uses refresh token).
  2. Scans inbox for unread emails with subject 'POS Inquiry'.
  3. Analyzes sentiment & drafts a reply.
  4. Saves the reply as a Gmail draft.
  5. Marks the original email as read.
"""

import base64
import logging
import os
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

import anthropic
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
)
logger = logging.getLogger("pos_inquiry_bot")

EMAIL_SUBJECT_FILTER = os.getenv("EMAIL_SUBJECT_FILTER", "POS Inquiry")

# ---------------------------------------------------------------------------
# Knowledge Base
# ---------------------------------------------------------------------------

KNOWLEDGE_BASE = """
You are a professional customer support agent for a POS (Point of Sale) equipment company.

**Product Knowledge Base:**
- POS Terminal: ₦145,000 each (one-time purchase price)
- Includes hardware setup and basic onboarding support
- Bulk discounts available for orders of 5+ units (contact sales team)
- Warranty: 12 months on hardware
- Support: Business hours Mon–Fri, 8 AM – 5 PM WAT

**Guidelines:**
- Be warm, professional, and concise.
- Always address the customer by referencing their email if possible.
- If the customer is asking about pricing, confirm the ₦145,000 unit price clearly.
- If the inquiry is a complaint, acknowledge it empathetically before providing resolution steps.
- Close every email with: "Best regards, POS Support Team"
"""

# ---------------------------------------------------------------------------
# Gmail Authentication (headless – uses refresh token only)
# ---------------------------------------------------------------------------

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
]


def build_gmail_service():
    """Build and return an authenticated Gmail API service client."""
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        raise EnvironmentError(
            "Missing one or more required env vars: "
            "GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN"
        )

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )

    # Refresh the access token silently
    creds.refresh(Request())
    logger.debug("Gmail credentials refreshed successfully.")

    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    return service


# ---------------------------------------------------------------------------
# Email Helpers
# ---------------------------------------------------------------------------

def get_email_body(payload: dict) -> str:
    """Recursively extract plain-text body from a Gmail message payload."""
    body = ""

    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            body = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    elif payload.get("mimeType", "").startswith("multipart/"):
        for part in payload.get("parts", []):
            body = get_email_body(part)
            if body:
                break

    return body.strip()


def get_header(headers: list, name: str) -> str:
    """Extract a specific header value from a list of header dicts."""
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def clean_text(text: str) -> str:
    """Remove excessive whitespace from text."""
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# Sentiment Analysis + Response Drafting
# ---------------------------------------------------------------------------

def analyse_and_draft_response(sender_email: str, email_body: str) -> dict:
    """
    Use Claude to:
      - Determine sentiment (Positive / Neutral / Negative)
      - Draft a professional email reply

    Returns a dict: {"sentiment": str, "draft_reply": str}
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY is not set in environment.")

    client = anthropic.Anthropic(api_key=api_key)

    prompt = f"""
You are responding to a POS inquiry email.

Sender: {sender_email}
Email Body:
\"\"\"
{email_body}
\"\"\"

Using the knowledge base provided in the system prompt, do the following:

1. Identify the sentiment of this email (choose one: Positive, Neutral, Negative).
2. Draft a professional, helpful reply email.

Respond in this exact format:

SENTIMENT: <Positive|Neutral|Negative>
---
DRAFT_REPLY:
<your full email reply here, starting with a greeting>
"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=KNOWLEDGE_BASE,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_response = message.content[0].text.strip()
    logger.debug(f"Claude raw response:\n{raw_response}")

    # Parse response
    sentiment = "Neutral"
    draft_reply = ""

    sentiment_match = re.search(r"SENTIMENT:\s*(Positive|Neutral|Negative)", raw_response, re.IGNORECASE)
    if sentiment_match:
        sentiment = sentiment_match.group(1).capitalize()

    draft_match = re.search(r"DRAFT_REPLY:\s*(.*)", raw_response, re.DOTALL | re.IGNORECASE)
    if draft_match:
        draft_reply = draft_match.group(1).strip()

    if not draft_reply:
        logger.warning("Could not parse draft reply from Claude response. Using raw output.")
        draft_reply = raw_response

    return {"sentiment": sentiment, "draft_reply": draft_reply}


# ---------------------------------------------------------------------------
# Gmail Actions
# ---------------------------------------------------------------------------

def create_draft(service, sender: str, recipient: str, subject: str, body: str) -> Optional[str]:
    """Create a Gmail draft and return its draft ID."""
    try:
        message = MIMEMultipart("alternative")
        message["to"] = recipient
        message["from"] = sender
        message["subject"] = f"Re: {subject}"

        part = MIMEText(body, "plain")
        message.attach(part)

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        draft_body = {"message": {"raw": raw}}

        draft = service.users().drafts().create(userId="me", body=draft_body).execute()
        draft_id = draft.get("id")
        logger.info(f"Draft created with ID: {draft_id}")
        return draft_id

    except HttpError as e:
        logger.error(f"Failed to create draft: {e}")
        return None


def mark_as_read(service, message_id: str) -> bool:
    """Remove the UNREAD label from a Gmail message."""
    try:
        service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"removeLabelIds": ["UNREAD"]},
        ).execute()
        logger.info(f"Message {message_id} marked as read.")
        return True
    except HttpError as e:
        logger.error(f"Failed to mark message {message_id} as read: {e}")
        return False


# ---------------------------------------------------------------------------
# Main Scanner Logic
# ---------------------------------------------------------------------------

def scan_and_respond() -> dict:
    """
    Main function:
      - Fetches unread POS Inquiry emails
      - Processes each with Claude
      - Creates Gmail drafts
      - Marks originals as read

    Returns a summary dict.
    """
    logger.info("Starting POS Inquiry email scanner...")
    summary = {"processed": 0, "skipped": 0, "errors": 0, "results": []}

    try:
        service = build_gmail_service()
    except EnvironmentError as e:
        logger.error(f"Auth setup failed: {e}")
        summary["errors"] += 1
        return summary

    # Fetch unread emails with the target subject
    query = f'is:unread subject:"{EMAIL_SUBJECT_FILTER}"'
    logger.info(f"Gmail query: {query}")

    try:
        response = service.users().messages().list(userId="me", q=query).execute()
    except HttpError as e:
        logger.error(f"Failed to list messages: {e}")
        summary["errors"] += 1
        return summary

    messages = response.get("messages", [])
    logger.info(f"Found {len(messages)} unread message(s) matching filter.")

    if not messages:
        logger.info("No messages to process. Exiting.")
        return summary

    # Retrieve sender's email address (the 'me' user)
    try:
        profile = service.users().getProfile(userId="me").execute()
        my_email = profile.get("emailAddress", "me")
    except HttpError:
        my_email = "me"

    for msg_stub in messages:
        msg_id = msg_stub["id"]
        result_entry = {"message_id": msg_id, "status": "error", "sentiment": None, "draft_id": None}

        try:
            # Fetch full message
            msg = service.users().messages().get(
                userId="me", id=msg_id, format="full"
            ).execute()

            headers = msg.get("payload", {}).get("headers", [])
            sender = get_header(headers, "From")
            subject = get_header(headers, "Subject")
            body = get_email_body(msg.get("payload", {}))

            logger.info(f"Processing email from: {sender} | Subject: {subject}")

            if not body:
                logger.warning(f"Email {msg_id} has no readable body. Skipping.")
                result_entry["status"] = "skipped_no_body"
                summary["skipped"] += 1
                summary["results"].append(result_entry)
                continue

            # Extract just the email address from "Name <email@example.com>" format
            email_match = re.search(r"<(.+?)>", sender)
            sender_email = email_match.group(1) if email_match else sender

            # Analyse with Claude
            ai_result = analyse_and_draft_response(sender_email, clean_text(body))
            sentiment = ai_result["sentiment"]
            draft_reply = ai_result["draft_reply"]

            logger.info(f"Sentiment detected: {sentiment}")

            # Save draft in Gmail
            draft_id = create_draft(
                service,
                sender=my_email,
                recipient=sender_email,
                subject=subject,
                body=draft_reply,
            )

            # Mark original as read
            mark_as_read(service, msg_id)

            result_entry.update({
                "status": "success",
                "sender": sender_email,
                "subject": subject,
                "sentiment": sentiment,
                "draft_id": draft_id,
            })
            summary["processed"] += 1

        except anthropic.APIError as e:
            logger.error(f"Anthropic API error for message {msg_id}: {e}")
            result_entry["error"] = str(e)
            summary["errors"] += 1

        except HttpError as e:
            logger.error(f"Gmail API error for message {msg_id}: {e}")
            result_entry["error"] = str(e)
            summary["errors"] += 1

        except Exception as e:
            logger.exception(f"Unexpected error for message {msg_id}: {e}")
            result_entry["error"] = str(e)
            summary["errors"] += 1

        summary["results"].append(result_entry)

    logger.info(
        f"Scan complete. Processed: {summary['processed']}, "
        f"Skipped: {summary['skipped']}, Errors: {summary['errors']}"
    )
    return summary


# ---------------------------------------------------------------------------
# Entry Point (standalone run)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    result = scan_and_respond()
    import json
    print(json.dumps(result, indent=2))
