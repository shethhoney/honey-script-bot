# Technical Design Document
## Honey Script Bot — WhatsApp Reel Script Generator

**Version:** 1.0
**Date:** 2026-04-02
**Author:** Honey Sheth
**Stack:** Python / Flask / Twilio / Anthropic / Groq

---

## 1. System Overview

Honey Script Bot is a stateful, multi-turn WhatsApp chatbot built on Flask. It receives inbound WhatsApp messages via Twilio webhooks, processes briefs through a structured conversation flow, calls the Claude Sonnet API to generate reel scripts, and sends responses back via Twilio. Audio inputs are transcribed via Groq Whisper. File inputs (PDF, DOCX, images) are processed before being passed to the AI layer.

### Architecture Diagram

```
WhatsApp User
      │
      ▼
  Twilio (WhatsApp gateway)
      │  POST /webhook
      ▼
  Flask App (app.py)
      │
      ├── Media handler
      │     ├── Audio → Groq Whisper → text
      │     ├── PDF → PyPDF2 → text
      │     ├── DOCX → mammoth → text
      │     └── Image → base64 → Claude vision
      │
      ├── State machine (shelve)
      │     └── Per-user state: step, brief, format, concepts, last_script, last_caption
      │
      ├── Conversation router
      │     ├── Greetings / help / cancel
      │     ├── Format selection
      │     ├── Sub-format selection
      │     ├── Concept selection
      │     └── Refinement
      │
      └── AI layer (Anthropic Claude Sonnet 4)
            ├── generate_concepts()
            ├── generate_script()
            ├── refine_script()
            └── extract_email_brief()
                      │
                      ▼
              Twilio (outbound messages)
                      │
                      ▼
              WhatsApp User
```

---

## 2. Tech Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| Runtime | Python | 3.11+ |
| Web framework | Flask | 2.3.3 |
| WSGI server | Gunicorn | 21.2.0 |
| WhatsApp gateway | Twilio Messaging API | SDK 8.2.0 |
| AI — script generation | Anthropic Claude Sonnet 4 (`claude-sonnet-4-20250514`) | SDK 0.18.1 |
| AI — audio transcription | Groq Whisper (`whisper-large-v3`) | REST API |
| PDF extraction | PyPDF2 | 3.0.1 |
| DOCX extraction | mammoth | 1.6.0 |
| State persistence | Python `shelve` | stdlib |
| HTTP client | requests / httpx | 2.28.2 / 0.23.3 |
| Deployment | Railway (primary) / Render (fallback) | — |
| Build system | Nixpacks | — |

---

## 3. File Structure

```
honey-script-bot/
├── app.py              # All application logic (single-file architecture)
├── requirements.txt    # Python dependencies
├── Procfile            # Process declaration for Heroku-compatible platforms
├── railway.toml        # Railway deployment config (Nixpacks, Gunicorn, healthcheck)
├── nixpacks.toml       # Build config
├── render.yaml         # Render.com deployment config
├── runtime.txt         # Python version pin
├── .python-version     # Python version for local dev
└── SETUP_GUIDE.md      # End-user deployment guide
```

Single-file architecture (`app.py`) — all routes, state management, AI calls, media processing, and helper utilities are co-located. Appropriate for a single-user personal tool; no separation needed at this scale.

---

## 4. Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key for Claude |
| `TWILIO_ACCOUNT_SID` | Yes | Twilio account SID (starts with `AC...`) |
| `TWILIO_AUTH_TOKEN` | Yes | Twilio auth token |
| `TWILIO_WHATSAPP_NUMBER` | Yes | Sender number in format `whatsapp:+1XXXXXXXXXX` |
| `GROQ_API_KEY` | Yes | Groq API key for Whisper transcription |
| `RENDER_EXTERNAL_URL` | Optional | Used by self-ping; auto-set on Render |
| `PORT` | Optional | HTTP port; defaults to 5000 |

---

## 5. State Machine

State is persisted per phone number using Python's `shelve` module at `/tmp/honey_state`. All reads and writes are protected by a `threading.Lock()`.

### State Schema

```python
{
    "step": str,              # Current conversation step (see states below)
    "brief": str,             # Extracted brief text
    "format": str,            # Selected top-level format key ("immbt" | "event" | "collab")
    "subformat_label": str,   # Full sub-format label string passed to Claude
    "concepts": list[str],    # List of 4 generated concept strings
    "chosen_concept": str,    # The concept selected by user
    "last_script": str,       # Most recently generated script
    "last_caption": str,      # Most recently generated caption
}
```

### State Transitions

