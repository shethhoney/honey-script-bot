# Technical Design Document — Honey Script Bot

**Version:** 2.0
**Date:** 2025-07-09
**Author:** Technical Documentation (auto-generated from source)
**Repository:** `shethhoney/honey-script-bot`

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

The Honey Script Bot is a personal, single-user AI assistant delivered over WhatsApp. It generates Instagram Reel scripts and captions for content creator **Honey Sheth**, matching her specific voice, tone, and content structure.

### Core Value Proposition

A content creator sends a brand brief (text, PDF, Word doc, screenshot, forwarded email, or voice note) to a WhatsApp number. The bot walks her through format selection, generates a script and caption in her established voice, then allows iterative refinement — all within the WhatsApp chat interface. Approved scripts are saved to a persistent library that serves as few-shot examples for future generations, creating a self-improving feedback loop.

### High-Level Flow

```
Brand Brief (any format)
        │
        ▼
  Brief Extraction & Email Detection
        │
        ▼
  Web Enrichment (Brave Search, optional)
        │
        ▼
  Format Selection (3 categories)
        │
        ▼
  Sub-format Selection (3–5 options)
        │
        ▼
  Concept Generation (4 concepts via Claude Opus)
        │
        ▼
  Concept Selection or "all"
        │
        ▼
  Script + Caption Generation (Claude Opus + Haiku voice-check)
        │
        ▼
  Iterative Refinement Loop (text or voice feedback)
        │
        ▼
  Save to Library (few-shot learning)
```

### Design Principles

- **Single-user system:** Designed exclusively for Honey Sheth, though technically any WhatsApp number can interact with the webhook. Library save is gated to Honey's number.
- **Voice fidelity over creativity:** The system prompt, few-shot examples, and voice-check pass all prioritize matching Honey's existing voice rather than generating novel styles.
- **Conversational UX:** The entire interface is a WhatsApp chat — no web dashboard, no login, no app install.
- **Self-improving:** Every `save` command adds a new approved script to the few-shot library, improving future output quality.

---

## 2. Tech Stack

### Runtime & Framework

| Component | Choice | Version | Reasoning |
|-----------|--------|---------|-----------|
| Language | Python | 3.x | Broad AI/ML library support, rapid prototyping |
| Web Framework | Flask | 2.3.3 | Lightweight, minimal overhead for a single-endpoint webhook |
| WSGI Server | Gunicorn | 21.2.0 | Production-grade serving; configured with 1 worker to avoid state conflicts |
| HTTP Adapter | Werkzeug | 2.3.7 | Flask dependency; pinned for compatibility |

### AI & ML Services

| Service | Model | Purpose |
|---------|-------|---------|
| Anthropic Claude | `claude-opus-4-6` | Primary script/caption generation, concept ideation, brief extraction, email parsing |
| Anthropic Claude | `claude-haiku-4-5-20251001` | Voice-check second pass (fast, cheap), brand/product extraction for search |
| Groq | `whisper-large-v3` | Voice note transcription (speech-to-text) |
| Brave Search API | Web search | Product USP enrichment (optional) |

### Messaging & Communication

| Service | Purpose |
|---------|---------|
| Twilio WhatsApp API | Inbound webhook reception and outbound message delivery |
| Twilio REST Client (`twilio==8.2.0`) | Programmatic message sending |
| Twilio TwiML | Immediate webhook responses |

### Document Processing

| Library | Version | Purpose |
|---------|---------|---------|
| PyPDF2 | 3.0.1 | PDF text extraction from brand briefs |
| mammoth | 1.6.0 | DOCX/Word document raw text extraction |

### Storage & Persistence

| Mechanism | Purpose |
|-----------|---------|
| Python `shelve` | Conversation state persistence (per-phone-number) |
| JSON files | Script library (`honey_library.json`) and feedback log (`honey_feedback.json`) |
| GitHub API | Primary persistent storage for the script library (survives redeploys) |

### Infrastructure

