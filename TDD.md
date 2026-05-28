# Technical Design Document — Honey Script Bot

**Version:** 2.0
**Date:** 2025-07-09
**Author:** Technical Documentation
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

The Honey Script Bot is a single-user, WhatsApp-based AI assistant purpose-built for Indian lifestyle/beauty/travel content creator **Honey Sheth**. It generates Instagram Reel scripts and captions that match her established voice and editorial style, trained on 37 of her real scripts embedded as a system prompt.

### Core Workflow

1. Honey sends a **brand brief** via WhatsApp (text, PDF, Word doc, screenshot, forwarded email, or voice note).
2. The bot extracts and optionally enriches the brief with web-searched product USPs.
3. Honey selects a **content format** (IMMBT / Event / Collab) and **sub-format** (11 total options).
4. The bot generates **4 creative concepts** for the reel.
5. Honey picks a concept (or requests all variations).
6. The bot generates a full **reel script** (with Visual/PTC/VO/Super cues) and an **Instagram caption**.
7. Honey iterates via **text or voice feedback** until satisfied.
8. Honey can **save** approved scripts to a personal library, which feeds back into future generations as few-shot examples.

### Design Philosophy

- **Single-user system** — no authentication layer; designed exclusively for one WhatsApp number.
- **Conversational state machine** — the entire UX is a guided multi-step flow within WhatsApp.
- **Self-improving** — approved scripts and feedback logs accumulate over time, steering the AI toward Honey's preferences with each interaction.
- **Asynchronous processing** — long-running AI calls happen in background threads so Twilio receives immediate `200 OK` responses.

---

## 2. Tech Stack

| Component | Technology | Version | Reasoning |
|---|---|---|---|
| **Runtime** | Python 3 | 3.x (Railway Nixpacks) | Broad library support for AI/ML, rapid prototyping |
| **Web Framework** | Flask | 2.3.3 | Lightweight; sufficient for a single webhook endpoint |
| **WSGI Server** | Gunicorn | 21.2.0 | Production-grade HTTP server; single-worker config for state safety |
| **ASGI Compat** | Werkzeug | 2.3.7 | Pinned to match Flask 2.3.x compatibility |
| **LLM Provider** | Anthropic (Claude) | SDK 0.89.0 | Claude claude-opus-4-6 for high-quality creative writing; Claude claude-haiku-4-5-20251001 for lightweight extraction |
| **Speech-to-Text** | Groq (Whisper) | REST API | Free tier; `whisper-large-v3` for accurate English + Hindi code-switching transcription |
| **Messaging** | Twilio WhatsApp API | SDK 8.2.0 | Industry standard for WhatsApp Business API integration; handles media relay |
| **Web Search** | Brave Search API | REST API | Optional enrichment; privacy-focused search with structured JSON results |
| **PDF Extraction** | PyPDF2 | 3.0.1 | Pure Python; no native dependencies for Railway deployment |
| **DOCX Extraction** | Mammoth | 1.6.0 | Extracts raw text from `.docx`; no LibreOffice dependency required |
| **HTTP Client** | Requests | 2.31.0 | Used for Twilio media downloads, Groq API, Brave Search API |
| **State Storage** | Python `shelve` | stdlib | Key-value persistence with no external database dependency |
| **Data Storage** | JSON files | stdlib | Human-readable; sufficient for small rolling windows (20 scripts, 30 feedback entries) |
| **Concurrency** | Python `threading` | stdlib | Daemon threads for background AI processing; thread locks for state safety |
| **Hosting** | Railway | Hobby plan | Simple container deployment with persistent volume support |

---

## 3. Architecture & File Structure

```
honey-script-bot/
├── app.py                  # Entire application — single-file monolith
├── requirements.txt        # Pinned Python dependencies
├── railway.toml            # Railway deployment configuration
└── /data/                  # Railway persistent volume (mounted at runtime)
    ├── honey_state.db      # shelve database (conversation state per phone number)
    ├── honey_library.json  # Approved script library (rolling window of 20)
    └── honey_feedback.json # Refinement feedback log (rolling window of 30)
```

### Architectural Pattern

