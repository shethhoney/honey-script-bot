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

The Honey Script Bot is a personal, AI-powered WhatsApp assistant built for Indian lifestyle, beauty, and travel content creator **Honey Sheth**. It automates the generation of Instagram Reel scripts and accompanying captions, fine-tuned to match Honey's distinctive voice and content style.

### Core Workflow

```
Brand Brief (text/PDF/DOCX/image/voice/email)
        │
        ▼
  Format Selection (IMMBT / Event / Collab)
        │
        ▼
  Sub-format Selection (3–5 options per format)
        │
        ▼
  Concept Generation (4 creative angles)
        │
        ▼
  Script + Caption Generation (Claude Opus)
        │
        ▼
  Iterative Refinement Loop (text or voice feedback)
        │
        ▼
  Save to Library (approved scripts train future output)
```

### Design Philosophy

- **Single-user tool**: Designed exclusively for one creator. No multi-tenancy, no auth layer beyond WhatsApp identity.
- **Learning system**: Every approved script is saved to a persistent library and injected as few-shot examples into future generations, causing the AI's output to converge toward Honey's actual voice over time.
- **Conversational UX**: The entire interface is a WhatsApp chat — no web dashboard, no login screen. Briefs can arrive as text, documents, images, forwarded emails, or voice notes.
- **Asynchronous processing**: All AI generation happens in background daemon threads to prevent Twilio webhook timeouts, with progress messages sent while the user waits.

---

## 2. Tech Stack

### Application Framework

| Component | Library/Version | Reasoning |
|-----------|----------------|-----------|
| Web Framework | Flask 2.3.3 | Lightweight, minimal overhead for a single-endpoint webhook server. No ORM, no template engine — only JSON/XML responses needed. |
| WSGI Server | Gunicorn 21.2.0 | Production-grade WSGI server; configured with a single worker to avoid concurrency issues with `shelve` file-based state. |
| HTTP Utility | Werkzeug 2.3.7 | Pinned explicitly to maintain compatibility with Flask 2.3.3. |

### AI & ML Services

| Component | Service/Model | Reasoning |
|-----------|--------------|-----------|
| Script Generation | Anthropic Claude `claude-opus-4-6` | Opus-tier model chosen for its superior creative writing quality, ability to maintain consistent voice across long-form scripts, and strong instruction following for format-specific output. Used for script generation, refinement, concept generation, and email brief extraction. |
| Brand/Product Extraction | Anthropic Claude `claude-haiku-4-5-20251001` | Lightweight, low-cost model used only for the narrow task of extracting brand/product names from briefs before web search enrichment. |
| Voice Transcription | Groq `whisper-large-v3` | Free-tier Groq API provides fast Whisper transcription. Enables voice-note-based briefs and feedback — critical for a mobile-first WhatsApp workflow. |
| Anthropic SDK | `anthropic` 0.89.0 | Official Python SDK for Claude API access. |

### Messaging & Communication

| Component | Library/Version | Reasoning |
|-----------|----------------|-----------|
| WhatsApp API | Twilio 8.2.0 | Industry-standard WhatsApp Business API provider. Handles message send/receive, media hosting, and webhook delivery. |

### Document Processing

| Component | Library/Version | Reasoning |
|-----------|----------------|-----------|
| PDF Extraction | PyPDF2 3.0.1 | Pure-Python PDF text extraction — no system dependencies required, which simplifies container deployment on Railway. |
| DOCX Extraction | Mammoth 1.6.0 | Extracts raw text from `.docx` files. Chosen over `python-docx` for its simpler API when only text content is needed. |

### Networking & Data

| Component | Library/Version | Reasoning |
|-----------|----------------|-----------|
| HTTP Client | Requests 2.31.0 | Used for Twilio media downloads, Groq API calls, Brave Search API, and GitHub API interactions. |

### Infrastructure & Storage

