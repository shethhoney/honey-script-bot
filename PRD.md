# Product Requirements Document
## Honey Script Bot — WhatsApp Reel Script Generator

**Version:** 2.0
**Date:** 2025-01-31
**Owner:** Honey Sheth
**Status:** Live (Production — Railway deployment)

---

## 1. Overview

Honey Script Bot is a personal WhatsApp-based AI assistant that generates Instagram Reel scripts and captions in the documented creative voice of Honey Sheth — an Indian lifestyle, beauty, and travel content creator. The bot accepts brand briefs in any format (plain text, PDF, Word document, image, voice note, or forwarded brand email), walks the user through a structured format selection flow, generates creative concept options, produces production-ready reel scripts with matching captions, and supports unlimited refinement cycles via text or voice feedback.

**Version 2.0** introduces a **self-learning system**: Honey can approve scripts she's happy with, building a personal library of approved examples. These approved scripts are injected as few-shot examples into every future generation, causing the bot's output to converge on her exact voice over time. Refinement feedback is also logged persistently, allowing the model to learn from recurring correction patterns.

**Primary user:** Honey Sheth (single-user personal tool)
**Interface:** WhatsApp (via Twilio)
**AI backbone:** Anthropic Claude claude-opus-4-6 (script generation), Groq Whisper Large v3 (voice transcription)
**Hosting:** Railway with persistent volume storage at `/data`

---

## 2. Problem Statement

As a content creator managing multiple brand collaborations per month, Honey faces a recurring workflow bottleneck: translating raw brand briefs into polished, on-brand reel scripts and captions. This process is:

- **Time-consuming** — manually drafting a script takes 30–60 minutes per brief, multiplied across 5–15 collaborations per month
- **Inconsistent** — maintaining a precise creative voice across formats (IMMBT, event coverage, brand collaborations) is difficult under deadline pressure
- **Friction-heavy** — briefs arrive in many formats (PDFs, forwarded emails, screenshots, WhatsApp voice memos) requiring manual extraction and reformatting before writing can even begin
- **Iterative** — first drafts typically need 2–3 refinement rounds, each requiring context recall and re-reading
- **Non-cumulative** — feedback given on past scripts doesn't carry forward; the same corrections get repeated

### What v2.0 specifically addresses

Version 1.0 solved the generation and refinement loop. Version 2.0 adds a **learning layer**: the system now accumulates approved scripts and refinement feedback over time, meaning every future script is informed by what Honey has already approved and what she's consistently asked to change. The bot gets better the more it's used.

**The goal:** eliminate manual scripting time, enable brief-to-filming in minutes, and build a system that learns Honey's voice with every interaction.

---

## 3. Target User

**Primary and sole user: Honey Sheth**

| Attribute | Detail |
|-----------|--------|
| Role | Indian lifestyle, beauty, and travel content creator |
| Collaboration volume | 5–15 brand collaborations per month |
| Brief sources | WhatsApp messages, forwarded emails, PDFs, voice memos, screenshots |
| Content categories | IMMBT (Instagram Made Me Buy This), Event coverage, Brand collaborations |
| Technical proficiency | Non-technical — interface must be entirely conversational within WhatsApp |
| Devices | Mobile-first (WhatsApp on phone) |

---

## 4. User Goals

| Goal | Priority |
|------|----------|
| Generate a reel script + caption from any brand brief in under 60 seconds | P0 |
| Receive content that sounds authentically like Honey — not generic AI | P0 |
| Submit briefs in whatever format they arrive (no reformatting required) | P0 |
| Choose from multiple creative concepts before committing to a direction | P1 |
| Refine scripts via natural text or voice feedback without restarting | P1 |
| Get a matching caption (different angle from the video) with every script | P1 |
| Approve scripts to teach the bot her exact voice over time | P1 |
| Use the tool entirely within WhatsApp — no app, no login, no dashboard | P2 |
| Review her library of approved scripts and feedback history | P2 |

---

## 5. Non-Goals

