# Honey Script Bot

A personal WhatsApp AI assistant that generates Instagram Reel scripts and captions in Honey Sheth's creative voice — from any brand brief, in any format, in under 60 seconds.

---

## What it does

Send a brand brief to a WhatsApp number. Get back a production-ready reel script and caption, written in your voice, structured to your content formats.

**Accepts briefs as:**
- Plain text
- PDF files
- Word documents (.docx)
- Images / screenshots
- Voice notes
- Forwarded brand emails

**Output:** A full reel script (with Visual, PTC, VO, Super cues) + a matching caption (different angle from the video).

---

## How it works

```
Brief (any format)
     │
     ▼
Format: IMMBT / Event / Collab
     │
     ▼
Sub-format selection (3–5 options)
     │
     ▼
4 creative concept hooks generated
     │
     ▼
Pick a concept → full script + caption
     │
     ▼
Refine via text or voice feedback (unlimited rounds)
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11 |
| Web framework | Flask + Gunicorn |
| WhatsApp | Twilio Messaging API |
| AI — scripts | Anthropic Claude Sonnet 4 |
| AI — voice transcription | Groq Whisper (whisper-large-v3) |
| PDF parsing | PyPDF2 |
| DOCX parsing | mammoth |
| State management | Python shelve |
| Deployment | Railway / Render |

---

## Content Formats

**IMMBT** _(Instagram Made Me Buy This)_
- Single product discovery
- Viral hype check / sceptic won over
- Personal resistance resolved

**Event Coverage**
- Brand booth or launch
- Destination / full travel day
- Community or group event

**Brand Collaboration**
- Routine or tutorial
- Personal narrative
- Multi-product haul
- Gifting or occasion
- Platform or retail collab

---

## Setup

Full deployment instructions (Railway + Twilio + environment variables) are in [SETUP_GUIDE.md](./SETUP_GUIDE.md).

**You'll need:**
- `ANTHROPIC_API_KEY`
- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_WHATSAPP_NUMBER`
- `GROQ_API_KEY`

Estimated setup time: ~45 minutes. Estimated monthly cost: $6–28 depending on usage.

---

## Commands

| Message | Action |
|---------|--------|
| `hi` / `hello` / `hey` | Reset and start fresh |
| `help` | Show usage guide |
| `cancel` | Abandon current flow |
| Any feedback after a script | Triggers refinement mode |

---

## Docs

- [PRD — Product Requirements Document](./PRD.md)
- [TDD — Technical Design Document](./TDD.md)
- [Setup Guide](./SETUP_GUIDE.md)

---

## Cost

| Service | Cost |
|---------|------|
| Railway | Free (500 hrs/month) → $5/month |
| Twilio sandbox | Free |
| Twilio production number | ~$1/month + $0.005/msg |
| Anthropic Claude | ~$0.01–0.03 per script |
| Groq Whisper | Free tier |
| **Estimated total** | **$6–28/month** |
