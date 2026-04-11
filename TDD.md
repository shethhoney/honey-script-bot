# Technical Design Document — Honey Script Bot

**Version:** 2.0
**Date:** 2025-01-24
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

The Honey Script Bot is a personal, single-user WhatsApp-based AI assistant purpose-built for Indian lifestyle/beauty/travel content creator **Honey Sheth**. It accepts brand briefs via WhatsApp (as text, PDFs, Word documents, images, forwarded emails, or voice notes), and generates Instagram Reel scripts and captions in Honey's distinctive voice.

### Core Workflow

1. **Brief Ingestion** — The user sends a brand brief in any supported format.
2. **Format Selection** — The bot presents a menu-driven format/subformat taxonomy (IMMBT, Event, Collab).
3. **Concept Generation** — The bot generates 4 distinct creative concepts for the user to choose from.
4. **Script Generation** — Based on the selected concept, a full reel script and caption are generated.
5. **Iterative Refinement** — The user provides feedback (text or voice), and the bot rewrites accordingly.
6. **Approval & Learning** — When the user is satisfied, they type `save`, and the approved script is stored in a rolling library that is injected as few-shot examples into future generations.

### Design Philosophy

- **Voice fidelity**: A detailed system prompt trained on 37 real Honey Sheth scripts encodes her voice characteristics, emotional arc, script cue conventions (`Visual`, `PTC`, `VO`, `Super`), caption rules, and format-specific guides.
- **Progressive learning**: An approval-based library system and feedback log enable the model to converge on the user's preferences over time.
- **Conversational UX**: The entire interaction occurs within WhatsApp, with no external dashboards or web UIs. The bot uses numbered menus, progress indicators, and chunked message delivery for a native chat experience.

---

## 2. Tech Stack

| Layer | Technology | Version | Reasoning |
|-------|-----------|---------|-----------|
| **Runtime** | Python | 3.x | Broad library ecosystem, first-class support across all integrated APIs |
| **Web Framework** | Flask | 2.3.3 | Lightweight; the app exposes only two routes — a webhook and a health check. No ORM, templating, or middleware overhead needed. |
| **WSGI Server** | Gunicorn | 21.2.0 | Production-grade WSGI server; configured with 1 worker to avoid state conflicts with `shelve` and threading |
| **WSGI Compatibility** | Werkzeug | 2.3.7 | Pinned to match Flask 2.3.3 dependency requirements |
| **LLM (Generation)** | Anthropic Python SDK | 0.89.0 | Access to Claude claude-opus-4-6 for high-quality creative writing; supports vision (base64 image input) for image-based briefs |
| **Speech-to-Text** | Groq API (Whisper large-v3) | REST API | Fast, free-tier transcription of WhatsApp voice notes; supports OGG, M4A, MP3, WebM formats |
| **Messaging** | Twilio Python SDK | 8.2.0 | WhatsApp Business API via Twilio — handles inbound webhook parsing and outbound message delivery |
| **Web Search** | Brave Search API | REST API | Optional product USP enrichment; searches for brand/product ingredient and benefit details to make scripts more factually specific |
| **PDF Extraction** | PyPDF2 | 3.0.1 | Pure-Python PDF text extraction; no native dependencies, ideal for containerized deployment |
| **DOCX Extraction** | Mammoth | 1.6.0 | Extracts raw text from `.docx` files; minimal footprint compared to python-docx |
| **HTTP Client** | Requests | 2.31.0 | Used for Twilio media downloads, Groq API calls, and Brave Search API calls |
| **State Persistence** | `shelve` (stdlib) | Built-in | Key-value store backed by filesystem; sufficient for single-user, single-worker deployment |
| **Hosting** | Railway | Hobby plan | Nixpacks-based container builds, persistent volume support, health check monitoring, and sub-$10/month cost |

---

## 3. Architecture & File Structure

```
honey-script-bot/
├── app.py              # Monolithic application: routes, state machine, AI calls,
│                       # media processing, messaging, storage — all in one file
├── requirements.txt    # Pinned Python dependencies
├── railway.toml        # Railway deployment configuration
└── /data/              # Railway persistent volume (runtime, mounted externally)
    ├── honey_state.db  # shelve database files (conversation state per phone number)
    ├── honey_library.json   # Approved script library (rolling window of 20)
    └── honey_feedback.json  # Refinement feedback log (rolling window of 30)
```