- Multi-user support or team collaboration features
- Analytics dashboards or usage reporting
- Content scheduling, posting automation, or calendar integration
- Script approval workflows with external stakeholders
- Support for platforms other than Instagram Reels (YouTube Shorts, TikTok, etc.)
- Real-time brand research, product lookup, or competitive analysis
- Multi-language caption generation
- Side-by-side draft comparison UI
- Auto-format detection from brief content (format selection is menu-driven by design)

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
          │ 1 script │ │ All 4        │
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
          │ → Script added to      │
          │   approved library     │
          │ → Future scripts learn │
          │   from this example    │
          └────────────────────────┘
```

---

## 7. Functional Requirements

### 7.1 Brief Ingestion

| ID | Requirement | Details |
|----|-------------|---------|
| FR-01 | Accept plain text briefs | Any WhatsApp text message treated as a brief when no active flow exists |
| FR-02 | Accept and extract text from PDF attachments | Uses PyPDF2; returns extracted text for processing |
| FR-03 | Accept and extract text from Word (.docx) attachments | Uses mammoth library for raw text extraction |
| FR-04 | Accept image/screenshot attachments | Image is base64-encoded and sent to Claude claude-opus-4-6 via vision (multimodal) for text extraction and script generation in a single pass |
| FR-05 | Accept voice note briefs | Audio downloaded from Twilio, transcribed via Groq Whisper Large v3, then treated as a text brief |
| FR-06 | Detect forwarded brand emails | Heuristic detection based on signal keywords (≥2 of: "from:", "subject:", "dear honey", "deliverables", "collaboration", etc.) |
| FR-07 | Extract structured brief from detected emails | Claude claude-opus-4-6 extracts: Brand, Product, Key Claims, Deliverables, Deadline, Extra Notes; confirmed back to user before proceeding |
| FR-08 | Reject excessively long briefs | Briefs exceeding 8,000 characters are rejected with a message asking user to trim to key details |
| FR-09 | Handle extraction failures gracefully | If PDF/DOCX/image extraction fails or yields <10 characters, user is asked to paste as plain text |
| FR-10 | Support multiple audio formats | .ogg, .m4a, .mp3, .mp4, .webm — auto-detected from content type |

### 7.2 Format & Sub-Format Selection

| ID | Requirement | Details |
|----|-------------|---------|
| FR-11 | Present a 3-option format menu | After brief extraction: 1️⃣ IMMBT, 2️⃣ Event coverage, 3️⃣ Collaboration |
| FR-12 | Present sub-format menu per category | IMMBT (3 options), Event (3 options), Collaboration (5 options) — see Section 7.2.1 |
| FR-13 | Validate input at each selection step | Invalid input triggers re-prompt with the same menu; only valid numeric options accepted |
| FR-14 | Map sub-format to descriptive label | Each sub-format resolves to a full descriptive label used in prompt construction (e.g., "IMMBT — viral hype check, sceptic who gets won over") |

#### 7.2.1 Sub-Format Options

**IMMBT (Instagram Made Me Buy This):**
1. Single product discovery
2. Viral / hype check
3. Sceptic won over

**Event coverage:**
1. Brand booth or launch
2. Destination / travel day
3. Community or group event

**Collaboration:**
1. Routine or tutorial
2. Personal narrative
3. Multi-product or haul
4. Gifting or occasion
5. Platform or retail

### 7.3 Concept Generation

| ID | Requirement | Details |
|----|-------------|---------|
| FR-15 | Generate 4 distinct creative concepts per brief | Each concept has a different angle, hook, or emotional approach; generated by Claude claude-opus-4-6 with system prompt |
| FR-16 | Inject approved library examples into concept generation | Up to 3 most relevant approved scripts (matching format preferred) included in prompt as few-shot examples |
| FR-17 | Present concepts as numbered options | Displayed as 1️⃣–4️⃣ with title and 2-sentence description each |
| FR-18 | Allow single concept selection | User replies 1–4 to select one concept for script generation |
| FR-19 | Allow "all" option | User replies "all" to receive all 4 concepts written as full script variations |
| FR-20 | Parse concept text dynamically | Regex-based extraction of CONCEPT N patterns; handles variable concept counts |
| FR-21 | Show progress indicator | If concept generation exceeds 15 seconds, send "Thinking up concepts… almost there ✍️" |
| FR-22 | Handle concept generation failure | If parsing fails or API errors, user is