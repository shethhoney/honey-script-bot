# Technical Design Document — Honey Script Bot

**Version:** 2.0
**Date:** 2025-07-10
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

The Honey Script Bot is a single-user, WhatsApp-based AI writing assistant purpose-built for Indian lifestyle, beauty, and travel content creator **Honey Sheth**. It generates Instagram Reel scripts and accompanying captions that match her established voice, trained on 37 of her real scripts embedded as stylistic guidance in a system prompt.

### Core Workflow

1. Honey sends a brand brief to the bot via WhatsApp (as text, PDF, Word document, image, forwarded email, or voice note).
2. The bot asks her to select a content format (IMMBT, Event, or Collab) and a sub-format.
3. The bot generates 4 creative concept directions using Claude Opus.
4. Honey picks a concept (or requests all variations).
5. The bot produces a full reel script with visual/audio cues and an Instagram caption.
6. Honey iterates via text or voice feedback until satisfied.
7. She types `save` to approve the script, which enters a learning library that improves future generations via few-shot examples.

### Design Philosophy

- **Single-user tool** — no authentication layer; designed for one phone number.
- **Conversational UI** — the entire interaction happens inside WhatsApp, requiring zero app installs.
- **Learning system** — approved scripts and refinement feedback accumulate over time, making each generation closer to Honey's voice.
- **Multi-modal input** — accepts text, documents, images, voice notes, and forwarded emails.

---

## 2. Tech Stack

| Component | Technology | Version | Reasoning |
|---|---|---|---|
| **Runtime** | Python | 3.x | Broad library ecosystem for AI/NLP, fast prototyping |
| **Web Framework** | Flask | 2.3.3 | Lightweight; only two routes needed. No ORM or template overhead. |
| **WSGI Server** | Gunicorn | 21.2.0 | Production-grade Python HTTP server; required for Railway deployment |
| **LLM — Generation** | Anthropic Claude (claude-opus-4-6) | via `anthropic` 0.89.0 | Highest-quality creative writing; supports vision (image briefs) |
| **LLM — Extraction** | Anthropic Claude (claude-haiku-4-5-20251001) | via `anthropic` 0.89.0 | Fast/cheap model used solely for brand/product name extraction before web search |
| **Speech-to-Text** | Groq Whisper Large v3 | REST API | Fast, free-tier transcription; supports `.ogg` voice notes from WhatsApp |
| **Messaging** | Twilio WhatsApp API | `twilio` 8.2.0 | Industry-standard programmable WhatsApp; handles message send/receive, media hosting |
| **PDF Parsing** | PyPDF2 | 3.0.1 | Pure-Python PDF text extraction; no native dependencies |
| **DOCX Parsing** | Mammoth | 1.6.0 | Extracts raw text from `.docx` files; lightweight |
| **HTTP Client** | Requests | 2.31.0 | Used for Twilio media downloads, Groq API calls, Brave Search |
| **Web Search** | Brave Search API | REST (optional) | Enriches briefs with real product USPs; optional — degrades gracefully if key absent |
| **State Storage** | Python `shelve` | stdlib | Simple key-value persistence for conversation state; file-based, no DB server needed |
| **Data Storage** | JSON files | stdlib | Approved script library and feedback log stored as JSON on disk |
| **Deployment** | Railway (Nixpacks) | Hobby tier | One-command deploy; persistent volumes; health checks; env var management |
| **WSGI Adapter** | Werkzeug | 2.3.7 | Flask dependency; pinned for compatibility |

---

## 3. Architecture & File Structure

```
honey-script-bot/
├── app.py               # Entire application — webhook, state machine, AI generation,
│                        # media processing, library management, messaging
├── requirements.txt     # Pinned Python dependencies
├── railway.toml         # Railway deployment configuration
└── /data/               # Persistent volume (Railway-mounted at runtime)
    ├── honey_state.db   # shelve database — conversation state per phone number
    ├── honey_library.json   # Approved script library (rolling window of 20)
    └── honey_feedback.json  # Refinement feedback log (rolling window of 30)
```

