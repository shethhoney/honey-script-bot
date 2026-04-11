# Product Requirements Document
## Honey Script Bot — WhatsApp Reel Script Generator

**Version:** 2.0
**Date:** 2025-07-14
**Owner:** Honey Sheth
**Status:** Live (Production — Railway deployment with persistent volume storage)

---

## 1. Overview

Honey Script Bot is a personal, single-user WhatsApp-based AI assistant that generates production-ready Instagram Reel scripts and captions in the documented creative voice of Honey Sheth — an Indian lifestyle, beauty, and travel content creator.

The system accepts brand briefs in any format they naturally arrive — plain text, PDF, Word document, image/screenshot, voice note, or forwarded brand email — and walks the user through a structured content creation pipeline:

1. **Brief ingestion** — automatic extraction and parsing of brand brief content regardless of input format
2. **Format and sub-format selection** — guided menu-driven selection across 3 content categories and 11 sub-formats
3. **Concept generation** — 4 distinct creative concepts with different hooks and angles for the user to evaluate
4. **Script and caption generation** — full production-ready reel scripts with matched captions, following Honey's documented emotional arc and voice
5. **Iterative refinement** — unlimited text or voice-based feedback loops to converge on the final output
6. **Self-learning system** — approved scripts are saved to a persistent library and injected as few-shot examples into future generations; refinement feedback is logged and used to avoid repeating past mistakes

The bot is built on a Flask application deployed to Railway with persistent volume storage, using Anthropic Claude claude-opus-4-6 as the primary generation model, Groq Whisper Large v3 for voice transcription, Brave Search API for optional product enrichment, and Twilio WhatsApp Business API as the messaging interface.

| Attribute | Detail |
|---|---|
| **Primary user** | Honey Sheth (single-user personal tool) |
| **Interface** | WhatsApp via Twilio WhatsApp Business API |
| **AI backbone — generation** | Anthropic Claude claude-opus-4-6 (scripts, captions, concepts, email extraction, brand identification) |
| **AI backbone — brand extraction** | Anthropic Claude claude-haiku-4-5-20251001 (lightweight brand/product name extraction for web search) |
| **AI backbone — transcription** | Groq Whisper Large v3 (voice note → text) |
| **Web enrichment** | Brave Search API (optional — product USP lookup, up to 5 results) |
| **Hosting** | Railway with persistent volume mounted at `/data` (fallback: `/tmp`) |
| **Persistent storage** | Python `shelve` for conversation state; JSON files for script library (`honey_library.json`) and feedback log (`honey_feedback.json`) |
| **Message delivery** | Twilio REST Client for outbound messages; chunked delivery for messages exceeding 1,500 characters |

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

1. **Learning from approvals** — Approved scripts are stored in a persistent library (rolling window of 20) and injected as few-shot examples into every future generation, so the bot's voice converges on what Honey actually signs off on — not just what the system prompt describes.
2. **Learning from corrections** — Refinement feedback is logged persistently (rolling window of 30 entries) and injected into refinement prompts, so the bot learns from recurring correction patterns and stops making the same mistakes.
3. **Web enrichment** — When a Brave Search API key is configured, the bot automatically extracts the brand and product name from the brief, searches for real product USPs, ingredients, and claims online, and enriches the brief before generation — producing scripts with specific, accurate product details instead of vague placeholders.

**The goal:** eliminate manual scripting time, enable brief-to-filming in minutes, and build a system that gets measurably better at matching Honey's voice with every interaction.

---

## 3. Functional Requirements

### 3.1 Brief Ingestion

| ID | Requirement | Details |
|---|---|---|
| FR-01 | **Accept plain text briefs** | Any WhatsApp text message is treated as a new brief when no active flow exists and no prior script is loaded. Messages under 500 characters when a prior script exists are treated as refinement feedback instead (see FR-33). Briefs exceeding 8,000 characters are rejected with a prompt to trim. |
| FR-02 | **Accept and extract text from PDF attachments** | Uses PyPDF2 to read all pages and concatenate extracted text. Handles extraction failures gracefully with a fallback message asking the user to paste as plain text. |
| FR-03 | **Accept and extract text from Word (.docx) attachments** | Uses mammoth library for raw text extraction from .docx files. Content type detection covers `word`, `docx`, and `officedocument` MIME type variants. |
| FR-04 | **Accept image/screenshot attachments** | Image is base64-encoded and passed to Claude claude-opus-4-6 via multimodal vision input during the generation step. The image is stored in the brief field as a `[IMAGE:base64:content_type]` token and processed inline — text extraction and script generation happen in a single API call. If the image token cannot be parsed at generation time, the user is asked to resend in another format. |
| FR-05 | **Accept voice note briefs** | Audio is downloaded from Twilio media URL, saved to a temporary file with the appropriate extension (`.ogg`, `.m4a`, `.mp3`, `.webm`), transcribed via Groq Whisper Large v3, and then treated as a text brief. Transcription is echoed back to the user in italics for confirmation before proceeding to format selection. Supported audio MIME type keywords: `audio`, `ogg`, `mpeg`, `mp4`, `webm`. |
| FR-06 | **Detect forwarded brand emails** | Heuristic detection based on signal keyword count: if ≥2 of the following appear in the message text — `from:`, `subject:`, `dear honey`, `hi honey`, `hello honey`, `we would like`, `we are reaching out`, `collaboration`, `partnership`, `deliverables`, `compensation`, `deadline`, `fwd:`, `forwarded message`, `------` — the message is classified as a forwarded email. Only triggered for text messages (not media attachments). |
| FR-07 | **Extract structured brief from detected emails** | When an email is detected (FR-06), Claude claude-opus-4-6 extracts a structured brief in the format: Brand, Product, Key Claims, Deliverables, Deadline, Extra Notes. The extracted brief is sent back to the user for transparency, then used as the brief text for the remainder of the flow. Falls back to the raw email text if extraction fails. |
| FR-08 | **Reject empty or insufficient briefs** | If extracted text is empty or under 10 characters, the user is prompted to resend in a different format or paste as plain text. |
| FR-09 | **Reject oversized briefs** | Text briefs exceeding 8,000 characters are rejected with a message asking the user to trim to key details: brand, product, key claims, and deliverables. |

