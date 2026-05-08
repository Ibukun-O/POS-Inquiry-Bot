"""
main.py – FastAPI backend for the POS Inquiry email bot
---------------------------------------------------------
Endpoints:
  GET  /             → health check
  POST /scan         → trigger a full inbox scan immediately
  GET  /status       → last scan summary
  POST /scan/start   → start automatic background scanning (interval configurable)
  POST /scan/stop    → stop automatic background scanning
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from gmail_scanner import scan_and_respond

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
)
logger = logging.getLogger("pos_api")

SCAN_INTERVAL_SECONDS = int(os.getenv("SCAN_INTERVAL_SECONDS", "300"))  # default: 5 min

# ---------------------------------------------------------------------------
# In-memory state
# ---------------------------------------------------------------------------

state = {
    "last_scan_time": None,
    "last_scan_summary": None,
    "is_scanning": False,
    "auto_scan_running": False,
    "total_processed_all_time": 0,
    "total_errors_all_time": 0,
}

auto_scan_task: Optional[asyncio.Task] = None

# ---------------------------------------------------------------------------
# Background auto-scan loop
# ---------------------------------------------------------------------------

async def auto_scan_loop(interval: int):
    """Runs scan_and_respond() every `interval` seconds in the background."""
    logger.info(f"Auto-scan started. Interval: {interval}s")
    state["auto_scan_running"] = True

    while True:
        try:
            await run_scan_async()
        except Exception as e:
            logger.error(f"Auto-scan iteration error: {e}")

        await asyncio.sleep(interval)


async def run_scan_async() -> dict:
    """Run the blocking gmail_scanner in a thread pool so it doesn't block the event loop."""
    if state["is_scanning"]:
        logger.warning("Scan already in progress. Skipping.")
        return {"skipped": True, "reason": "scan_in_progress"}

    state["is_scanning"] = True
    try:
        loop = asyncio.get_event_loop()
        summary = await loop.run_in_executor(None, scan_and_respond)
        state["last_scan_time"] = datetime.utcnow().isoformat() + "Z"
        state["last_scan_summary"] = summary
        state["total_processed_all_time"] += summary.get("processed", 0)
        state["total_errors_all_time"] += summary.get("errors", 0)
        logger.info(f"Scan complete: {summary}")
        return summary
    finally:
        state["is_scanning"] = False


# ---------------------------------------------------------------------------
# FastAPI app lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("POS Inquiry Bot API starting up…")
    yield
    # Shutdown: cancel auto-scan if running
    global auto_scan_task
    if auto_scan_task and not auto_scan_task.done():
        auto_scan_task.cancel()
        logger.info("Auto-scan task cancelled on shutdown.")
    state["auto_scan_running"] = False
    logger.info("POS Inquiry Bot API shut down.")


app = FastAPI(
    title="POS Inquiry Bot API",
    description="Gmail scanner that processes POS Inquiry emails and drafts AI responses.",
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

class AutoScanConfig(BaseModel):
    interval_seconds: int = SCAN_INTERVAL_SECONDS


class ScanResponse(BaseModel):
    triggered_at: str
    summary: dict


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", tags=["Health"])
async def health_check():
    """API health check and quick status overview."""
    return {
        "status": "ok",
        "service": "POS Inquiry Bot",
        "is_scanning": state["is_scanning"],
        "auto_scan_running": state["auto_scan_running"],
        "last_scan_time": state["last_scan_time"],
        "total_processed_all_time": state["total_processed_all_time"],
    }


@app.post("/scan", tags=["Scan"], response_model=ScanResponse)
async def trigger_scan(background_tasks: BackgroundTasks):
    """
    Manually trigger a one-off inbox scan.
    The scan runs asynchronously; results are stored in /status.
    """
    if state["is_scanning"]:
        raise HTTPException(status_code=409, detail="A scan is already in progress.")

    async def _run():
        await run_scan_async()

    background_tasks.add_task(_run)

    return JSONResponse(
        status_code=202,
        content={
            "triggered_at": datetime.utcnow().isoformat() + "Z",
            "message": "Scan triggered. Check /status for results.",
        },
    )


@app.get("/status", tags=["Scan"])
async def get_status():
    """Return the result of the last completed scan."""
    return {
        "is_scanning": state["is_scanning"],
        "auto_scan_running": state["auto_scan_running"],
        "last_scan_time": state["last_scan_time"],
        "last_scan_summary": state["last_scan_summary"],
        "total_processed_all_time": state["total_processed_all_time"],
        "total_errors_all_time": state["total_errors_all_time"],
    }


@app.post("/scan/start", tags=["Auto Scan"])
async def start_auto_scan(config: AutoScanConfig):
    """
    Start a background auto-scan loop that fires every `interval_seconds`.
    Default interval is 300 s (5 minutes).
    """
    global auto_scan_task

    if state["auto_scan_running"]:
        raise HTTPException(status_code=409, detail="Auto-scan is already running.")

    interval = max(config.interval_seconds, 30)  # enforce minimum 30s
    auto_scan_task = asyncio.create_task(auto_scan_loop(interval))

    return {
        "status": "started",
        "interval_seconds": interval,
        "message": f"Auto-scan will run every {interval} seconds.",
    }


@app.post("/scan/stop", tags=["Auto Scan"])
async def stop_auto_scan():
    """Stop the background auto-scan loop."""
    global auto_scan_task

    if not state["auto_scan_running"]:
        raise HTTPException(status_code=409, detail="Auto-scan is not running.")

    if auto_scan_task and not auto_scan_task.done():
        auto_scan_task.cancel()

    state["auto_scan_running"] = False

    return {"status": "stopped", "message": "Auto-scan has been stopped."}


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
