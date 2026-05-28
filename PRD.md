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

1. **Brief ingestion** — automatic extraction and parsing of brand brief content regardless of input format, including auto-detection of forwarded brand emails and image-based briefs
2. **Web enrichment** — optional automatic lookup of real product USPs, ingredients, and claims via Brave Search API to ground scripts in factual product detail
3. **Format and sub-format selection** — guided menu-driven selection across 3 content categories and 11 sub-formats
4. **Concept generation** — 4 distinct creative concepts with different hooks and angles for the user to evaluate before committing to a full script
5. **Script and caption generation** — full production-ready reel scripts with Visual/PTC/VO/Super cues and matched captions, following Honey's documented emotional arc and voice
6. **Voice check pass** — automated second-pass quality gate using Claude Haiku to catch generic language, overclaims, pushy CTAs, and caption drift before delivery
7. **Iterative refinement** — unlimited text or voice-based feedback loops to converge on the final output
8. **Self-learning system** — approved scripts are saved to a persistent library and injected as few-shot examples into future generations; refinement feedback is logged and used to avoid repeating past mistakes

### Architecture Summary

| Attribute | Detail |
|---|---|
| **Primary user** | Honey Sheth (single-user personal tool) |
| **Interface** | WhatsApp via Twilio WhatsApp Business API |
| **AI backbone — generation** | Anthropic Claude claude-opus-4-6 (scripts, captions, concepts, email extraction, brand identification) |
| **AI backbone — voice check** | Anthropic Claude claude-haiku-4-5-20251001 (post-generation quality pass for voice compliance) |
| **AI backbone — brand extraction** | Anthropic Claude claude-haiku-4-5-20251001 (lightweight brand/product name extraction for web search) |
| **AI backbone — transcription** | Groq Whisper Large v3 (voice note → text) |
| **Web enrichment** | Brave Search API (optional — product USP lookup, up to 5 results) |
| **Hosting** | Railway with persistent volume mounted at `/data` (fallback: `/tmp`) |
| **Persistent storage — state** | Python `shelve` for conversation state (`honey_state`) with thread-safe locking via `threading.Lock` |
| **Persistent storage — library** | GitHub repository (`honey_library.json`) as primary, local JSON file as backup, in-memory cache with 300-second TTL |
| **Persistent storage — feedback** | Local JSON file (`honey_feedback.json`) |
| **Message delivery** | Twilio REST Client for outbound messages; chunked delivery for messages exceeding 1,500 characters with 0.5-second inter-chunk delay |
| **Background processing** | Python `threading` for non-blocking generation, refinement, transcription, and progress notifications |

### Key Limits

| Parameter | Value |
|---|---|
| Maximum library size | 200 approved scripts (rolling window — oldest trimmed) |
| Maximum feedback log size | 30 entries (rolling window — oldest trimmed) |
| Examples injected per generation | 5 approved scripts (format-prioritised) |
| Examples injected per refinement | 2 approved scripts |
| Library cache TTL | 300 seconds |
| Message chunk size | 1,500 characters |
| Maximum brief length | 8,000 characters |
| Minimum brief length | 10 characters |
| Progress notification delay — concepts | 15 seconds |
| Progress notification delay — scripts/refines | 20 seconds |

### Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Claude API access for generation, voice check, email extraction, brand extraction |
| `TWILIO_ACCOUNT_SID` | Yes | Twilio account authentication and media download |
| `TWILIO_AUTH_TOKEN` | Yes | Twilio account authentication and media download |
| `TWILIO_WHATSAPP_NUMBER` | Yes | Outbound WhatsApp sender number |
| `GROQ_API_KEY` | Yes | Groq Whisper API access for voice transcription |
| `BRAVE_SEARCH_API_KEY` | No | Brave Search API for web enrichment; all enrichment skipped if absent |
| `GITHUB_LIBRARY_TOKEN` | No | GitHub Personal Access Token for library persistence; falls back to local-only storage if absent |
| `GITHUB_REPO` | No | GitHub repository path (default: `shethhoney/honey-script-bot`) |
| `HONEY_NUMBER` | No | Honey's WhatsApp number for gating the `save` command; if unset, anyone can save |
| `PORT` | No | HTTP server port (default: `5000`) |

---

## 2. Problem Statement

As a content creator managing multiple brand collaborations per month, Honey faces a recurring workflow bottleneck: translating raw brand briefs into polished, on-brand reel scripts and captions. This process is:

- **Time-consuming** — manually drafting a script takes 30–60 minutes per brief, multiplied across 5–15 collaborations per month
- **Inconsistent** — maintaining a precise creative voice across formats (IMMBT, event coverage, brand collaborations) is difficult under deadline pressure
- **Friction-heavy** — briefs arrive in many formats (PDFs, forwarded emails, screenshots, WhatsApp voice memos) requiring manual extraction and reformatting before writing can even begin
- **Iterative** — first drafts typically need 2–3 refinement rounds, each requiring full context recall and re-reading of the original brief
- **Non-cumulative** — feedback given on past scripts doesn't carry forward; the same corrections get repeated across sessions, and the system starts from zero every time