| Component | Choice | Reasoning |
|-----------|--------|-----------|
| Hosting | Railway (Hobby tier) | Simple container deployment with volume support, health checks, auto-restart |
| Build system | Nixpacks | Railway's default builder; auto-detects Python |

### Supporting Libraries

| Library | Version | Purpose |
|---------|---------|---------|
| requests | 2.31.0 | HTTP calls to Groq, Brave Search, GitHub API, Twilio media download |
| anthropic | 0.89.0 | Official Anthropic Python SDK |

---

## 3. Architecture & File Structure

### Repository Structure

```
honey-script-bot/
├── app.py                  # Entire application — single-file monolith
├── requirements.txt        # Python dependencies (8 packages)
├── railway.toml            # Railway deployment configuration
├── honey_library.json      # Approved script library (GitHub-persisted)
└── README.md               # (assumed)
```

### Architectural Pattern

The application is a **single-file monolith** (`app.py`, ~850 lines). All concerns — routing, state management, AI orchestration, media processing, storage, and messaging — live in one file. This is a deliberate choice for a single-user tool: simplicity over modularity.

### Logical Module Breakdown

Within `app.py`, the code is organized into logical sections (demarcated by comment headers):

| Section | Lines (approx.) | Responsibility |
|---------|-----------------|----------------|
| Environment & Config | 1–30 | Env var validation, client initialization |
| Persistent Storage | 30–55 | Path detection, constants, locks |
| GitHub-backed Library Cache | 55–130 | Cache layer, GitHub read/write |
| State Management | 130–150 | `get_state()`, `set_state()` with shelve |
| Script Library | 150–260 | Load/save/add library entries, few-shot example selection |
| Feedback Tracker | 260–310 | Feedback logging and prompt injection |
| System Prompt | 310–420 | 2,000+ word system prompt defining Honey's voice |
| Format Menus & Labels | 420–490 | Format taxonomy constants |
| Messaging Helpers | 490–520 | `send_message()`, `send_in_chunks()` |
| Media Helpers | 520–620 | Download, transcribe, extract PDF/DOCX/image, email detection |
| Web Search Enrichment | 620–680 | Brave Search integration, brand extraction |
| AI Generation | 680–810 | `generate_concepts()`, `generate_script()`, `voice_check()`, `refine_script()` |
| Background Workers | 810–950 | Threaded processing functions |
| Webhook & Routes | 950–1100 | Flask route handlers |

### Data Flow Architecture

```
┌──────────────┐     HTTPS POST     ┌──────────────┐
│   WhatsApp   │ ──────────────────▶│  Twilio API  │
│   (Honey)    │◀────────────────── │              │
└──────────────┘   Outbound msgs    └──────┬───────┘
                                           │ Webhook
                                           ▼
                                    ┌──────────────┐
                                    │  Flask App   │
                                    │  (Gunicorn)  │
                                    └──────┬───────┘
                                           │
                    ┌──────────────────────┬┴───────────────────────┐
                    │                      │                        │
                    ▼                      ▼                        ▼
             ┌────────────┐        ┌──────────────┐        ┌──────────────┐
             │  Anthropic │        │   Groq API   │        │  Brave Search│
             │ Claude API │        │  (Whisper)   │        │    (optional)│
             └────────────┘        └──────────────┘        └──────────────┘
                    │
                    ▼
             ┌────────────┐        ┌──────────────┐
             │   shelve   │        │  GitHub API  │
             │  (state)   │        │  (library)   │
             └────────────┘        └──────────────┘
```

---

## 4. Environment Variables

### Required Variables (validated at startup)

The application raises `RuntimeError` on startup if any of these are missing:

| Variable | Description | Example |
|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | API key for Anthropic Claude models. Used for all script generation, concept ideation, voice-checking, email parsing, and brand extraction. | `sk-ant-api03-...` |
| `TWILIO_ACCOUNT_SID` | Twilio account SID. Used for REST API authentication and media download. | `AC...` |
| `TWILIO_AUTH_TOKEN` | Twilio auth token. Used alongside SID for REST API and media download basic auth. | `...` |
| `TWILIO_WHATSAPP_NUMBER` | Twilio WhatsApp sender number (the bot's number). Must include `whatsapp:` prefix. | `whatsapp:+14155238886` |
| `GROQ_API_KEY` | API key for Groq's Whisper transcription endpoint. Used for voice note processing. | `gsk_...` |

### Optional Variables

| Variable | Description | Default | Used By |
|----------|-------------|---------|---------|
| `GITHUB_LIBRARY_TOKEN` | GitHub Personal Access Token with repo write permissions. Enables persistent library storage that survives container redeploys. If absent, library is local-only. | `""` (empty) | `_load_from_github()`, `_save_to_github()` |
| `GITHUB_REPO` | GitHub repository in `owner/repo` format where `honey_library.json` is stored. | `shethhoney/honey-script-bot` | `_gh_repo()` |
| `BRAVE_SEARCH_API_KEY` | Brave Search API key. Enables automatic product USP enrichment via web search. If absent, enrichment is silently skipped. | `""` (empty) | `search_product_usps()`, `extract_brand_and_search()` |
| `HONEY_NUMBER` | Honey Sheth's WhatsApp number (with `whatsapp:` prefix). Gates the `save` command so only she can approve scripts to the library. If unset, anyone can save. | `""` (empty) | `save` command handler |
| `PORT` | Port to bind the application to. Railway sets this automatically. | `5000` | `app.run()` |

---

## 5. State Machine

The bot maintains per-user conversation state in a shelve database, keyed by WhatsApp phone number. Each state is a dictionary with a `step` field controlling the conversation flow.

### State Diagram

```
                          ┌──────────────────────────┐
                          │                          │
         greeting/cancel  │         IDLE             │◀────────────────────────┐
         ┌───────────────▶│                          │                         │
         │                │  (last_script may exist) │─────────┐               │
         │                └────────────┬─────────────┘         │               │
         │                             │                       │               │
         │                    new brief│              short msg│               │
         │                  (text/file/│            (with last │               │
         │                   voice)    │              script)  │               │
         │                             ▼                       │               │
         │                ┌──────────────────────┐             │               │
         │                │   AWAITING_FORMAT    │             │               │
         │                │                      │             │               │
         │                │  Reply: 1, 2, or 3   │             │               │
         │                └──────────┬───────────┘             │               │
         │                           │ valid format            │               │
         │                           ▼                         │               │
         │                ┌──────────────────────┐             │               │
         │                │ AWAITING_SUBFORMAT   │             │               │
         │                │                      │             │               │
         │                │ Reply: 1–3 or 1–5    │             │               │
         │                └──────────┬───────────┘             │               │
         │                           │ valid subformat         │               │
         │                           ▼                         │               │
         │                ┌──────────────────────┐             │               │
         │                │     GENERATING       │             │               │
         │                │  (concept phase)     │             │               │
         │                │                      │             │               │
         │                │ Background thread    │             │               │
         │                │ runs concept gen     │             │               │
         │                └──────────┬───────────┘             │               │
         │                           │ concepts ready          │               │
         │                           ▼                         │               │
         │                ┌──────────────────────┐             │               │
         │                │  AWAITING_CONCEPT    │             │               │
         │                │                      │             │               │
         │                │ Reply: 1–4 or "all"  │             │               │
         │                └──────────┬───────────┘             │               │
         │                           │ concept chosen          │               │
         │                           ▼                         │               │
         │                ┌──────────────────────┐             │               │
         │                │     GENERATING       │             │               │
         │                │   (script phase)     │──────────────────────────────┘
         │                │                      │  done → sets step to "idle"
         │                │ Background thread    │  and stores last_script/
         │                │ runs script gen      │  last_caption in state
         │                └──────────────────────┘
         │                                                     │
         │                                        refine text/ │
         │                                        voice note   │
         │                                                     ▼
         │                                        ┌──────────────────────┐
         │                                        │     GENERATING       │
         │                                        │   (refine phase)     │
         │                                        │                      │──┐
         │                                        │ Background thread    │  │
         └────────────────────────────────────────│ runs refine gen      │  │
                                                  └──────────────────────┘  │