### Architectural Pattern

The application is a **monolithic single-file Flask app** with no separate modules, services, or database layers. This is a deliberate choice for a single-user tool:

```
┌─────────────┐     HTTPS POST     ┌──────────────────────────────────────┐
│   WhatsApp   │ ───────────────▶  │  Twilio Platform                     │
│   (Honey)    │ ◀───────────────  │  (webhook relay + media hosting)     │
└─────────────┘                    └────────────┬─────────────────────────┘
                                                │ POST /webhook
                                                ▼
                                   ┌──────────────────────────────────────┐
                                   │         Flask App (app.py)           │
                                   │                                      │
                                   │  ┌────────────┐  ┌───────────────┐  │
                                   │  │ State       │  │ Script        │  │
                                   │  │ Machine     │  │ Library       │  │
                                   │  │ (shelve)    │  │ (JSON)        │  │
                                   │  └──────┬─────┘  └───────┬───────┘  │
                                   │         │                 │          │
                                   │  ┌──────┴─────────────────┴───────┐  │
                                   │  │      Processing Pipeline       │  │
                                   │  │  • Media extraction            │  │
                                   │  │  • Email detection             │  │
                                   │  │  • Voice transcription         │  │
                                   │  │  • Web search enrichment       │  │
                                   │  │  • AI generation/refinement    │  │
                                   │  └──────┬─────────────────────────┘  │
                                   └─────────┼────────────────────────────┘
                                             │
                          ┌──────────────────┼──────────────────┐
                          ▼                  ▼                  ▼
                   ┌─────────────┐  ┌──────────────┐  ┌──────────────┐
                   │  Anthropic  │  │    Groq       │  │ Brave Search │
                   │  Claude API │  │  Whisper API  │  │    API       │
                   │ (Opus/Haiku)│  │  (STT)        │  │ (optional)   │
                   └─────────────┘  └──────────────┘  └──────────────┘
```

### Request Flow

1. Twilio receives a WhatsApp message from Honey and POSTs to `/webhook`.
2. Flask synchronously reads state, determines the conversation step, and returns a TwiML response (immediate acknowledgment).
3. Long-running operations (AI generation, transcription, web search) are dispatched to **daemon threads** that send results back via the Twilio REST API.

---

## 4. Environment Variables

All five are validated at startup; the application raises `RuntimeError` and refuses to start if any are missing.

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | **Yes** | API key for Anthropic. Used for all Claude model calls (Opus for generation/refinement, Haiku for brand extraction). |
| `TWILIO_ACCOUNT_SID` | **Yes** | Twilio Account SID. Used to initialize the Twilio REST client and to authenticate media download requests. |
| `TWILIO_AUTH_TOKEN` | **Yes** | Twilio Auth Token. Paired with SID for REST client initialization and HTTP Basic Auth on media URLs. |
| `TWILIO_WHATSAPP_NUMBER` | **Yes** | The Twilio-provisioned WhatsApp sender number in `whatsapp:+XXXXXXXXXXX` format. Used as the `from_` parameter on all outbound messages. |
| `GROQ_API_KEY` | **Yes** | API key for Groq. Used for Whisper Large v3 audio transcription of voice notes. |
| `BRAVE_SEARCH_API_KEY` | No (optional) | API key for Brave Search. When present, the bot enriches brand briefs with web-searched product USPs, ingredients, and claims. If absent, this feature is silently skipped. |
| `PORT` | No (auto-set) | Port for the Flask/Gunicorn server. Defaults to `5000` in development; Railway injects this automatically. |

---

## 5. State Machine

The bot manages per-user conversation state via a `shelve` database. Each phone number maps to a state dictionary containing the current `step` and accumulated context.

### State Definitions

