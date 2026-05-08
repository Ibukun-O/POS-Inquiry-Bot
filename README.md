# POS Inquiry Bot

A Python service that scans your Gmail inbox for unread "POS Inquiry" emails, analyzes sentiment and draft a professional reply, saves the draft back to Gmail and then marks the original as read.

A FastAPI backend wraps the scanner so you can trigger scans via HTTP or run
automatic polling on a configurable interval.

---

## Project Structure

```
pos_inquiry_bot/
├── .env.example          # Copy to .env and fill in credentials
├── generate_token.py     # One-time helper to get your Google refresh token
├── gmail_scanner.py      # Core scanner logic (runs standalone too)
├── main.py               # FastAPI app
├── requirements.txt
└── README.md
```

---

## 1. Prerequisites

- Python 3.10+
- A Google Cloud project with the **Gmail API** enabled
- An **Anthropic API key**

---

## 2. Google Cloud Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/).
2. Create (or select) a project → **APIs & Services → Enable APIs**.
3. Search for **Gmail API** and enable it.
4. Go to **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**.
5. Choose **Desktop app** as the application type.
6. Download or note your **Client ID** and **Client Secret**.

---

## 3. Install Dependencies

```bash
pip install -r requirements.txt
```

---

## 4. Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env`:

```env
GOOGLE_CLIENT_ID=your_client_id
GOOGLE_CLIENT_SECRET=your_client_secret
GOOGLE_REFRESH_TOKEN=          # fill in after step 5
ANTHROPIC_API_KEY=your_anthropic_key
EMAIL_SUBJECT_FILTER=POS Inquiry
LOG_LEVEL=INFO
SCAN_INTERVAL_SECONDS=300      # auto-scan interval (seconds)
```

---

## 5. Generate Your Google Refresh Token (one-time)

Run the helper script **once** on a machine with a browser:

```bash
python generate_token.py
```

A browser window opens for Google login. After authorising, the script prints:

```
GOOGLE_REFRESH_TOKEN=1//04xxxxxxxxxxxxxxxxx
```

Paste this value into your `.env` file. After this, the app runs fully headless.

---

## 6. Run the API Server

```bash
python main.py
```

Or with uvicorn directly:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Interactive API docs are available at: **http://localhost:8000/docs**

---

## 7. API Endpoints

| Method | Path           | Description                                      |
|--------|----------------|--------------------------------------------------|
| GET    | `/`            | Health check & quick status                      |
| POST   | `/scan`        | Trigger a one-off scan (async, returns 202)      |
| GET    | `/status`      | Get last scan results and totals                 |
| POST   | `/scan/start`  | Start auto-scan loop (`interval_seconds` body)   |
| POST   | `/scan/stop`   | Stop auto-scan loop                              |

### Example: trigger a manual scan

```bash
curl -X POST http://localhost:8000/scan
```

### Example: start auto-scan every 2 minutes

```bash
curl -X POST http://localhost:8000/scan/start \
  -H "Content-Type: application/json" \
  -d '{"interval_seconds": 120}'
```

### Example: check results

```bash
curl http://localhost:8000/status
```

---

## 8. Run the Scanner Standalone (no API)

```bash
python gmail_scanner.py
```

Outputs a JSON summary to stdout.

---

## 9. Knowledge Base Customisation

Edit the `KNOWLEDGE_BASE` string inside `gmail_scanner.py` to add more product details,
FAQs, pricing tiers, or tone guidelines.

---

## Security Notes

- Never commit your `.env` file – it is in `.gitignore`.
- The refresh token grants long-lived Gmail access; treat it like a password.
- Rotate your Anthropic API key regularly from [console.anthropic.com](https://console.anthropic.com).