### Architectural Pattern

The application follows a **monolithic single-file architecture**. All concerns — routing, state management, AI orchestration, media processing, messaging, and persistence — reside in `app.py`. This is a deliberate choice for a single-user tool where operational simplicity outweighs separation-of-concerns benefits.

### Request Flow

```
WhatsApp User
    │
    ▼
Twilio WhatsApp Sandbox / Business API
    │
    ▼ (HTTP POST to /webhook)
Flask Application (app.py)
    │
    ├── Synchronous: Parse input, read state, return TwiML response
    │
    └── Asynchronous (daemon threads):
        ├── Media download & transcription (Groq Whisper)
        ├── Brief extraction (PDF / DOCX / Image / Email)
        ├── Web enrichment (Brave Search → Claude Haiku extraction)
        ├── Concept generation (Claude Opus)
        ├── Script generation (Claude Opus)
        ├── Script refinement (Claude Opus)
        └── Message delivery (Twilio outbound, chunked)
```

---

## 4. Environment Variables

All five required environment variables are validated at application startup. If any is missing, the app raises a `RuntimeError` and refuses to start.

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | **Yes** | API key for Anthropic's Claude API. Used for all LLM calls: concept generation (Claude Opus), script generation (Claude Opus), script refinement (Claude Opus), email brief extraction (Claude Opus), and brand/product extraction (Claude Haiku). |
| `TWILIO_ACCOUNT_SID` | **Yes** | Twilio Account SID. Used to authenticate the Twilio REST client for outbound messaging, and as HTTP Basic Auth credentials when downloading media files attached to inbound messages. |
| `TWILIO_AUTH_TOKEN` | **Yes** | Twilio Auth Token. Paired with `TWILIO_ACCOUNT_SID` for client authentication and media download authorization. |
| `TWILIO_WHATSAPP_NUMBER` | **Yes** | The Twilio WhatsApp sender number in `whatsapp:+XXXXXXXXXXX` format. Used as the `from_` parameter on all outbound messages. |
| `GROQ_API_KEY` | **Yes** | API key for Groq's OpenAI-compatible transcription endpoint. Used exclusively for Whisper large-v3 speech-to-text transcription of voice notes. |
| `BRAVE_SEARCH_API_KEY` | No | API key for Brave Search API. When present, the bot automatically searches for product USPs/ingredients/benefits and injects them into the brief before generation. When absent, this enrichment step is silently skipped. |

---

## 5. State Machine

The bot maintains per-phone-number conversational state in a `shelve` database. Each state entry is a dictionary with a `step` key (the current state) plus contextual data accumulated through the conversation.

### States

| State | Description |
|-------|-------------|
| `idle` | Default/initial state. The bot is waiting for a new brief or a refinement instruction (if a previous script exists in state). |
| `awaiting_format` | A brief has been received and parsed. The bot has presented the top-level format menu (IMMBT / Event / Collab) and awaits a `1`, `2`, or `3` response. |
| `awaiting_subformat` | A top-level format has been selected. The bot has presented the subformat menu and awaits a numeric selection. |
| `generating_concepts` | Transient state set immediately before the concept generation thread is spawned. The bot is generating 4 creative concepts via Claude Opus. |
| `awaiting_concept` | Concepts have been generated and presented. The bot awaits a concept selection (`1`–`4`) or `all`. |
| `generating` | Transient state set immediately before the script generation or refinement thread is spawned. |
| `awaiting_refine` | Not explicitly transitioned to in the main flow — the post-generation prompt invites free-text refinement. In practice, the `idle` state with a populated `last_script` field serves this role: short non-command messages are interpreted as refinement instructions. |

### State Transition Diagram