The application follows a **single-file monolith** pattern. All logic — routing, state management, AI orchestration, media processing, storage — lives in `app.py`. This is deliberate for a single-user tool: minimal operational complexity, easy to debug, and trivial to deploy.

### Request Flow

```
WhatsApp → Twilio → POST /webhook → Flask route handler
                                       │
                                       ├─ Synchronous: TwiML 200 OK response
                                       │
                                       └─ Async (daemon thread):
                                           ├─ Media download/extraction
                                           ├─ Brief enrichment (Brave Search)
                                           ├─ AI generation (Anthropic Claude)
                                           ├─ State update (shelve)
                                           └─ Response delivery (Twilio REST)
```

### Module Organization (within app.py)

The file is organized into clearly demarcated sections via comment headers:

| Section | Lines (approx.) | Responsibility |
|---|---|---|
| Environment validation | Startup | Fail-fast if required env vars are missing |
| Persistent storage | Config | Path detection, file paths, constants |
| State (conversation flow) | Functions | `get_state()`, `set_state()` |
| Script library | Functions | CRUD for approved scripts, few-shot selection |
| Feedback tracker | Functions | CRUD for refinement feedback, pattern extraction |
| System prompt | Constant | 2000+ character prompt encoding Honey's voice |
| Format menus | Constants | Menu text, labels, key mappings |
| Messaging helpers | Functions | `send_message()`, `send_in_chunks()` |
| Media helpers | Functions | Download, transcribe, extract PDF/DOCX/image |
| Web search enrichment | Functions | Brave Search integration, brief enrichment |
| AI generation | Functions | `generate_concepts()`, `generate_script()`, `refine_script()` |
| Background workers | Functions | Thread targets that orchestrate generation + delivery |
| Webhook | Route | Main `/webhook` POST handler with state machine logic |
| Health | Route | `/health` GET endpoint |

---

## 4. Environment Variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | **Yes** | API key for Anthropic Claude. Used for all LLM calls (script generation, concept generation, refinement, email extraction, brand/product extraction). |
| `TWILIO_ACCOUNT_SID` | **Yes** | Twilio Account SID. Used for REST API client initialization and as HTTP Basic Auth username when downloading media from Twilio URLs. |
| `TWILIO_AUTH_TOKEN` | **Yes** | Twilio Auth Token. Used for REST API client initialization and as HTTP Basic Auth password for media downloads. |
| `TWILIO_WHATSAPP_NUMBER` | **Yes** | Twilio WhatsApp sender number in `whatsapp:+1234567890` format. Used as the `from_` parameter for all outbound messages. |
| `GROQ_API_KEY` | **Yes** | API key for Groq's Whisper endpoint. Used for voice note transcription via `whisper-large-v3`. |
| `BRAVE_SEARCH_API_KEY` | No | API key for Brave Search. **Optional.** When present, enables automatic brief enrichment by searching for product USPs, ingredients, and claims. All search-related code gracefully degrades to empty strings if absent. |
| `PORT` | No | Port for the Flask/Gunicorn server. Defaults to `5000`. Railway sets this automatically. |

### Startup Validation

The five required variables are validated at import time:

```python
_REQUIRED_ENV = ["ANTHROPIC_API_KEY", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN",
                 "TWILIO_WHATSAPP_NUMBER", "GROQ_API_KEY"]
for _key in _REQUIRED_ENV:
    if not os.environ.get(_key):
        raise RuntimeError(f"Missing required environment variable: {_key}")
```

If any are missing, the process exits immediately with a `RuntimeError` — preventing a partially-configured deployment from accepting traffic.

---

## 5. State Machine

The bot implements a **per-user conversational state machine** persisted in a `shelve` database. Each phone number has an independent state object.

### States

