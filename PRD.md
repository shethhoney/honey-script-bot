# Product Requirements Document
## Honey Script Bot — WhatsApp Reel Script Generator

**Version:** 1.0
**Date:** 2026-04-02
**Owner:** Honey Sheth
**Status:** Live (Production)

---

## 1. Overview

Honey Script Bot is a personal WhatsApp-based AI tool that generates Instagram Reel scripts and captions in Honey Sheth's documented creative voice. It accepts brand briefs in any format — text, PDF, Word doc, image, or voice note — and returns a production-ready reel script plus caption within ~30 seconds.

---

## 2. Problem Statement

As an Indian lifestyle, beauty, and travel content creator managing multiple brand collaborations, Honey faces a recurring bottleneck: translating raw brand briefs into polished, on-brand reel scripts. This process is:

- **Time-consuming** — drafting scripts manually takes 30–60 minutes per brief
- **Inconsistent** — maintaining a consistent creative voice across formats is hard under deadline pressure
- **Friction-heavy** — briefs arrive in many formats (PDFs, forwarded emails, screenshots, voice memos)
- **Iterative** — first drafts typically need 2–3 refinement rounds

**The goal:** eliminate manual scripting time so Honey can go from brief to filming in minutes.

---

## 3. Target User

**Primary user: Honey Sheth (single-user personal tool)**

- Indian lifestyle, beauty, and travel content creator
- Manages 5–15 brand collaborations per month
- Receives briefs via WhatsApp, email, PDF, and verbally
- Creates content in three primary categories: IMMBT (Instagram Made Me Buy This), Event coverage, Brand collaborations
- Non-technical user — interface must be entirely conversational (WhatsApp)

---

## 4. User Goals

| Goal | Priority |
|------|----------|
| Generate a reel script from a brand brief in under 60 seconds | P0 |
| Receive content that sounds authentically like Honey, not generic AI | P0 |
| Submit briefs in whatever format they arrive (no copy-pasting required) | P0 |
| Refine scripts via natural feedback without restarting | P1 |
| Choose from multiple creative concepts before committing to a direction | P1 |
| Get matching caption (different angle from the video) alongside every script | P1 |
| Use the tool entirely within WhatsApp — no app to install | P2 |

---

## 5. Non-Goals

- Multi-user support (this is a personal tool for one creator)
- Analytics, dashboards, or usage reporting
- Content scheduling or posting automation
- Script approval workflows or team collaboration
- Support for platforms other than Instagram Reels (YouTube Shorts, TikTok, etc.)
- Real-time brand research or product lookup

---

## 6. User Flow

```
User sends brief (text / PDF / Word / image / voice note)
        │
        ▼
Bot detects format → extracts text
        │
        ├── [Email detected] → extract structured brief → confirm to user
        │
        ▼
Format selection: IMMBT / Event / Collaboration
        │
        ▼
Sub-format selection (3–5 options per category)
        │
        ▼
Bot generates 4 creative concept hooks
        │
        ▼
User picks concept 1–4 (or "all" for all 4 scripts)
        │
        ▼
Bot generates full Reel Script + Caption (~30 sec)
        │
        ▼
User sends text or voice feedback
        │
        ▼
Bot refines script → returns updated version
        │
        └── [Loop] Refine as many times as needed
```

---

## 7. Functional Requirements

### 7.1 Brief Ingestion
- **FR-01:** Accept plain text briefs via WhatsApp message
- **FR-02:** Accept and extract text from PDF attachments
- **FR-03:** Accept and extract text from Word (.docx) attachments
- **FR-04:** Accept image/screenshot attachments and extract text via Claude vision
- **FR-05:** Accept voice note attachments and transcribe using Groq Whisper
- **FR-06:** Detect forwarded brand emails and extract structured brief (brand, product, claims, deliverables, deadline)

### 7.2 Format Selection
- **FR-07:** Present a 3-option format menu: IMMBT / Event / Collaboration
- **FR-08:** Present a sub-format menu per category:
  - IMMBT: Single product discovery / Viral hype check / Sceptic won over
  - Event: Brand booth or launch / Destination or travel day / Community or group event
  - Collaboration: Routine or tutorial / Personal narrative / Multi-product haul / Gifting or occasion / Platform or retail
- **FR-09:** Validate user input at each selection step and re-prompt on invalid input

