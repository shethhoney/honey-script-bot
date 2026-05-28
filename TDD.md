# Technical Design Document — Honey Script Bot

**Version:** 2.0
**Date:** 2025-07-09
**Author:** Auto-generated from codebase analysis
**Status:** Production (Live)

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

The Honey Script Bot is a single-user, WhatsApp-based AI assistant purpose-built for content creator **Honey Sheth**. It generates Instagram Reel scripts and captions in Honey's distinctive voice — a casual, sensory, Hindi-code-switching Indian lifestyle/beauty/travel creator tone.

### Core Value Proposition

The bot replaces the manual cycle of briefing a copywriter: Honey forwards a brand brief (text, PDF, Word doc, image screenshot, email, or voice note) via WhatsApp, selects a content format, and receives a fully-formed Reel script with visual/PTC/VO/Super cues plus a separate Instagram caption — all tuned to her personal voice.

### Key Capabilities

| Capability | Description |
|---|---|
| **Multi-format brief ingestion** | Plain text, PDF, DOCX, images (via vision), voice notes (via transcription), forwarded brand emails |
| **Guided format selection** | Three-tier menu system: top-level format → sub-format → concept selection |
| **Concept ideation** | Generates 4 distinct creative concepts before scripting; user picks one or requests all |
| **Script + caption generation** | Produces structured Reel scripts (Visual/PTC/VO/Super cues) and a companion Instagram caption |
| **Iterative refinement** | Accepts text or voice feedback and refines the current script without full regeneration |
| **Voice learning** | Approved scripts are saved to a persistent library; future generations use them as few-shot examples |
| **Feedback pattern tracking** | Refinement instructions are logged and injected into future refine prompts to avoid repeated mistakes |
| **Web enrichment** | Optionally searches for real product USPs/ingredients via Brave Search to ground scripts in facts |
| **Email extraction** | Detects forwarded brand emails and auto-extracts structured brief information |

### User Flow Summary

```
Brand Brief (any format) → Format Selection → Sub-format Selection →
Concept Generation (4 options) → Concept Selection → Script + Caption →
Iterative Refinement (text/voice) → Approve & Save to Library
```

---

## 2. Tech Stack

### Runtime & Framework

| Component | Version | Reasoning |
|---|---|---|
| **Python** | 3.x (Railway Nixpacks auto-detected) | Primary application language; strong AI/NLP ecosystem |
| **Flask** | 2.3.3 | Lightweight WSGI framework; sufficient for a single webhook endpoint; minimal overhead |
| **Gunicorn** | 21.2.0 | Production WSGI server; single-worker config avoids shelve concurrency issues |
| **Werkzeug** | 2.3.7 | Pinned to maintain Flask 2.3.x compatibility |

### AI & NLP Services

| Service | Model / Version | Purpose |
|---|---|---|
| **Anthropic Claude** | `claude-opus-4-6` (primary), `claude-haiku-4-5-20251001` (lightweight extraction) | Script generation, refinement, concept ideation, email brief extraction, brand/product extraction for search |
| **Groq** | `whisper-large-v3` | Voice note transcription (WhatsApp audio → text) |

### Communication

| Service | Library Version | Purpose |
|---|---|---|
| **Twilio WhatsApp API** | `twilio==8.2.0` | Inbound webhook receipt, outbound message delivery via WhatsApp Business API |

### Document Processing

| Library | Version | Purpose |
|---|---|---|
| **PyPDF2** | 3.0.1 | PDF text extraction from brand brief attachments |
| **mammoth** | 1.6.0 | DOCX → raw text extraction from Word document briefs |

### Storage & Networking

| Library / Service | Purpose |
|---|---|
| **shelve** (stdlib) | Persistent key-value store for per-user conversation state |
| **GitHub API** (via `requests`) | Primary persistent storage for the approved script library (`honey_library.json`) |
| **Brave Search API** (via `requests`) | Optional web search to enrich briefs with real product USPs/ingredients |
| **requests** | 2.31.0 — HTTP client for Twilio media download, GitHub API, Brave Search, Groq API |

### Supporting Standard Library Modules