| State | Description | What the bot expects |
|---|---|---|
| `idle` | Default/reset state. No active workflow in progress. | A new brief (any media type), a greeting, a command (`save`, `again`, `library`, `help`, `cancel`), or — if `last_script` exists — a short text message treated as refinement feedback. |
| `awaiting_format` | Brief has been received and extracted. Waiting for top-level format selection. | A reply of `1`, `2`, or `3` corresponding to IMMBT, Event, or Collab. |
| `awaiting_subformat` | Top-level format selected. Waiting for sub-format selection. | A reply of `1`–`3` (IMMBT/Event) or `1`–`5` (Collab) selecting the specific angle. |
| `generating` | AI generation is in progress (in a background thread). | No user input expected. Any incoming message during this state falls through to default handling. The state is transient — set before thread launch, cleared when the thread completes. |
| `awaiting_concept` | 4 creative concepts have been presented. Waiting for concept selection. | A reply of `1`–`4` to select a concept, or `all` to generate all variations. |
| `awaiting_refine` | *(Defined in code but not explicitly set — see note below)* | Refinement feedback as text or voice note. |

> **Note on `awaiting_refine`:** The code defines handling for `step == "awaiting_refine"` in both the webhook and voice note handler, but the actual state is never explicitly set to `awaiting_refine` anywhere in the codebase. Instead, after script delivery, the state is set back to `idle` with `last_script` populated. The `idle` state handler has smart routing logic: if `last_script` exists and the incoming message is short (under 500 characters) and doesn't contain brief-like signals, it's automatically treated as refinement feedback. Voice notes also check for `last_script` to determine routing. This means the `awaiting_refine` state exists as a reachable code path (e.g., if manually set) but is effectively dead code under normal flow.

### State Transition Diagram

```
                              ┌─────────────────┐
                              │                  │
                    greeting  │      idle        │◄──── cancel (from any state)
                    ─────────►│  (entry point)   │◄──── generation complete
                              │                  │◄──── error recovery
                              └────────┬─────────┘
                                       │
                          ┌────────────┼─────────────────┐
                          │            │                  │
                     new brief    short msg +        save/again/
                     (any media)  last_script        library/help
                          │        exists                 │
                          │            │              (commands)
                          ▼            ▼
                 ┌─────────────┐   refine flow
                 │  awaiting   │   (direct to
                 │   format    │    generating)
                 │  (1/2/3)    │
                 └──────┬──────┘
                        │
                    1, 2, or 3
                        │
                        ▼
                 ┌─────────────┐
                 │  awaiting   │
                 │  subformat  │
                 │ (1-3 or 1-5)│
                 └──────┬──────┘
                        │
                   valid choice
                        │
                        ▼
                 ┌─────────────┐
                 │ generating  │ ── concept generation (background thread)
                 │  (concepts) │
                 └──────┬──────┘
                        │
                  concepts ready
                        │
                        ▼
                 ┌─────────────┐
                 │  awaiting   │
                 │   concept   │
                 │(1-4 or "all")│
                 └──────┬──────┘
                        │
                 ┌──────┴──────┐
                 │             │
            single (1-4)    "all"
                 │             │
                 ▼             ▼
          ┌─────────────┐  ┌─────────────┐
          │ generating  │  │ generating  │
          │  (single)   │  │ (multiple)  │
          └──────┬──────┘  └──────┬──────┘
                 │                │
                 └────────┬───────┘
                          │
                    script delivered
                          │
                          ▼
                 ┌─────────────┐
                 │    idle     │ (with last_script populated)
                 │ (refine or  │
                 │  new brief) │──── "again" ──► generating (new angle)
                 └─────────────┘──── "save"  ──► save to library, stay idle
                                ──── feedback ──► generating (refine)
```

### State Object Schema

```json
{
  "step": "idle | awaiting_format | awaiting_subformat | generating | awaiting_concept | awaiting_refine",
  "brief": "Extracted brief text (possibly enriched with web search results)",
  "format": "immbt | event | collab",
  "subformat_label": "Full human-readable sub-format label",
  "last_script": "Most recently generated reel script",
  "last_caption": "Most recently generated caption",
  "concepts": ["Concept 1 text", "Concept 2 text", ...],
  "chosen_concept": "The concept text the user selected"
}
```

### Smart Refinement Routing (idle state)

When the state is `idle` and `last_script` exists, the webhook applies heuristic routing:

```python
brief_signals = ["brand brief", "new brief", "collab brief", "new campaign", "new collab"]
looks_like_brief = len(msg_body) > 500 or any(s in lower for s in brief_signals)
```

- **Message > 500 chars** or contains