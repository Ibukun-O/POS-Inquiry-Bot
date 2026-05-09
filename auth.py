"""
auth.py — Google OAuth2 credentials for the Gmail API.

On first run (or when token.json is missing/expired) the browser opens for
the OAuth consent screen.  Subsequent runs reuse the cached token automatically.
"""

import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Minimum scopes required by the bot
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",  # read messages
    "https://www.googleapis.com/auth/gmail.compose",   # create drafts
    "https://www.googleapis.com/auth/gmail.modify",    # modify labels (mark read)
]

TOKEN_PATH = Path(os.getenv("GMAIL_TOKEN_PATH", "token.json"))
CREDENTIALS_PATH = Path(os.getenv("GMAIL_CREDENTIALS_PATH", "credentials.json"))


def get_gmail_credentials() -> Credentials:
    """
    Load cached credentials or run the OAuth2 flow to obtain fresh ones.
    Persists the token to TOKEN_PATH for reuse.
    """
    creds: Credentials | None = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_PATH.exists():
                raise FileNotFoundError(
                    f"Google credentials file not found at '{CREDENTIALS_PATH}'.\n"
                    "Download it from the Google Cloud Console and place it in the "
                    "project root (or set GMAIL_CREDENTIALS_PATH env var)."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0)

        TOKEN_PATH.write_text(creds.to_json())

    return creds