| Module | Purpose |
|---|---|
| `threading` | Background workers for AI generation (non-blocking webhook responses) |
| `shelve` | Disk-backed dictionary for conversation state |
| `tempfile` | Temporary file creation for audio transcription |
| `json` | Library and feedback file serialization |
| `base64` | Image encoding for Claude Vision; GitHub content API encoding/decoding |
| `uuid` | Unique IDs for library entries |
| `re` | Regex parsing of AI output (`[REEL SCRIPT]`/`[CAPTION]` delimiters, concept extraction) |
| `io` | In-memory byte streams for PDF/DOCX processing |
| `time` | Sleep intervals for progress messages and message chunk spacing |
| `os` | Environment variable access, file path operations, temp file cleanup |
| `datetime` | UTC timestamps for library entries and feedback logs |

---

## 3. Architecture & File Structure

### High-Level Architecture

```
┌─────────────┐    HTTPS POST     ┌─────────────────────┐
│  WhatsApp    │ ───────────────▶  │   Twilio Platform   │
│  (Honey)     │ ◀─────────────── │   (Webhook Proxy)   │
└─────────────┘   WhatsApp msgs   └────────┬────────────┘
                                           │ POST /webhook
                                           ▼
                                  ┌─────────────────────┐
                                  │   Flask App (app.py) │
                                  │   Gunicorn, 1 worker │
                                  └───┬─────┬─────┬─────┘
                                      │     │     │
                          ┌───────────┘     │     └───────────┐
                          ▼                 ▼                 ▼
                   ┌────────────┐   ┌────────────┐   ┌──────────────┐
                   │ Anthropic  │   │   Groq     │   │ Brave Search │
                   │ Claude API │   │ Whisper API│   │     API      │
                   └────────────┘   └────────────┘   └──────────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │  GitHub API           │
              │  (Library Persistence)│
              └───────────────────────┘
```

### Data Flow

```
Inbound Message → Twilio Webhook → Flask Route Handler
    ↓
State Machine (shelve DB) determines current step
    ↓
Branch: Brief Ingestion | Format Selection | Concept Selection | 
        Script Generation | Refinement | Save | Command
    ↓
Background Thread spawned for AI-heavy operations
    ↓
AI Response parsed → State updated → Outbound messages sent via Twilio
```

### File Structure

```
honey-script-bot/
├── app.py                    # Entire application — single-file monolith
├── requirements.txt          # Python dependencies (8 packages)
├── railway.toml              # Railway deployment configuration
├── honey_library.json        # Approved script library (committed to GitHub repo)
│
├── /data/                    # Railway persistent volume (if mounted)
│   ├── honey_state.db        # shelve database (conversation state)
│   ├── honey_library.json    # Local backup of script library
│   └── honey_feedback.json   # Refinement feedback log
│
└── /tmp/                     # Fallback storage (ephemeral)
    ├── honey_state.db
    ├── honey_library.json
    └── honey_feedback.json
```

### Module Organization (within app.py)

The single-file application is organized into clearly delineated sections:

| Section | Line Range (approx.) | Responsibility |
|---|---|---|
| Imports & Config | Top | Dependencies, env var validation, client initialization |
| Persistent Storage Constants | Early | Storage path detection, file paths, size caps |
| GitHub-backed Library Cache | `_gh_*`, `_load_from_github`, `_save_to_github` | Remote persistence layer |
| State Management | `get_state`, `set_state` | Shelve-backed conversation state |
| Script Library | `load_library`, `save_library`, `add_to_library`, `get_examples_for_prompt` | Library CRUD and few-shot example selection |
| Feedback Tracker | `load_feedback`, `save_feedback_log`, `log_feedback`, `get_feedback_for_prompt` | Refinement pattern logging |
| System Prompt | `SYSTEM_PROMPT` | ~2,500-word Claude system prompt defining Honey's voice |
| Format Menus | `FORMAT_MENU`, `SUBFORMAT_MENUS`, `SUBFORMAT_LABELS` | Content format taxonomy and display strings |
| Messaging Helpers | `send_message`, `send_in_chunks` | Twilio outbound with chunking |
| Media Helpers | `download_media`, `transcribe_audio`, `extract_pdf`, `extract_docx`, `extract_brief`, `looks_like_email`, `extract_email_brief` | Multi-format brief ingestion |
| Web Search | `search_product_usps`, `extract_brand_and_search` | Brave Search enrichment pipeline |
| AI Generation | `generate_concepts`, `generate_script`, `refine_script` | Claude API orchestration |
| Background Workers | `send_script_and_caption`, `process_concepts_and_send`, `process_and_send`, `process_refine_and_send`, `process_brief_and_send`, `process_voice_brief_and_send` | Threaded async processing |
| Webhook Route | `webhook()` | Main request handler — state machine dispatcher |
| Health Route | `health()` | Liveness probe |