| State | Description | Stored Context |
|---|---|---|
| `idle` | Default/resting state. Bot is waiting for a new brief or refinement feedback. | May contain `last_script`, `last_caption`, `brief`, `subformat_label` from a prior generation. |
| `awaiting_format` | Brief has been received and stored. Waiting for format selection (1/2/3). | `brief` |
| `awaiting_subformat` | Format chosen. Waiting for sub-format selection. | `brief`, `format` |
| `generating_concepts` | Sub-format chosen. Bot is generating 4 concept directions (background thread). | `brief`, `format`, `subformat_label` |
| `awaiting_concept` | Concepts presented. Waiting for concept selection (1-4) or "all". | `brief`, `format`, `subformat_label`, `concepts` (list) |
| `generating` | Script generation or refinement in progress (background thread). | `brief`, `subformat_label`, optionally `chosen_concept` |
| `awaiting_refine` | Script delivered. Waiting for refinement feedback. | `brief`, `subformat_label`, `last_script`, `last_caption` |

> **Note:** The `awaiting_refine` state is *set conceptually* but the actual code sets the step back to `idle` after delivering a script and relies on the presence of `last_script` in state to route short messages to refinement. The `awaiting_refine` step is used explicitly only when voice note feedback arrives.

### State Transition Diagram

```
                         ┌─────────┐
                         │  idle   │◀──────────────────────────────────┐
                         └────┬────┘                                   │
                              │                                        │
              ┌───────────────┼───────────────┐                        │
              │               │               │                        │
         New brief      Short message    "cancel"/"hi"                 │
         (text/doc/     (with last_script)   (reset)                   │
          image/email)      │                                          │
              │              ▼                                         │
              │     ┌────────────────┐                                 │
              │     │  (refine via   │─── result ──────────────────────┤
              │     │   idle path)   │                                 │
              │     └────────────────┘                                 │
              ▼                                                        │
     ┌────────────────┐                                                │
     │ awaiting_format │                                               │
     │   (1/2/3?)     │                                                │
     └───────┬────────┘                                                │
             │ valid format                                            │
             ▼                                                         │
    ┌─────────────────────┐                                            │
    │ awaiting_subformat   │                                           │
    │ (1-3 or 1-5?)       │                                           │
    └────────┬────────────┘                                            │
             │ valid sub-format                                        │
             ▼                                                         │
  ┌──────────────────────────┐                                         │
  │ generating_concepts       │ ◀── background thread                  │
  │ (Claude Opus generates 4) │                                        │
  └──────────┬───────────────┘                                         │
             │ concepts ready                                          │
             ▼                                                         │
    ┌──────────────────┐                                               │
    │ awaiting_concept  │                                              │
    │ (1-4 or "all"?)  │                                               │
    └────────┬─────────┘                                               │
             │ concept chosen                                          │
             ▼                                                         │
      ┌─────────────┐                                                  │
      │ generating   │ ◀── background thread                           │
      │ (script gen) │                                                 │
      └──────┬──────┘                                                  │
             │ script ready                                            │
             ▼                                                         │
         ┌───────┐                                                     │
         │ idle  │ (with last_script populated)                        │
         │       │─── feedback text ──▶ refine ──── result ────────────┤
         │       │─── "save" ──▶ add to library ───────────────────────┘
         └───────┘
```

### Special Transitions

| Trigger | From | To | Behavior |
|---|---|---|---|
| Greeting (`hi`, `hello`, `hey`, `start`) | Any | `idle` | Resets state, shows welcome message |
| `cancel` | Any | `idle` | Resets state |
| `save` | Any (with `last_script`) | Stays `idle` | Adds script to library |
| `library` / `my scripts` / `examples` | Any | No change | Displays library summary |
| `help` | Any | No change | Shows usage guide |
| Voice note (with `last_script`) | `idle` or `awaiting_refine` | `generating` | Transcribes → refines |
| Voice note (no `last_script`) | `idle` | `awaiting_format` | Transcribes → treats as new brief |
| Short text (< 500 chars, no brief signals, with `last_script`) | `idle` | `generating` | Routes directly to refinement |
| Long text (> 500 chars or contains brief signals) | `idle` (with `last_script`) | `awaiting_format` | Treated