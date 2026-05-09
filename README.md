# 📬 Gmail POS Inquiry Bot

> A headless Python service that monitors your Gmail inbox for unread **POS Inquiry** emails, analyses customer sentiment with **OpenAI GPT-4o**, drafts a professional reply, saves it to Gmail Drafts, and marks the original as read — all automatically.

---

## ✨ Features

- 🔍 **Inbox scanning** — Queries Gmail for `is:unread subject:"POS Inquiry"` on demand
- 🧠 **Sentiment analysis** — Classifies each email as `positive`, `neutral`, or `negative` with a numeric score (−1.0 → +1.0) and a one-line summary
- ✍️ **AI-generated replies** — GPT-4o writes a context-aware, empathetic support response tailored to the detected sentiment
- 📝 **Draft saving** — Replies are saved as Gmail Drafts inside the original thread (never auto-sent)
- ✅ **Mark as read** — Processed emails are marked read so they're never handled twice
- 🌐 **FastAPI service** — Trigger scans and inspect results over HTTP with a fully documented REST API
- 🔒 **Minimal OAuth scopes** — Only requests the Gmail permissions it actually needs

---

## 🗂 Project Structure

```
pos_inquiry_bot/
├── auth.py           # Google OAuth2 helper — token caching & refresh
├── scanner.py        # Core pipeline: Gmail fetch → OpenAI → Draft → Mark read
├── main.py           # One-shot CLI entry point
├── api.py            # FastAPI web service
├── requirements.txt  # Python dependencies
├── .env.example      # Environment variable template
├── .gitignore        # Excludes secrets and build artefacts
├── HOW_TO_USE.txt    # Detailed setup & usage guide
└── README.md         # This file
```

---

## ⚡ Quick Start

### 1. Clone & install

```bash
git clone <your-repo-url>
cd pos_inquiry_bot

python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o        # or gpt-4o-mini for lower cost
```

### 3. Add Google credentials

Follow the [Google Cloud Setup](#google-cloud-setup) section below, then place `credentials.json` in the project root.

### 4. Run

```bash
# One-shot CLI scan
python main.py

# Or start the HTTP API
python api.py
```

On the **first run**, a browser window will open for Gmail OAuth consent. After you approve, `token.json` is cached and all future runs are silent.

---

## 🌐 API Reference

Start the server:

```bash
python api.py          # http://localhost:8000
```

Interactive docs available at **`http://localhost:8000/docs`**

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Health check — app name, version, uptime |
| `GET` | `/status` | Runtime stats — scan count, emails processed, last scan time, errors |
| `GET` | `/config` | Active config — model, paths, API key presence (never the key itself) |
| `POST` | `/scan` | Trigger a Gmail scan in the background; returns `scan_id` immediately |
| `GET` | `/results` | All results from the most recent scan |
| `GET` | `/results/{id}` | Full detail for a single result (0-based index) |

### Example session

```bash
# Health check
curl http://localhost:8000/

# Trigger a scan
curl -X POST http://localhost:8000/scan

# Retrieve results (after a few seconds)
curl http://localhost:8000/results | python -m json.tool

# Drill into result #0
curl http://localhost:8000/results/0 | python -m json.tool
```

### Sample `/results` response

```json
[
  {
    "result_id": 0,
    "email": {
      "msg_id": "18f3c2a1b9d4e7f2",
      "sender": "merchant@example.com",
      "subject": "POS Inquiry — terminal keeps freezing",
      "received_at": "2025-05-08T14:22:00+00:00",
      "body_preview": "Hi, our POS terminal has been freezing every morning..."
    },
    "sentiment": {
      "label": "negative",
      "score": -0.78,
      "summary": "Customer is frustrated with repeated terminal crashes."
    },
    "draft_id": "r1234567890abcdef",
    "draft_preview": "Hi there,\n\nI'm sorry to hear you're experiencing issues...",
    "processed_at": "2025-05-08T14:23:05+00:00"
  }
]
```

---

## ☁️ Google Cloud Setup

> One-time setup to get your `credentials.json`.

1. Open [Google Cloud Console](https://console.cloud.google.com) and create or select a project.
2. Go to **APIs & Services → Library**, search for **Gmail API**, and click **Enable**.
3. Go to **APIs & Services → OAuth consent screen**:
   - User Type: **External**
   - Fill in app name and email fields.
   - Under **Test users**, add your Gmail address.
4. Go to **APIs & Services → Credentials → Create Credentials → OAuth client ID**:
   - Application type: **Desktop app**
   - Download the JSON file and rename it to **`credentials.json`**.
5. Place `credentials.json` in the project root.

> ⚠️ Never commit `credentials.json` or `token.json` to version control.

**OAuth scopes requested (minimum required):**

| Scope | Purpose |
|-------|---------|
| `gmail.readonly` | Read email bodies |
| `gmail.compose` | Create draft replies |
| `gmail.modify` | Mark emails as read |

---

## 🤖 OpenAI Model Selection

Set `OPENAI_MODEL` in `.env`:

| Model | Quality | Speed | Cost |
|-------|---------|-------|------|
| `gpt-4o` *(default)* | ⭐⭐⭐⭐⭐ | Fast | ~$0.002–0.004 / email |
| `gpt-4o-mini` | ⭐⭐⭐⭐ | Faster | ~$0.0002–0.0005 / email |

Each email triggers **two API calls**: one for sentiment analysis, one for reply generation.

---

## 🕒 Scheduled Scanning

**Linux / macOS (cron)** — scan every 30 minutes:

```cron
*/30 * * * * cd /path/to/pos_inquiry_bot && .venv/bin/python main.py >> /var/log/pos_bot.log 2>&1
```

**Windows (Task Scheduler):**

- Trigger: Daily, repeat every 30 minutes
- Action: Run `.venv\Scripts\python.exe main.py`

---

## 🔒 Security Notes

- `credentials.json` and `token.json` grant Gmail access — keep them out of git (`.gitignore` covers this).
- `OPENAI_API_KEY` lives only in `.env` — never hard-coded.
- The FastAPI service has **no authentication by default**. For production, add an API key header or place it behind a reverse proxy (nginx, Caddy) with auth.
- The `/config` endpoint exposes only a boolean for whether the API key is set — never the key value.

---

## 🛠 Troubleshooting

| Problem | Fix |
|---------|-----|
| `credentials.json not found` | Complete Google Cloud Setup and place the file in the project root |
| "Google hasn't verified this app" | Add your Gmail as a **Test User** in the OAuth consent screen |
| `Token has been expired or revoked` | Delete `token.json` and re-run `python main.py` |
| No emails found | Confirm the subject contains exactly `POS Inquiry` and emails are still unread |
| `OpenAI AuthenticationError` | Verify `OPENAI_API_KEY` is correct and has available credits |
| `409 Conflict` on `POST /scan` | A scan is already running — wait a few seconds and retry |

---

## 🚀 Extending the Bot

- **Change the subject filter** — edit the `query` string in `scanner.fetch_unread_pos_emails()`
- **Customise the reply persona** — edit `_REPLY_SYSTEM` in `scanner.py` (company name, agent name, tone)
- **Auto-send replies** — replace `create_draft()` with `service.users().messages().send()` *(review quality first!)*
- **Persist results** — swap the in-memory list in `api.py` for SQLite (SQLModel) or PostgreSQL
- **Scheduled API scanning** — add APScheduler to `api.py`'s lifespan to poll Gmail every N minutes

---

## 📄 License

MIT — free to use, modify, and distribute.

---

> 💡 **Tip:** Always review your Gmail Drafts before sending. The bot is designed to assist, not replace, human judgement.