```
idle
  │── [greeting] ──────────────────────────────────────────────→ idle (reset)
  │── [new brief received] ────────────────────────────────────→ awaiting_format
  │── [short message + last_script exists] ──────────────────→ awaiting_refine

awaiting_format
  │── [1|2|3 received] ──────────────────────────────────────→ awaiting_subformat

awaiting_subformat
  │── [valid sub-option received] ────────────────────────────→ generating_concepts
                                                                 (async thread starts)
generating_concepts
  │── [concepts ready] ────────────────────────────────────────→ awaiting_concept

awaiting_concept
  │── [1|2|3|4 received] ─────────────────────────────────────→ generating
  │── ["all" received] ──────────────────────────────────────→ generating
                                                                 (async thread starts)
generating
  │── [script delivered] ──────────────────────────────────────→ idle

awaiting_refine
  │── [feedback text received] ────────────────────────────────→ generating
  │── [voice note received] ───────────────────────────────────→ generating

idle (with last_script)
  │── [voice note received] → route as refine if has_script=True
```

---

## 6. API Integrations

### 6.1 Anthropic Claude Sonnet 4

**Model:** `claude-sonnet-4-20250514`

Used for four distinct operations:

| Function | Endpoint | Max Tokens | Notes |
|----------|----------|------------|-------|
| `generate_concepts()` | `messages.create` | 600 | Returns 4 concepts in structured format |
| `generate_script()` — text/DOCX/PDF | `messages.create` | 2200 | System prompt + user prompt |
| `generate_script()` — image | `messages.create` | 2200 | Vision: base64 image + text |
| `generate_script()` — multiple (count > 1) | `messages.create` | 4000 | All 4 variations in one call |
| `refine_script()` | `messages.create` | 2200 | Includes previous script + feedback |
| `extract_email_brief()` | `messages.create` | 400 | No system prompt; structured extraction |

**System Prompt:** ~1,800-token voice document encoding Honey's style, cues, emotional arc, format guides, and hard rules. Applied to all script/concept/refinement calls.

**Output parsing:** Script and caption are extracted via regex:
```python
re.search(r'\[REEL SCRIPT\]([\s\S]*?)(?=\[CAPTION\]|$)', raw)
re.search(r'\[CAPTION\]([\s\S]*?)$', raw)
```

### 6.2 Groq Whisper

**Model:** `whisper-large-v3`
**Endpoint:** `https://api.groq.com/openai/v1/audio/transcriptions`
**Supported formats:** `.ogg`, `.m4a`, `.mp3`, `.webm`
**Language:** `en` (hardcoded)

Flow:
1. Download audio from Twilio media URL (authenticated GET)
2. Write to `tempfile.NamedTemporaryFile` with correct extension
3. POST to Groq transcription endpoint
4. Delete temp file
5. Return transcribed text string

### 6.3 Twilio

**Inbound:** Twilio POSTs to `/webhook` with form fields: `From`, `Body`, `NumMedia`, `MediaUrl0`, `MediaContentType0`

**Outbound — two methods:**
- **Synchronous (TwiML):** `MessagingResponse()` returned in webhook response. Used for immediate short replies (greetings, menus, confirmations).
- **Asynchronous (REST):** `twilio_client.messages.create()` called from background threads. Used for script delivery and progress messages.

**Message chunking:** All text > 1,500 characters is split into chunks with 0.5s delays between sends.

---

## 7. Media Processing

### 7.1 PDF Extraction
```python
PyPDF2.PdfReader(io.BytesIO(data))
"\n".join(page.extract_text() or "" for page in reader.pages)
```
Limitation: Password-protected or scanned (image-only) PDFs will return empty text.

### 7.2 DOCX Extraction
```python
mammoth.extract_raw_text(io.BytesIO(data)).value
```
Strips all formatting; returns plain text.

### 7.3 Image Extraction
Images are base64-encoded and passed directly to Claude's vision API. The brief text is stored as `[IMAGE:base64data:content_type]` and decoded at generation time.

### 7.4 Email Detection
Heuristic detection using keyword matching:
```python
email_signals = ["from:", "subject:", "dear honey", "we would like",
                 "collaboration", "partnership", "deliverables",
                 "compensation", "deadline", "fwd:", "------"]
```
Match threshold: ≥ 2 signals → treated as email, structured extraction triggered.

---

## 8. Concurrency Model

All AI generation and media processing runs in **daemon background threads** to avoid Twilio's 15-second webhook timeout. The webhook handler returns an immediate TwiML acknowledgment; results are delivered asynchronously via Twilio REST API.

### Progress Messages
Each background thread spawns a secondary "progress" thread:
- Concepts: fires after 15 seconds if not complete
- Scripts: fires after 20 seconds if not complete
- A `done` dict flag (`{"value": False}`) shared via closure prevents duplicate messages