| Component | Technology | Reasoning |
|-----------|-----------|-----------|
| State Store | Python `shelve` (stdlib) | Zero-dependency key-value store for conversation state. Adequate for single-user, single-worker deployment. |
| Library Persistence | GitHub API + local JSON | GitHub serves as durable, version-controlled primary storage for the script library. Local JSON file acts as backup. |
| Hosting | Railway (Hobby plan) | Simple container hosting with persistent volume support, health checks, and automatic restarts. |

---

## 3. Architecture & File Structure

```
honey-script-bot/
├── app.py                  # Monolithic application — all logic in one file
├── requirements.txt        # Python dependencies (8 packages)
├── railway.toml            # Railway deployment configuration
├── honey_library.json      # Approved script library (GitHub-synced)
└── /data/                  # Railway persistent volume (runtime)
    ├── honey_state.db      # shelve database for conversation state
    ├── honey_library.json  # Local backup of script library
    └── honey_feedback.json # Rolling feedback log
```

### Architectural Pattern

The application follows a **monolithic single-file architecture** with the following logical sections:

```
app.py
├── Environment validation & client initialization
├── Persistent storage configuration
├── GitHub-backed library cache layer
├── State management (shelve-based)
├── Script library CRUD operations
├── Feedback tracking system
├── System prompt (Honey's voice definition)
├── Format/subformat menu definitions
├── Messaging helpers (chunking, sending)
├── Media processing (PDF, DOCX, image, audio)
├── Web search enrichment (Brave Search)
├── AI generation functions (concepts, scripts, refinement)
├── Background worker functions
├── Webhook route handler (conversation state machine)
└── Health check route
```

### Data Flow Diagram

```
┌─────────────┐     ┌──────────┐     ┌──────────────┐
│  WhatsApp    │────▶│  Twilio  │────▶│  /webhook    │
│  (Honey)     │◀────│  API     │◀────│  (Flask)     │
└─────────────┘     └──────────┘     └──────┬───────┘
                                            │
                    ┌───────────────────────┬┴──────────────────────┐
                    │                       │                       │
              ┌─────▼──────┐      ┌────────▼────────┐    ┌───────▼────────┐
              │  Anthropic  │      │   Groq Whisper  │    │  Brave Search  │
              │  Claude API │      │   (voice notes) │    │  (product USPs)│
              └─────┬──────┘      └────────┬────────┘    └───────┬────────┘
                    │                       │                     │
                    └───────────┬───────────┘                     │
                                │                                 │
                    ┌───────────▼──────────────────────────────────▼┐
                    │              State & Storage                   │
                    │  ┌─────────┐  ┌──────────┐  ┌─────────────┐ │
                    │  │ shelve  │  │ library  │  │  feedback   │ │
                    │  │ (state) │  │ (JSON)   │  │  (JSON)     │ │
                    │  └─────────┘  └─────┬────┘  └─────────────┘ │
                    └─────────────────────┼────────────────────────┘
                                          │
                                   ┌──────▼──────┐
                                   │   GitHub    │
                                   │  (durable   │
                                   │   storage)  │
                                   └─────────────┘
```

---

## 4. Environment Variables

All required variables are validated at startup. The application raises `RuntimeError` if any required variable is missing.

### Required Variables

| Variable | Description | Used By |
|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | API key for Anthropic Claude. Authenticates all script generation, concept generation, refinement, email extraction, and brand/product extraction calls. | `anthropic.Anthropic()` client |
| `TWILIO_ACCOUNT_SID` | Twilio Account SID. Used for REST API client authentication and HTTP Basic Auth when downloading media files from Twilio-hosted URLs. | `twilio.rest.Client()`, `requests.get()` auth |
| `TWILIO_AUTH_TOKEN` | Twilio Auth Token. Paired with Account SID for authentication. | `twilio.rest.Client()`, `requests.get()` auth |
| `TWILIO_WHATSAPP_NUMBER` | The Twilio WhatsApp sender number (format: `whatsapp:+1234567890`). Used as the `from_` parameter in all outbound messages. | `twilio_client.messages.create()` |
| `GROQ_API_KEY` | API key for Groq's Whisper transcription endpoint. Sent as Bearer token in Authorization header. | Voice note transcription via `requests.post()` |

### Optional Variables