---

## 4. Environment Variables

### Required Variables (validated at startup)

The application performs startup validation for these five variables. If any is missing, the process raises `RuntimeError` and refuses to start.

| Variable | Description | Used By |
|---|---|---|
| `ANTHROPIC_API_KEY` | API key for Anthropic Claude. Authenticates all script generation, refinement, concept ideation, email extraction, and brand extraction calls. | `anthropic.Anthropic` client |
| `TWILIO_ACCOUNT_SID` | Twilio Account SID. Used for REST API authentication (outbound messages) and HTTP Basic Auth for media downloads. | `twilio.rest.Client`, `requests.get(auth=(...))` |
| `TWILIO_AUTH_TOKEN` | Twilio Auth Token. Paired with Account SID for authentication. | `twilio.rest.Client`, `requests.get(auth=(...))` |
| `TWILIO_WHATSAPP_NUMBER` | The Twilio WhatsApp sender number (format: `whatsapp:+1XXXXXXXXXX`). All outbound messages are sent from this number. | `twilio_client.messages.create(from_=...)` |
| `GROQ_API_KEY` | API key for Groq. Authenticates Whisper-based audio transcription for voice note processing. | `requests.post` to Groq API |

### Optional Variables (feature flags)

| Variable | Description | Default Behavior if Missing |
|---|---|---|
| `GITHUB_LIBRARY_TOKEN` | GitHub Personal Access Token with `repo` scope. Enables persistent storage of the script library in the GitHub repository. | Library falls back to local file only; GitHub read/write silently disabled |
| `GITHUB_REPO` | GitHub repository in `owner/repo` format for library storage. | Defaults to `"shethhoney/honey-script-bot"` |
| `BRAVE_SEARCH_API_KEY` | Brave Search API subscription token. Enables automatic web enrichment of brand briefs with real product USPs. | Web enrichment silently skipped; `extract_brand_and_search` returns empty string |
| `PORT` | HTTP port for the Flask/Gunicorn server. | Defaults to `5000` |

---

## 5. State Machine

The bot implements a per-user finite state machine stored in a shelve database. Each WhatsApp number has an independent state. State transitions are driven by inbound messages and background task completion.

### States

| State | Description | Expected Input |
|---|---|---|
| `idle` | No active flow. Awaiting a new brief or command. | Brief (text/media), greeting, command (`save`, `again`, `library`, `help`, `cancel`) |
| `awaiting_format` | Brief received; awaiting top-level format selection (1/2/3). | `"1"`, `"2"`, or `"3"` |
| `awaiting_subformat` | Format chosen; awaiting sub-format selection. | Number within valid range for chosen format |
| `generating` | AI is working (concepts or script). Transient state — set before thread launch, cleared by thread. | (No user input expected; messages during this state fall through to default handling) |
| `awaiting_concept` | 4 concepts presented; awaiting user's choice. | `"1"`–`"4"` or `"all"` |
| `awaiting_refine` | Script delivered; explicitly awaiting refinement feedback. | Free-text feedback or voice note |

> **Note:** The `awaiting_refine` state is set by `send_script_and_caption` conceptually (the post-delivery prompt says "Tell me what to tweak"), but in practice the code sets the step back to `idle` after generation completes. Refinement is handled through the "idle with previous script" shortcut — when `step == "idle"` and `last_script` exists, short messages are interpreted as refinement instructions rather than new briefs.

### State Transition Diagram

```
                              ┌──────────┐
                              │          │
         greeting/cancel ────▶│   IDLE   │◀──── cancel (from any state)
                              │          │
                              └─────┬────┘
                                    │
                    ┌───────────────┤ (brief received: text/pdf/docx/image/email/voice)
                    │               │
                    ▼               │ (short text + last_script exists)
           ┌────────────────┐      │
           │   AWAITING     │      ▼
           │   FORMAT       │  ┌──────────┐
           │  (1/2/3)       │  │GENERATING│──▶ (refine completes) ──▶ IDLE
           └───────┬────────┘  │(refine)  │    (with last_script)
                   │           └──────────┘
                   │ (