### 3.2 Web Enrichment

| ID | Requirement | Details |
|---|---|---|
| FR-10 | **Automatic brand and product extraction** | When a Brave Search API key is configured (`BRAVE_SEARCH_API_KEY` environment variable), the bot uses Claude claude-haiku-4-5-20251001 to extract the brand name and product name from the first 600 characters of the brief. Returns empty if extraction yields "unknown" for the brand. |
| FR-11 | **Product USP web search** | Using the extracted brand and product name, the bot queries Brave Search API with the query pattern `{brand} {product} key ingredients benefits claims`, retrieves up to 5 web results, and extracts title + description snippets. |
| FR-12 | **Brief enrichment injection** | Web search results are appended to the brief text as a `WEB-FETCHED PRODUCT DETAILS` section with a directive to use the facts for specificity and accuracy. The enriched brief is persisted to state so it carries through to concept generation, script generation, and refinement. User is notified with a message: "🔍 Found product details online — enriching your brief with real USPs..." |
| FR-13 | **Graceful degradation without Brave API key** | All web enrichment is skipped silently if `BRAVE_SEARCH_API_KEY` is not set or is empty. The bot functions identically to the non-enriched flow. Search failures are caught and logged without user-facing errors. |

### 3.3 Format and Sub-Format Selection

| ID | Requirement | Details |
|---|---|---|
| FR-14 | **Three-category format menu** | After brief ingestion, the bot presents a numbered menu with three content categories: (1) IMMBT — Instagram Made Me Buy This, (2) Event coverage — launch, experience, destination, (3) Collaboration — routine, narrative, haul, gifting. User replies with `1`, `2`, or `3`. Invalid responses re-display the menu. |
| FR-15 | **Sub-format selection per category** | Each category has a secondary menu: IMMBT has 3 sub-formats (single product discovery, viral hype check, sceptic won over); Event has 3 sub-formats (brand booth/launch, destination/travel day, community/group event); Collaboration has 5 sub-formats (routine/tutorial, personal narrative, multi-product haul, gifting/occasion, platform/retail). User selects by number. Invalid responses re-display the sub-menu. |
| FR-16 | **Sub-format label persistence** | The selected sub-format is stored as a human-readable label (e.g., "IMMBT — single product discovery", "Brand collaboration — personal narrative, emotional hook, product as solution") and used in all subsequent prompts for concept generation, script generation, and refinement. |

### 3.4 Concept Generation

| ID | Requirement | Details |
|---|---|---|
| FR-17 | **Generate 4 distinct creative concepts** | After sub-format selection, the bot generates 4 creative concept options via Claude claude-opus-4-6, each with a different angle, hook, or emotional approach. Concepts are generated using the system prompt, the brief text (including any web enrichment), the selected format label, and any approved library examples (see FR-28). |
| FR-18 | **Concept parsing and presentation** | Concepts are parsed from the model output using regex (`CONCEPT \d+:` pattern) and presented as a numbered list. Each concept includes a short title and a 2-sentence description of the hook and angle. |
| FR-19 | **Concept selection** | User replies with a number (`1` through `4`, or however many were successfully parsed) to select a single concept, or replies `all` to have all concepts written out as full script variations. Invalid responses re-display the options. |
| FR-20 | **Progress indicator for concept generation** | A "Thinking up concepts… almost there ✍️" message is sent after 15 seconds if generation has not completed. |
| FR-21 | **Concept generation failure handling** | If concepts cannot be parsed from the model output, state resets to idle and the user is asked to send their brief again. |

### 3.5 Script and Caption Generation

| ID