```
                        ┌──────────────────────────────────┐
                        │                                  │
                        ▼                                  │
    ┌───────────┐   brief received    ┌──────────────────┐ │
    │           │ ──────────────────► │                  │ │
    │   idle    │                     │ awaiting_format  │ │
    │           │ ◄── cancel ──────── │                  │ │
    └───────────┘                     └────────┬─────────┘ │
       │    ▲                                  │           │
       │    │                          1/2/3   │           │
       │    │                                  ▼           │
       │    │                         ┌──────────────────┐ │
       │    │                         │                  │ │
       │    │                         │awaiting_subformat│ │
       │    │                         │                  │ │
       │    │                         └────────┬─────────┘ │
       │    │                                  │           │
       │    │                       subformat  │           │
       │    │                       selected   │           │
       │    │                                  ▼           │
       │    │                       ┌────────────────────┐ │
       │    │                       │                    │ │
       │    │                       │generating_concepts │ │
       │    │                       │  (daemon thread)   │ │
       │    │                       └────────┬───────────┘ │
       │    │                                │             │
       │    │                       concepts │             │
       │    │                       ready    │             │
       │    │                                ▼             │
       │    │                       ┌──────────────────┐   │
       │    │                       │                  │   │
       │    │                       │ awaiting_concept │   │
       │    │                       │                  │   │
       │    │                       └────────┬─────────┘   │
       │    │                                │             │
       │    │                    1/2/3/4/all  │             │
       │    │                                ▼             │
       │    │                       ┌──────────────────┐   │
       │    │                       │                  │   │
       │    │                       │   generating     │   │
       │    │                       │  (daemon thread) │   │
       │    │                       └────────┬─────────┘   │
       │    │                                │             │
       │    │                     script     │             │
       │    │                     delivered  │             │
       │    │                                │             │
       │    └────────────────────────────────┘             │
       │                                                   │
       │  short text (refinement feedback)                 │
       │  ─────────────────────────────►  generating       │
       │                                  ──────────► idle │
       │                                                   │
       │  long text / media (new brief)                    │
       └───────────────────────────────────────────────────┘
```

### State Data Schema

```python
{
    "step": str,                # Current state name
    "brief": str,               # Extracted brief text (may include web enrichment)
    "format": str,              # Top-level format key: "immbt" | "event" | "collab"
    "subformat_label": str,     # Human-readable subformat description
    "concepts": list[str],      # List of generated concept strings
    "chosen_concept": str,      # The concept the user selected
    "last_script": str,         # Most recently generated/refined script
    "last_caption": str,        # Most recently generated/refined caption
}
```

### Idle-State Refinement Heuristic

When the bot is in `idle` state with a populated `last_script`, incoming short messages (≤500 characters) that are not commands or greetings are automatically interpreted as refinement instructions. Messages longer than 500 characters or containing brief-like signals (`"brand brief"`, `"new brief"`, `"collab brief"`, `"new campaign"`, `"new collab"`) are treated as new briefs. This enables a fluid refinement loop without explicit state transitions.

---

## 6. API Integrations

### 6.1 Anthropic Claude API

**Models Used:**

| Model | Usage | Max Tokens |
|-------|-------|------------|
| `claude-opus-4-6` | Concept generation | 600 |
| `claude-opus-4-6` | Single script generation | 2,200 |
| `claude-opus-4-6` | Multi-variation generation | 4,000 |
| `claude-opus-4-6` | Script refinement | 2,200 |
| `claude-opus-4-6` | Email brief extraction | 400 |
| `claude-haiku-4-5-20251001` | Brand/product name extraction (for web search) | 60 |

**System Prompt:** A ~1,500-word prompt (`SYSTEM_PROMPT`) is sent with every generation and refinement call. It encodes:
- Honey's voice characteristics (warm, confident, luxury-as-lived-in, Hindi code-switching)
- Script cue definitions (Visual, PTC, VO, Super) with usage rules
- Five-beat emotional arc (Hook → Product Moment → Demo/Experience → Transformation → CTA)
- Caption rules (essay-like, different angle from script, 2–5 hashtags)
- 11 format-specific guides (IMMBT Single/Hype/Sceptic, Event Booth/Destination/Community, Collab Routine/Narrative/Haul/Gifting/Platform)
- Hard rules (ALWAYS/NEVER constraints)
- 9 reference voice examples excerpted from real scripts
- Strict output format (`[REEL