| Variable | Description | Default/Fallback |
|----------|-------------|-----------------|
| `GITHUB_LIBRARY_TOKEN` | Personal access token for GitHub API. Enables reading/writing `honey_library.json` to the repository. If absent, GitHub sync is silently disabled and only local file storage is used. | `""` (empty string — GitHub sync disabled) |
| `GITHUB_REPO` | GitHub repository in `owner/repo` format for library storage. | `"shethhoney/honey-script-bot"` |
| `BRAVE_SEARCH_API_KEY` | API key for Brave Search API. Enables automatic product USP enrichment by searching the web for brand/product details extracted from briefs. If absent, enrichment is silently skipped. | `""` (empty string — enrichment disabled) |
| `PORT` | Port for the Flask/Gunicorn server to bind to. | `5000` |

---

## 5. State Machine

Conversation state is tracked per phone number using `shelve`. Each state includes the step name plus accumulated context (brief text, format selections, generated scripts, etc.).

### State Diagram

```
                    ┌──────────────────────────────────┐
                    │                                  │
                    ▼                                  │
 ┌──────────┐  brief received   ┌──────────────────┐  │
 │          │─────────────────▶│  awaiting_format  │  │
 │   idle   │                  │   (1/2/3 menu)    │  │
 │          │◀─────────────────└────────┬──────────┘  │
 └──────┬───┘    cancel/error           │              │
        │                         format chosen        │
        │                         (1/2/3)              │
        │                               │              │
        │                    ┌──────────▼───────────┐  │
        │                    │ awaiting_subformat   │  │
        │                    │ (sub-menu shown)     │  │
        │                    └──────────┬───────────┘  │
        │                               │              │
        │                      subformat chosen        │
        │                               │              │
        │                    ┌──────────▼───────────┐  │
        │                    │     generating       │  │
        │                    │  (concepts phase)    │──┤
        │                    └──────────┬───────────┘  │
        │                               │              │
        │                      concepts ready          │
        │                               │              │
        │                    ┌──────────▼───────────┐  │
        │                    │   awaiting_concept   │  │
        │                    │  (1-4 / all menu)    │  │
        │                    └──────────┬───────────┘  │
        │                               │              │
        │                    concept chosen / all       │
        │                               │              │
        │                    ┌──────────▼───────────┐  │
        │                    │     generating       │  │
        │                    │  (script phase)      │──┘
        │                    └──────────┬───────────┘
        │                               │
        │                      script delivered
        │                               │
        │                    ┌──────────▼───────────┐
        │◀───────────────────│       idle           │
        │    (returns to     │  (with last_script)  │
        │     idle with      └──────────┬───────────┘
        │     script in                 │
        │     memory)           short text or voice
        │                       (auto-refine)
        │                               │
        │                    ┌──────────▼───────────┐
        │                    │     generating       │
        │                    │  (refine phase)      │
        │                    └──────────┬───────────┘
        │                               │
        │                      refined script
        │                               │
        └───────────────────────────────┘
```

### State Definitions

| State | Description | Valid Inputs | Transitions To |
|-------|-------------|-------------|----------------|
| `idle` | Default state. No active workflow. If `last_script` exists in state, short messages are auto-routed to refinement. | Brief (text/media/voice), greeting, commands (`save`, `again`, `library`, `help`, `cancel`) | `awaiting_format` (brief received), `generating` (again/auto-refine) |
| `awaiting_format` | Brief captured. Waiting for top-level format selection (1/2/3). | `1` (IMMBT), `2` (Event), `3` (Collab) | `awaiting_subformat` |
| `awaiting_subformat` | Format selected. Waiting for sub-format selection. | `1`–`5` depending on format | `generating` (triggers concept generation) |
| `generating` | AI is working in a background thread. Transient state — the user cannot interact meaningfully. | (Incoming messages during this state are handled normally by the webhook but may lead to race conditions) | `awaiting_concept` (concepts ready), `idle` (script delivered or error) |
| `awaiting_concept` | Concepts presented. Waiting for concept selection. | `1`–`4` (select one), `