### Thread Safety
All state reads/writes use a module-level `threading.Lock()`:
```python
state_lock = threading.Lock()

def get_state(number):
    with state_lock:
        with shelve.open("/tmp/honey_state") as db:
            return dict(db.get(number, {"step": "idle"}))
```
Shelve is not thread-safe by itself; the lock ensures serialised access.

---

## 9. Deployment

### Railway (Primary)

```toml
# railway.toml
[build]
builder = "NIXPACKS"

[deploy]
startCommand = "gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120"
healthcheckPath = "/health"
healthcheckTimeout = 30
restartPolicyType = "ON_FAILURE"
```

- 2 Gunicorn workers
- 120s worker timeout (accommodates slow AI responses)
- `/health` endpoint returns `"ok", 200`

### Self-Ping (Anti-Sleep)
A daemon thread pings `/health` every 4 minutes to prevent Render's free-tier sleep:
```python
def self_ping():
    time.sleep(30)  # initial delay
    url = os.environ.get("RENDER_EXTERNAL_URL", "https://honey-script-bot.onrender.com")
    while True:
        requests.get(url.rstrip("/") + "/health", timeout=10)
        time.sleep(240)
```

---

## 10. Routes

| Route | Method | Description |
|-------|--------|-------------|
| `/webhook` | POST | Main Twilio webhook — all inbound WhatsApp messages |
| `/health` | GET | Health check — returns `"ok"` |

---

## 11. Format & Subformat Taxonomy

### Top-Level Formats
| Key | Label |
|-----|-------|
| `immbt` | Instagram Made Me Buy This |
| `event` | Event coverage |
| `collab` | Brand collaboration |

### Sub-formats
| Parent | Key | Label |
|--------|-----|-------|
| immbt | 1 | Single product discovery |
| immbt | 2 | Viral hype check, sceptic who gets won over |
| immbt | 3 | Personal resistance resolved by product |
| event | 1 | Brand booth or launch |
| event | 2 | Destination or full day travel experience |
| event | 3 | Community or group event with friends |
| collab | 1 | Routine or tutorial, step by step with sensory detail |
| collab | 2 | Personal narrative, emotional hook, product as solution |
| collab | 3 | Multi-product haul, one editorial hook |
| collab | 4 | Gifting or occasion, relationship narrative first |
| collab | 5 | Platform or retail collab |

---

## 12. Known Limitations & Technical Debt

| Item | Detail |
|------|--------|
| `/tmp` state | Shelve stored in `/tmp` — wiped on Railway/Render restarts. Users must re-send briefs after a restart. |
| Single-file architecture | All logic in `app.py`. Fine for current scale; would need splitting if features expand significantly. |
| No retry logic | Failed API calls (Anthropic/Groq) surface as user-facing error messages with no auto-retry. |
| No request validation | Twilio webhook signature is not validated — potential for unauthenticated POST abuse. |
| Audio language hardcoded | Groq Whisper set to `language: "en"` — Hindi/Hinglish voice notes may transcribe less accurately. |
| Image storage | Base64 image data stored in shelve state — large images could cause state bloat. |
| No logging/monitoring | Print statements only; no structured logging or error alerting. |

---

## 13. Security Considerations

- All secrets stored as environment variables — never hardcoded
- Twilio media downloads use HTTP Basic Auth (SID + Auth Token)
- No Twilio request signature validation on `/webhook` — **recommended to add** using `twilio.request_validator`
- No user authentication beyond phone number identity (provided by Twilio)
- `/health` endpoint is publicly accessible — intentional (no sensitive data exposed)

---

## 14. Cost Model

| Service | Unit cost | Estimated monthly (regular use) |
|---------|-----------|--------------------------------|
| Anthropic Claude Sonnet 4 | ~$0.01–0.03 / script | $5–15 |
| Groq Whisper | Free tier / minimal | ~$0 |
| Twilio WhatsApp sandbox | Free | $0 |
| Twilio production number | $1/month + $0.005/msg | $3–8 |
| Railway | Free 500hrs / $5 after | $0–5 |
| **Total** | | **~$6–28/month** |

---

## 15. Future Improvements

- **Twilio signature validation** on `/webhook` for security
- **Persistent state store** (Redis or SQLite) to survive restarts
- **Structured logging** (e.g. Python `logging` module with Render log drains)
- **Script history** — retrieve previously generated scripts by reference
- **Auto-format detection** — infer IMMBT/Event/Collab from brief content without menu
- **Hindi/Hinglish Whisper tuning** — pass `language: "hi"` or allow auto-detect for mixed-language voice notes
- **Twilio production number** upgrade from sandbox
