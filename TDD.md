# Technical Design Document — Honey Script Bot

**Version:** 2.0
**Date:** 2025-07-09
**Author:** Auto-generated from codebase analysis
**Status:** Production

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Tech Stack](#2-tech-stack)
3. [Architecture & File Structure](#3-architecture--file-structure)
4. [Environment Variables](#4-environment-variables)
5. [State Machine](#5-state-machine)
6. [API Integrations](#6-api-integrations)
7. [Script Library & Learning System](#7-script-library--learning-system)
8. [Media Processing](#8-media-processing)
9. [Concurrency Model](#9-concurrency-model)
10. [Storage & Persistence](#10-storage--persistence)
11. [Deployment](#11-deployment)
12. [Routes](#12-routes)
13. [Format/Subformat Taxonomy](#13-formatsubformat-taxonomy)
14. [Security Considerations](#14-security-considerations)
15. [Cost Model](#15-cost-model)
16. [Known Limitations](#16-known-limitations)
17. [Future Improvements](#17-future-improvements)

---

## 1. System Overview

The Honey Script Bot is a single-user, WhatsApp-based AI assistant purpose-built for **Honey Sheth**, an Indian lifestyle, beauty, and travel content creator. The bot accepts brand briefs in multiple formats (text, PDF, Word, image, voice note, forwarded email), guides the user through a structured format-selection flow, generates creative concept options, produces full Instagram Reel scripts and captions in Honey's trained voice, and supports iterative refinement via text or voice feedback.

### Core Workflow

```
Brand Brief → Format Selection → Subformat Selection → Concept Generation →
Concept Selection → Script + Caption Generation → Refinement Loop → Save to Library
```

### Key Design Goals

| Goal | Implementation |
|---|---|
| **Voice fidelity** | 37-script-trained system prompt with explicit voice rules, emotional arc, and reference quotes |
| **Self-improving** | Approved scripts are saved to a rolling library and injected as few-shot examples into future generations |
| **Multimodal input** | PDF extraction, DOCX parsing, image vision (base64), voice transcription, email parsing |
| **Conversational UX** | WhatsApp-native numbered menu flow with progress indicators and chunked message delivery |
| **Feedback learning** | Refinement instructions are logged and injected into future refine prompts as preference patterns |

---

## 2. Tech Stack

### Runtime & Framework

| Component | Library/Service | Version | Reasoning |
|---|---|---|---|
| Language | Python 3 | (Railway Nixpacks default) | Rapid prototyping; rich ecosystem for AI/NLP |
| Web Framework | Flask | 2.3.3 | Lightweight; sufficient for a single-endpoint webhook server |
| WSGI Server | Gunicorn | 21.2.0 | Production-grade process manager; required for Railway deployment |
| HTTP Adapter | Werkzeug | 2.3.7 | Pinned to match Flask 2.3.x compatibility |

### AI & NLP

| Component | Library/Service | Version/Model | Reasoning |
|---|---|---|---|
| Script Generation | Anthropic Python SDK | 0.89.0 (`claude-opus-4-6`) | Top-tier creative writing quality; vision capability for image briefs |
| Voice Transcription | Groq API (REST) | `whisper-large-v3` | Fast, free-tier Whisper inference; low-latency for conversational UX |

### Messaging

| Component | Library/Service | Version | Reasoning |
|---|---|---|---|
| WhatsApp Gateway | Twilio Python SDK | 8.2.0 | Industry-standard WhatsApp Business API wrapper; handles media URLs and auth |

### Document Processing

| Component | Library/Service | Version | Reasoning |
|---|---|---|---|
| PDF Extraction | PyPDF2 | 3.0.1 | Pure Python; no native dependencies; sufficient for text-based PDF briefs |
| DOCX Extraction | Mammoth | 1.6.0 | Extracts raw text from `.docx` without needing `python-docx`; handles brand brief formatting |

### Infrastructure

| Component | Library/Service | Reasoning |
|---|---|---|
| HTTP Client | Requests 2.31.0 | Media downloads from Twilio CDN; Groq REST API calls |
| Hosting | Railway (Hobby plan) | Simple container deployment with persistent volume support |
| Build System | Nixpacks | Railway's default builder; auto-detects Python and installs from `requirements.txt` |

### Standard Library (Notable Usage)

| Module | Usage |
|---|---|
| `shelve` | Persistent key-value store for per-user conversation state |
| `threading` | Daemon threads for async AI generation (non-blocking webhook responses) |
| `json` | Script library and feedback log serialization |
| `re` | Parsing `[REEL SCRIPT]` / `[CAPTION]` sections and concept blocks from AI output |
| `base64` | Encoding images for Anthropic vision API |
| `io` | In-memory byte streams for PDF/DOCX parsing |
| `tempfile` | Temporary audio files for Groq transcription upload |
| `uuid` | Short IDs for library entries |

---

## 3. Architecture & File Structure

### Repository Structure

```
honey-script-bot/
├── app.py              # Monolithic application — all logic in a single file
├── requirements.txt    # Python dependencies (8 packages)
├── railway.toml        # Railway deployment configuration
└── /data/              # Railway persistent volume (mounted at runtime)
    ├── honey_state.db  # shelve database — conversation state per phone number
    ├── honey_library.json  # Approved script library (max 20 entries)
    └── honey_feedback.json # Refinement feedback log (max 30 entries)
```

### Architectural Pattern

The application follows a **monolithic single-file architecture** with clear internal sections:

```
┌─────────────────────────────────────────────────────────┐
│                       app.py                            │
├─────────────────────────────────────────────────────────┤
│  1. Configuration & Environment Validation              │
│  2. Persistent Storage (state, library, feedback)       │
│  3. System Prompt & Format Definitions                  │
│  4. Messaging Helpers (send, chunk)                     │
│  5. Media Helpers (download, transcribe, extract)       │
│  6. AI Generation Functions (concepts, script, refine)  │
│  7. Background Workers (threaded async processors)      │
│  8. Webhook Handler (Flask route — state machine)       │
│  9. Health Check Endpoint                               │
└─────────────────────────────────────────────────────────┘
```

### Request Flow

```
WhatsApp User
     │
     ▼
Twilio WhatsApp API
     │ (HTTP POST with form data)
     ▼
/webhook (Flask route)
     │
     ├─ Synchronous: Validate input, update state, return TwiML
     │
     └─ Asynchronous (daemon thread): AI generation → Twilio send
           │
           ├─ Anthropic API (concepts / scripts / refinement)
           ├─ Groq API (voice transcription)
           └─ Twilio API (send result messages)
```

---

## 4. Environment Variables

All five variables are validated at startup. If any is missing, the application raises `RuntimeError` and refuses to boot.

| Variable | Description | Used By |
|---|---|---|
| `ANTHROPIC_API_KEY` | API key for Anthropic Claude. Used for all script generation, concept ideation, refinement, and email brief extraction. | `anthropic.Anthropic()` client |
| `TWILIO_ACCOUNT_SID` | Twilio Account SID. Used for REST API authentication (sending messages) and HTTP Basic Auth when downloading media from Twilio CDN. | `twilio.rest.Client()`, `requests.get(auth=...)` |
| `TWILIO_AUTH_TOKEN` | Twilio Auth Token. Paired with Account SID for all Twilio operations. | `twilio.rest.Client()`, `requests.get(auth=...)` |
| `TWILIO_WHATSAPP_NUMBER` | The Twilio WhatsApp sender number in `whatsapp:+1XXXXXXXXXX` format. Used as the `from_` parameter in all outbound messages. | `twilio_client.messages.create(from_=...)` |
| `GROQ_API_KEY` | API key for Groq's hosted Whisper model. Used for voice note transcription via REST API. | `Authorization: Bearer` header on Groq API calls |

### Optional / Implicit

| Variable | Description |
|---|---|
| `PORT` | Set by Railway at deploy time. Defaults to `5000` if not present. Used by both Flask and the Gunicorn start command. |

---

## 5. State Machine

The bot maintains per-user conversation state keyed by WhatsApp phone number (e.g., `whatsapp:+91XXXXXXXXXX`). State is persisted via Python's `shelve` module.

### State Definitions

| State | Description | Expected Input | Transition |
|---|---|---|---|
| `idle` | Default state. Waiting for a new brief or refinement feedback. | Brief (text/media/voice), greeting, command | → `awaiting_format` (new brief) or → `generating` (refinement shortcut) |
| `awaiting_format` | Brief received. Presenting top-level format menu (IMMBT / Event / Collab). | `1`, `2`, or `3` | → `awaiting_subformat` |
| `awaiting_subformat` | Format chosen. Presenting sub-format menu. | Numeric choice within valid range | → `generating_concepts` |
| `generating_concepts` | AI is generating 4 creative concepts (background thread active). | (No user input expected — transient state) | → `awaiting_concept` |
| `awaiting_concept` | Concepts presented. Waiting for concept selection. | `1`–`4` or `all` | → `generating` |
| `generating` | AI is writing the script (background thread active). | (No user input expected — transient state) | → `idle` (with `last_script` populated) |
| `awaiting_refine` | (Documented in code but primarily entered implicitly; refinement is handled from `idle` when `last_script` exists) | Feedback text or voice note | → `generating` → `idle` |

### State Transition Diagram

```
                          ┌─────────────┐
                          │             │
            greeting/     │    idle     │◄────────────────────────────┐
            cancel        │             │                             │
                          └──────┬──────┘                             │
                                 │                                    │
                    new brief    │    short msg + last_script exists  │
                    (text/media/ │    (refinement shortcut)           │
                     voice/email)│         │                          │
                                 ▼         ▼                          │
                      ┌──────────────┐  ┌───────────┐                │
                      │  awaiting_   │  │generating │────────────────┤
                      │  format      │  │ (refine)  │                │
                      └──────┬───────┘  └───────────┘                │
                             │ 1/2/3                                  │
                             ▼                                        │
                      ┌──────────────┐                                │
                      │  awaiting_   │                                │
                      │  subformat   │                                │
                      └──────┬───────┘                                │
                             │ numeric choice                         │
                             ▼                                        │
                      ┌──────────────┐                                │
                      │ generating_  │                                │
                      │ concepts     │ (background thread)            │
                      └──────┬───────┘                                │
                             │ concepts ready                         │
                             ▼                                        │
                      ┌──────────────┐                                │
                      │  awaiting_   │                                │
                      │  concept     │                                │
                      └──────┬───────┘                                │
                             │ 1-4 or "all"                           │
                             ▼                                        │
                      ┌──────────────┐                                │
                      │  generating  │ (background thread)            │
                      │  (script)    │────────────────────────────────┘
                      └──────────────┘
```

### State Data Schema

Each state entry is a Python dictionary stored in `shelve`:

```python
{
    "step": str,              # Current state name
    "brief": str,             # Extracted brief text
    "format": str,            # Top-level format key: "immbt" | "event" | "collab"
    "subformat_label": str,   # Human-readable subformat description
    "concepts": list[str],    # Generated concept options (up to 4)
    "chosen_concept": str,    # Selected concept text
    "last_script": str,       # Most recent generated script
    "last_caption": str,      # Most recent generated caption
}
```

### Implicit Refinement Detection

When in `idle` state with a populated `last_script`, the bot applies heuristic refinement detection:

- **Short message** (≤300 chars) without brief-like keywords → treated as refinement feedback
- **Long message** (>300 chars) or contains brief signal words (`brief`, `brand`, `product`, `collab`, `campaign`, `launch`, `event`, `partnership`) → treated as a new brief

---

## 6. API Integrations

### 6.1 Anthropic — Claude claude-opus-4-6

**SDK:** `anthropic` Python package v0.89.0
**Model:** `claude-opus-4-6` (used for all generation endpoints)

| Function | Purpose | Max Tokens | System Prompt |
|---|---|---|---|
| `generate_concepts()` | Generate 4 creative concept options | 600 | Full `SYSTEM_PROMPT` |
| `generate_script()` (single) | Write one script + caption | 2,200 | Full `SYSTEM_PROMPT` |
| `generate_script()` (multiple) | Write N variations | 4,000 | Full `SYSTEM_PROMPT` |
| `refine_script()` | Rewrite based on feedback | 2,200 | Full `SYSTEM_PROMPT` |
| `extract_email_brief()` | Parse forwarded brand email | 400 | None (user prompt only) |

**Vision Support:** For image-based briefs, the bot encodes the image as base64 and sends it via Anthropic's multimodal message format:

```python
{
    "type": "image",
    "source": {"type": "base64", "media_type": ct, "data": img_b64}
}
```

**System Prompt Architecture:** A single 1,500+ word `SYSTEM_PROMPT` constant is used for all creative generation. It encodes:
- Voice characteristics and anti-patterns
- Script cue definitions (Visual, PTC, VO, Super)
- 5-step emotional arc structure
- Caption rules and style guidelines
- 11 format-specific guides
- 9 reference voice samples from real Honey scripts
- Strict output format (`[REEL SCRIPT]` / `[CAPTION]`)

### 6.2 Groq — Whisper Large V3

**Integration:** Direct REST API (no SDK)
**Endpoint:** `https://api.groq.com/openai/v1/audio/transcriptions`
**Model:** `whisper-large-v3`

```
POST /openai/v1/audio/transcriptions
Headers: Authorization: Bearer {GROQ_API_KEY}