### What Version 2.0 Specifically Addresses

Version 1.0 solved the generation and refinement loop. Version 2.0 adds four critical layers:

1. **Learning from approvals** — Approved scripts are stored in a persistent library (rolling window of 200) and injected as few-shot examples (up to 5 per generation, 2 per refinement) into every future prompt, so the bot's voice converges on what Honey actually signs off on — not just what the system prompt describes. Library is backed by GitHub for durability across deploys, with in-memory caching and local file backup.
2. **Learning from corrections** — Refinement feedback is logged persistently (rolling window of 30 entries) and injected into refinement prompts, so the bot learns from recurring correction patterns and stops making the same mistakes.
3. **Web enrichment** — When a Brave Search API key is configured, the bot automatically extracts the brand and product name from the brief, searches for real product USPs, ingredients, and claims online, and enriches the brief before generation — producing scripts with specific, accurate product details instead of vague placeholders.
4. **Automated voice check** — Every generated script passes through a second-pass quality gate (Claude Haiku) that catches generic openers, banned words, caption drift, feature dumps, and pushy CTAs — enforcing voice compliance before the user ever sees the output.

**The goal:** eliminate manual scripting time, enable brief-to-filming in minutes, and build a system that gets measurably better at matching Honey's voice with every interaction.

---

## 3. Functional Requirements

### 3.1 Brief Ingestion

| ID | Requirement | Details |
|---|---|---|
| FR-01 | **Accept plain text briefs** | Any WhatsApp text message is treated as a new brief when no active flow exists and no prior script is loaded. Messages under 500 characters when a prior script exists are treated as refinement feedback instead (see FR-37). Briefs exceeding 8,000 characters are rejected with a prompt to trim. Messages with explicit brief signals (`brand brief`, `new brief`, `collab brief`, `new campaign`, `new collab`) are always treated as new briefs regardless of length or prior script state. |
| FR-02 | **Accept and extract text from PDF attachments** | Uses PyPDF2 to read all pages and concatenate extracted text. Handles extraction failures gracefully with a fallback message asking the user to paste as plain text. |
| FR-03 | **Accept and extract text from Word (.docx) attachments** | Uses mammoth library for raw text extraction from .docx files. Content type detection covers `word`, `docx`, and `officedocument` MIME type variants. |
| FR-04 | **Accept image/screenshot attachments** | Image is base64-encoded and passed to Claude claude-opus-4-6 via multimodal vision input during the generation step. The image is stored in the brief field as a `[IMAGE:base64:content_type]` token and processed inline — text extraction and script generation happen in a single API call. If the image token cannot be parsed at generation time, the user is asked to resend in another format. |
| FR-05 | **Accept voice note briefs** | Audio is downloaded from Twilio media URL, saved to a temporary file with the appropriate extension (`.ogg`, `.m4a`, `.mp3`, `.webm`), transcribed via Groq Whisper Large v3, and then treated as a text brief. Transcription is echoed back to the user in italics for confirmation before proceeding to format selection. Supported audio MIME type keywords: `audio`, `ogg`, `mpeg`, `mp4`, `webm`. Temporary audio files are cleaned up after transcription. |
| FR-06 | **Detect forwarded brand emails** | Heuristic detection based on signal keyword count: if ≥2 of the following appear in the message text — `from:`, `subject:`, `dear honey`, `hi honey`, `hello honey`, `we would like`, `we are reaching out`, `collaboration`, `partnership`, `deliverables`, `compensation`, `deadline`, `fwd:`, `forwarded message`, `------` — the message is classified as a forwarded email. Only triggered for text messages (not media attachments). |
| FR-07 | **Extract structured brief from detected emails** | When an email is detected (FR-06), Claude claude-opus-4-6 extracts a structured brief in the format: Brand, Product, Key Claims, Deliverables, Deadline, Extra Notes. The extracted brief is sent back to the user for transparency, then used as the brief text for the remainder of the flow. Falls back to the raw email text if extraction fails. |
| FR-08 | **Reject empty or insufficient briefs** | If extracted text is empty or under 10 characters, the user is prompted to resend in a different format or paste as plain text. |
| FR-09 | **Reject oversized briefs** | Text briefs exceeding 8,000 characters are rejected with a message asking the user to trim to key details: brand, product, key claims, and deliverables. |
| FR-10 | **Brief confirmation** | After successful brief extraction, the bot acknowledges receipt ("Got your brief!") and immediately transitions to format selection. For voice briefs, the transcription is echoed back for the user to review. For emails, the structured extraction is shown. |

### 3.2 Web Enrichment

| ID | Requirement | Details |
|---|---|---|
| FR-11 | **Automatic brand and product extraction** | When a Brave Search API key is configured (`BRAVE_SEARCH_API_KEY` environment variable), the bot uses Claude claude-haiku-4-5-20251001 to extract the brand name and product name from the first 600 characters of the brief. Returns empty if extraction yields "unknown" for the brand. |
| FR-12 | **Product USP web search** | Using the extracted brand and product name, the bot queries Brave Search API with the query pattern `{brand} {product} key ingredients benefits claims`, retrieves up