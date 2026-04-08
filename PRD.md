# Product Requirements Document
## Honey Script Bot — WhatsApp Reel Script Generator

**Version:** 2.0
**Date:** 2025-07-09
**Owner:** Honey Sheth
**Status:** Live (Production — Railway deployment with persistent volume storage)

---

## 1. Overview

Honey Script Bot is a personal, single-user WhatsApp-based AI assistant that generates production-ready Instagram Reel scripts and captions in the documented creative voice of Honey Sheth — an Indian lifestyle, beauty, and travel content creator. The system accepts brand briefs in any format they naturally arrive (plain text, PDF, Word document, image/screenshot, voice note, or forwarded brand email), walks the user through a structured format and sub-format selection flow, generates multiple creative concept options, produces full reel scripts with matching captions, and supports unlimited iterative refinement via text or voice feedback.

**Version 2.0** introduces a **self-learning system**: Honey can approve scripts she's happy with by typing `save`, building a persistent personal library of approved examples. These approved scripts are injected as few-shot examples into every future generation, causing the bot's output to converge on her exact voice over time. Refinement feedback is also logged persistently, allowing the model to learn from recurring correction patterns and avoid repeating mistakes Honey has previously flagged.

| Attribute | Detail |
|---|---|
| **Primary user** | Honey Sheth (single-user personal tool) |
| **Interface** | WhatsApp via Twilio WhatsApp Business API |
| **AI backbone — generation** | Anthropic Claude claude-opus-4-6 (script, caption, concept, email extraction, brand identification) |
| **AI backbone — brand extraction** | Anthropic Claude claude-haiku-4-5-20251001 (lightweight brand/product name extraction for web search) |
| **AI backbone — transcription** | Groq Whisper Large v3 (voice note → text) |
| **Web enrichment** | Brave Search API (optional — product USP lookup) |
| **Hosting** | Railway with persistent volume mounted at `/data` (fallback: `/tmp`) |
| **Persistent storage** | Python `shelve` for conversation state; JSON files for script library and feedback log |

---

## 2. Problem Statement

As a content creator managing multiple brand collaborations per month, Honey faces a recurring workflow bottleneck: translating raw brand briefs into polished, on-brand reel scripts and captions. This process is:

- **Time-consuming** — manually drafting a script takes 30–60 minutes per brief, multiplied across 5–15 collaborations per month
- **Inconsistent** — maintaining a precise creative voice across formats (IMMBT, event coverage, brand collaborations) is difficult under deadline pressure
- **Friction-heavy** — briefs arrive in many formats (PDFs, forwarded emails, screenshots, WhatsApp voice memos) requiring manual extraction and reformatting before writing can even begin
- **Iterative** — first drafts typically need 2–3 refinement rounds, each requiring full context recall and re-reading of the original brief
- **Non-cumulative** — feedback given on past scripts doesn't carry forward; the same corrections get repeated across sessions, and the system starts from zero every time

### What Version 2.0 Specifically Addresses

Version 1.0 solved the generation and refinement loop. Version 2.0 adds three critical layers:

1. **Learning from approvals** — Approved scripts are stored in a persistent library (rolling window of 20) and injected as few-shot examples into every future generation, so the bot's voice converges on what Honey actually signs off on.
2. **Learning from corrections** — Refinement feedback is logged persistently (rolling window of 30 entries) and injected into refinement prompts, so the bot learns from recurring correction patterns and stops making the same mistakes.
3. **Web enrichment** — When a Brave Search API key is configured, the bot automatically extracts the brand and product name from the brief, searches for real product USPs, ingredients, and claims online, and enriches the brief before generation — producing scripts with specific, accurate product details instead of vague placeholders.

**The goal:** eliminate manual scripting time, enable brief-to-filming in minutes, and build a system that learns Honey's voice with every interaction.

---

## 3. Target User

**Primary and sole user: Honey Sheth**

| Attribute | Detail |
|---|---|
| Role | Indian lifestyle, beauty, and travel content creator |
| Collaboration volume | 5–15 brand collaborations per month |
| Brief sources | WhatsApp messages, forwarded emails, PDFs, voice memos, screenshots |
| Content categories | IMMBT (Instagram Made Me Buy This), Event coverage, Brand collaborations |
| Technical proficiency | Non-technical — interface must be entirely conversational within WhatsApp |
| Devices | Mobile-first (WhatsApp on phone) |

---

## 4. User Goals

| Goal | Priority |
|---|---|
| Generate a reel script + caption from any brand brief in under 60 seconds | P0 |
| Receive content that sounds authentically like Honey — not generic AI | P0 |
| Submit briefs in whatever format they arrive (no reformatting required) | P0 |
| Choose from multiple creative concepts before committing to a direction | P1 |
| Refine scripts via natural text or voice feedback without restarting | P1 |
| Get a matching caption (different angle from the video) with every script | P1 |
| Approve scripts to teach the bot her exact voice over time | P1 |
| Have the bot enrich briefs with real product details from the web | P1 |
| Use the tool entirely within WhatsApp — no app, no login, no dashboard | P2 |
| Review her library of approved scripts and feedback history | P2 |