### 7.3 Concept Generation
- **FR-10:** Generate 4 distinct creative concepts per brief, each with a different hook or angle
- **FR-11:** Present concepts as numbered options
- **FR-12:** Allow user to select one concept (1–4) or request all 4 scripts written out ("all")

### 7.4 Script Generation
- **FR-13:** Generate a full reel script following Honey's documented emotional arc: Hook → Product Moment → Demo/Experience → Transformation/Reflection → CTA
- **FR-14:** Generate a matching caption (different angle from video — quieter, more reflective)
- **FR-15:** Include proper script cues: Visual, PTC (piece-to-camera), VO (voiceover), Super (text overlay)
- **FR-16:** Respect format-specific content guidelines per sub-format
- **FR-17:** Never include product overclaiming, hard-sell CTAs, or feature dumps

### 7.5 Voice & Refinement
- **FR-18:** Accept voice note feedback on existing scripts and treat as refinement instruction
- **FR-19:** Distinguish voice notes as new briefs vs. refinement feedback based on conversation state
- **FR-20:** Retain brief context and previous script during refinement — only change what was requested
- **FR-21:** Support unlimited refinement rounds per session

### 7.6 Conversation Management
- **FR-22:** Respond to "hi", "hello", "hey", "start" with a welcome message and reset state
- **FR-23:** Respond to "help" with command reference
- **FR-24:** Respond to "cancel" to abandon current flow and reset
- **FR-25:** Persist conversation state per phone number across messages
- **FR-26:** Detect short follow-up messages (< 200 chars) after a script has been delivered and prompt for refinement

### 7.7 Delivery
- **FR-27:** Chunk all messages exceeding 1,500 characters (WhatsApp limit)
- **FR-28:** Send progress messages ("Still writing… almost there ✍️") if generation exceeds 15–20 seconds
- **FR-29:** Send script and caption as separate messages for readability

---

## 8. Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| Script generation time (P95) | < 45 seconds |
| Concept generation time (P95) | < 20 seconds |
| Audio transcription time | < 15 seconds |
| Uptime | > 99% (self-ping mechanism to prevent sleep) |
| State persistence | Survives server restarts (shelve on /tmp) |
| Message chunking | All messages ≤ 1,500 characters |
| Concurrent users | Single primary user; threading supports parallel requests |

---

## 9. Content Voice Requirements

The system prompt encodes 37 documented Honey Sheth scripts. Key voice rules:

- **Tone:** Warm, confident, visually descriptive — luxury feels lived-in, never distant
- **Authenticity:** "I noticed" and "it feels like" — not "it transformed my skin"
- **Structure:** Each piece reads like a small story: sensory, honest, reflective
- **Hindi code-switching:** Natural, only when emotion calls for it — never forced
- **Product placement:** Product earns its place in the story; 1–2 benefits max
- **Captions:** Quieter, more essay-like than the video; fewer emojis; extends the story

---

## 10. Success Metrics

| Metric | Target |
|--------|--------|
| Briefs successfully processed (no errors) | > 95% |
| Scripts requiring 0–1 refinement rounds to approval | > 70% |
| Voice notes successfully transcribed | > 90% |
| Files (PDF/DOCX) successfully extracted | > 95% |
| Time from brief submission to usable script | < 60 seconds |

---

## 11. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| API downtime (Anthropic / Groq / Twilio) | Error messages guide user to retry; stateless retry supported |
| Voice note format not supported | Multi-format fallback (.ogg, .m4a, .mp3, .webm) |
| Password-protected PDFs fail extraction | Error message advises plain text paste |
| State loss on /tmp restart | User can re-send brief; state rebuilds |
| WhatsApp sandbox expiry | SETUP_GUIDE covers production number upgrade path |
| Model API costs | ~$0.01–0.03/script; acceptable at current usage volume |

---

## 12. Out-of-Scope for v1

- Saved script history / archive
- Draft comparisons side-by-side
- Auto-format detection from brief content (currently menu-driven)
- Multi-language caption support
- Integration with content calendar tools

---

## 13. Launch Checklist

- [x] WhatsApp Twilio sandbox configured
- [x] Railway/Render deployment active
- [x] All 4 environment variables set (Anthropic, Twilio x3, Groq)
- [x] Webhook URL registered in Twilio
- [x] Self-ping active to prevent sleep
- [x] SETUP_GUIDE.md published in repo
- [ ] Twilio production WhatsApp number (when sandbox testing complete)
