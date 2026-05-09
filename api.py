"""
api.py — FastAPI service for the Gmail POS Inquiry Bot.

Endpoints
─────────
GET  /                  App info & health check
GET  /status            Runtime stats (uptime, scan counts, last scan time)
POST /scan              Trigger a Gmail scan in the background
GET  /results           Results from the most recent scan
GET  /results/{id}      Detail for a single scan result (0-indexed)
GET  /config            Show active configuration (no secrets exposed)
"""

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel

from scanner import ScanResult, run_scan

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Runtime state  (replace with a DB for production)
# ─────────────────────────────────────────────
_APP_START = datetime.now(timezone.utc)
_last_scan_at: datetime | None = None
_last_results: list[ScanResult] = []
_total_scans: int = 0
_total_emails_processed: int = 0
_scan_in_progress: bool = False
_last_scan_error: str | None = None


# ─────────────────────────────────────────────
# Lifespan
# ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("POS Inquiry Bot API starting up…")
    yield
    logger.info("POS Inquiry Bot API shutting down.")


# ─────────────────────────────────────────────
# App
# ─────────────────────────────────────────────
app = FastAPI(
    title="Gmail POS Inquiry Bot",
    description=(
        "Headless service that scans Gmail for unread 'POS Inquiry' emails, "
        "analyses sentiment with OpenAI, saves a draft reply, and marks the "
        "original as read."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ─────────────────────────────────────────────
# Pydantic schemas
# ─────────────────────────────────────────────

class AppInfo(BaseModel):
    name: str
    version: str
    description: str
    started_at: str
    uptime_seconds: float


class StatusResponse(BaseModel):
    status: str
    uptime_seconds: float
    total_scans: int
    total_emails_processed: int
    last_scan_at: str | None
    scan_in_progress: bool
    last_scan_error: str | None


class ScanTriggerResponse(BaseModel):
    message: str
    scan_id: str


class ConfigResponse(BaseModel):
    openai_model: str
    openai_api_key_set: bool
    gmail_credentials_path: str
    gmail_token_path: str
    host: str
    port: int


class SentimentDetail(BaseModel):
    label: str
    score: float
    summary: str


class EmailDetail(BaseModel):
    msg_id: str
    sender: str
    subject: str
    received_at: str
    body_preview: str


class ScanResultResponse(BaseModel):
    result_id: int
    email: EmailDetail
    sentiment: SentimentDetail
    draft_id: str
    draft_preview: str
    processed_at: str


# ─────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────

def _uptime() -> float:
    return (datetime.now(timezone.utc) - _APP_START).total_seconds()


def _to_response(idx: int, r: ScanResult) -> ScanResultResponse:
    return ScanResultResponse(
        result_id=idx,
        email=EmailDetail(
            msg_id=r.email.msg_id,
            sender=r.email.sender,
            subject=r.email.subject,
            received_at=r.email.received_at.isoformat(),
            body_preview=(
                r.email.body[:300] + "…" if len(r.email.body) > 300 else r.email.body
            ),
        ),
        sentiment=SentimentDetail(
            label=r.sentiment,
            score=round(r.sentiment_score, 3),
            summary=r.sentiment_summary,
        ),
        draft_id=r.draft_id,
        draft_preview=(
            r.draft_body[:300] + "…" if len(r.draft_body) > 300 else r.draft_body
        ),
        processed_at=r.processed_at.isoformat(),
    )


def _do_scan():
    global _last_scan_at, _last_results, _total_scans
    global _total_emails_processed, _scan_in_progress, _last_scan_error

    _scan_in_progress = True
    _last_scan_error = None
    try:
        model = os.getenv("OPENAI_MODEL", "gpt-4o")
        api_key = os.getenv("OPENAI_API_KEY")
        results = run_scan(openai_api_key=api_key, openai_model=model)
        _last_results = results
        _last_scan_at = datetime.now(timezone.utc)
        _total_scans += 1
        _total_emails_processed += len(results)
        logger.info("Scan complete — %d email(s) processed.", len(results))
    except Exception as exc:
        _last_scan_error = str(exc)
        logger.exception("Scan failed: %s", exc)
    finally:
        _scan_in_progress = False


# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────

@app.get("/", response_model=AppInfo, summary="App info & health check")
def root():
    """Returns application metadata and current uptime."""
    return AppInfo(
        name="Gmail POS Inquiry Bot",
        version="1.0.0",
        description=app.description,
        started_at=_APP_START.isoformat(),
        uptime_seconds=round(_uptime(), 1),
    )


@app.get("/status", response_model=StatusResponse, summary="Runtime statistics")
def status():
    """Returns live runtime statistics including scan history and current state."""
    return StatusResponse(
        status="ok",
        uptime_seconds=round(_uptime(), 1),
        total_scans=_total_scans,
        total_emails_processed=_total_emails_processed,
        last_scan_at=_last_scan_at.isoformat() if _last_scan_at else None,
        scan_in_progress=_scan_in_progress,
        last_scan_error=_last_scan_error,
    )


@app.get("/config", response_model=ConfigResponse, summary="Active configuration")
def config():
    """Shows the active configuration. API keys are never exposed — only whether they are set."""
    return ConfigResponse(
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o"),
        openai_api_key_set=bool(os.getenv("OPENAI_API_KEY")),
        gmail_credentials_path=os.getenv("GMAIL_CREDENTIALS_PATH", "credentials.json"),
        gmail_token_path=os.getenv("GMAIL_TOKEN_PATH", "token.json"),
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
    )


@app.post("/scan", response_model=ScanTriggerResponse, summary="Trigger a Gmail scan")
def trigger_scan(background_tasks: BackgroundTasks):
    """
    Fires a Gmail scan in the background and returns immediately.
    Poll GET /results once the scan finishes (usually a few seconds).
    Returns 409 if a scan is already running.
    """
    if _scan_in_progress:
        raise HTTPException(
            status_code=409,
            detail="A scan is already in progress. Please wait and try again.",
        )
    background_tasks.add_task(_do_scan)
    scan_id = f"scan-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    return ScanTriggerResponse(
        message="Scan started in the background. Check GET /results shortly.",
        scan_id=scan_id,
    )


@app.get(
    "/results",
    response_model=list[ScanResultResponse],
    summary="Results from the last scan",
)
def list_results():
    """
    Returns all results from the most recent scan.
    Each result contains email metadata, sentiment analysis, and a draft preview.
    """
    return [_to_response(i, r) for i, r in enumerate(_last_results)]


@app.get(
    "/results/{result_id}",
    response_model=ScanResultResponse,
    summary="Single scan result detail",
)
def get_result(result_id: int):
    """Returns full detail for one result by its 0-based index."""
    if result_id < 0 or result_id >= len(_last_results):
        raise HTTPException(
            status_code=404,
            detail=f"Result {result_id} not found. "
                   f"Last scan produced {len(_last_results)} result(s).",
        )
    return _to_response(result_id, _last_results[result_id])


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "api:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=bool(os.getenv("DEV", "")),
    )