---

## 5. Non-Goals

- Multi-user support or team collaboration features
- Analytics dashboards or usage reporting
- Content scheduling, posting automation, or calendar integration
- Script approval workflows with external stakeholders
- Support for platforms other than Instagram Reels (YouTube Shorts, TikTok, etc.)
- Multi-language caption generation (Hindi is used organically as part of Honey's code-switching voice, not as a separate language mode)
- Side-by-side draft comparison UI
- Auto-format detection from brief content (format selection is menu-driven by design)
- Persistent conversation history across sessions (only current flow state and library persist)

---

## 6. User Flow

```
┌─────────────────────────────────────────────────────────┐
│  User sends brief                                       │
│  (text / PDF / Word / image / voice note / email)       │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
          ┌────────────────────────┐
          │ Bot detects format     │
          │ → extracts text        │
          ├────────────────────────┤
          │ [Email detected]       │
          │ → extract structured   │
          │   brief via Claude     │
          │ → confirm to user      │
          ├────────────────────────┤
          │ [Voice note]           │
          │ → transcribe via Groq  │
          │ → confirm transcription│
          └────────────┬───────────┘
                       │
                       ▼
          ┌────────────────────────┐
          │ Format selection       │
          │ 1. IMMBT               │
          │ 2. Event coverage      │
          │ 3. Collaboration       │
          └────────────┬───────────┘
                       │
                       ▼
          ┌────────────────────────┐
          │ Sub-format selection   │
          │ (3–5 options per       │
          │  category)             │
          └────────────┬───────────┘
                       │
                       ▼
          ┌────────────────────────┐
          │ [Optional] Web search  │
          │ enrichment for product │
          │ USPs via Brave API     │
          └────────────┬───────────┘
                       │
                       ▼
          ┌────────────────────────┐
          │ Bot generates 4        │
          │ creative concepts      │
          │ (~15 sec)              │
          └────────────┬───────────┘
                       │
                       ▼
          ┌────────────────────────┐
          │ User picks concept     │
          │ (1–4) or "all"         │
          └───────┬────────┬───────┘
                  │        │
            [single]    ["all"]
                  │        │
                  ▼        ▼
          ┌──────────┐ ┌──────────────┐
          │ 1 script │ │ All N        │
          │ + caption│ │ variations   │
          │ (~30s)   │ │ (~60s)       │
          └────┬─────┘ └──────┬───────┘
               │              │
               └──────┬───────┘
                      │
                      ▼
          ┌────────────────────────┐
          │ User sends feedback    │
          │ (text or voice note)   │
          │                        │
          │ → Bot refines script   │
          │ → Feedback logged      │
          │                        │
          │ [Loop unlimited times] │
          └────────────┬───────────┘
                       │
                       ▼
          ┌────────────────────────┐
          │ User types "save"      │
          │ → Script + caption     │
          │   added to approved    │
          │   library              │
          │ → Future scripts learn │
          │   from this example    │
          └────────────┬───────────┘
                       │
                       ▼
          ┌────────────────────────┐
          │ Send new brief to      │
          │ start fresh            │
          │ — OR —                 │
          │ Short message auto-    │
          │ treated as refinement  │
          │ of last script         │
          └────────────────────────┘
```

---

## 7. Functional Requirements

### 7.1 Brief Ingestion

| ID | Requirement | Details |
|---|---|---|
| FR-01 | Accept plain text briefs | Any WhatsApp text message is treated as a brief when no active flow exists and no prior script is loaded. Messages under 500 characters when a prior script exists are treated as refinement feedback instead. |
| FR-02 | Accept and extract text from PDF attachments | Uses PyPDF2 to read all pages and concatenate extracted text. Handles extraction failures gracefully. |
| FR-03 | Accept and extract text from Word (.docx) attachments | Uses mammoth library for raw text extraction from .docx files. Content type detection includes "word", "docx", and "officedocument" variants. |
| FR-04 | Accept image/screenshot attachments | Image is base64-encoded and sent to Claude claude-opus-4-6 via multimodal vision input. The image is processed inline — text extraction and script generation happen in a single API call during the generation step. |
| FR-05 | Accept voice note briefs | Audio is downloaded from Twilio media URL, transcribed via Groq Whisper Large v3, then treated as a text brief. Transcription is echoed back to the user for confirmation before proceeding to format selection. |
| FR-06 | Detect forwarded brand emails | Heuristic detection based on signal keyword count: if ≥2 of the following appear in the text — "from:", "subject:", "dear honey", "hi honey", "hello honey", "we would like", "we are reaching out", "collaboration", "partnership", "deliverables", "compensation", "deadline", "fwd:", "forwarded message", "------" — the message is classified as a forwarded email. |
| FR-07 | Extract structured brief from detected emails | Claude claude-opus-4-6 extracts a structured brief in the format: Brand, Product, Key Claims, Deliverables, Deadline, Extra Notes. Extracted brief is sent back to the user for