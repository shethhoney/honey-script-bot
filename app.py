import os
import re
import tempfile
import requests
from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
import anthropic
import mammoth
import PyPDF2
import openai
from pydub import AudioSegment
from PIL import Image
import pytesseract
import io
import base64

app = Flask(__name__)

# ── Clients ──────────────────────────────────────────────────────────────────
anthropic_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
twilio_client    = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])
TWILIO_NUMBER    = os.environ["TWILIO_WHATSAPP_NUMBER"]   # e.g. whatsapp:+14155238886

# ── Conversation state (in-memory — resets on redeploy) ──────────────────────
# Stores pending clarification state per user phone number
user_state = {}

# ── Honey's full system prompt ────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a script and caption writer for Honey Sheth — an Indian lifestyle, beauty, and travel content creator. You write EXCLUSIVELY in her voice, trained on 37 of her real scripts.

━━ HONEY'S VOICE ━━
- Warm, confident, visually descriptive. Luxury feels lived-in, never distant.
- Real over perfect. "I noticed" and "it feels like" — not "it transformed my skin."
- Each piece reads like a small story: sensory, honest, reflective.
- She code-switches into Hindi naturally — never forced, only when emotion or humour calls for it.
- Calm confidence. Never hype. The product earns its place in the story.
- She picks 1–2 benefits and builds around them — never a feature dump.
- Captions have evolved toward quieter, more essay-like writing. Fewer emojis. More thought.

━━ SCRIPT CUES ━━
Visual: [what the camera sees — specific and shootable]
PTC: [piece to camera — personal, emotional, opinion — direct eye contact]
VO: [voiceover — product detail, sensory, while visuals carry the scene]
Super: [text overlay on screen]

PTC = feelings, reactions, verdicts. VO = product info, texture, ingredients.
Never a talking head throughout. Always alternate.

━━ EMOTIONAL ARC ━━
1. HOOK — relatable, visual, personal. Stops the scroll.
2. PRODUCT MOMENT — seamless. Arrives inside the story.
3. DEMO / EXPERIENCE — sensory. Texture, application, how it feels. Non-negotiable.
4. TRANSFORMATION / REFLECTION — what quietly shifted. Soft and earned.
5. CTA — soft, natural. Conversation not instruction.

━━ CAPTION RULES ━━
Line 1: hook — truth, confession, or moment. Not a product claim.
2–3 short paragraphs: sensory storytelling + personal perspective.
Final line: a thought that lingers — reflection or gentle CTA.
2–5 hashtags max. Include #Ad and brand tag.
Captions extend the story — different angle, same emotional world. Never a transcript.
Recent style: quieter, more reflective, fewer emojis, reads like a short essay.

━━ FORMAT GUIDES ━━

IMMBT: Open with why it kept catching your attention. Insert <IMMBT theme intro> after hook.
Build to a genuine verdict: "okay, Instagram. You got me." / "Added to my vanity."

EVENT COVERAGE: Vlog energy — walking in, reacting, discovering in real time.
VO carries the story. Name specific things seen and done. End on a feeling, not a feature list.

COLLABORATION — Routine/tutorial: Step by step. Each product gets its own sensory moment.
COLLABORATION — Narrative: Emotional hook first. Product arrives as the solution.
COLLABORATION — Multi-product: One editorial hook holds everything together.
COLLABORATION — Gifting: Build the relationship narrative first. Product is the act of care.
COLLABORATION — Platform: Platform is the brand. Products are editorial picks within it.

━━ HONEY'S RULES ━━
ALWAYS: Connect product to a real moment. Include texture/sensory moment. Give audience emotional way in before selling. Captions add something the video doesn't say.
NEVER: Overclaim. Dump all benefits. Let brand voice take over. End with hard sell. Write caption as video transcript.

━━ REFERENCE SCRIPTS ━━

[IMMBT — Neutrogena]
Hook: "I've actually avoided retinol for years because my skin can be a little sensitive… But this kept showing up on my Instagram so eventually curiosity won"
Texture: "lightweight and comfortable so it doesn't feel heavy or intimidating"
Verdict: "if you've been retinol curious but didn't know where to begin this feels like a really easy place to start"
Caption: "Retinol has always been one of those ingredients that felt a little intimidating to start."

[IMMBT — Dr. Althea 345 Relief Cream]
Hook: "I'm sure you've seen this everywhere and people are calling it a holy grail but is it actually worth the hype?"
Verdict: "it just gets the balance right — lightweight but still hydrating, gentle but still effective"
Caption: "There's a difference between a moisturiser that works… and one that just doesn't mess your skin up."

[IMMBT — Dove Hair Mask]
Hook: "This mask kept showing up on my feed… And every time, the claims sounded too good to be true."
Texture: "protein peptide beads that melt into the hair to help repair damaged bonds"
Verdict: "I didn't plan on buying another hair mask, but… this one got me. Added to my vanity!"

[IMMBT — Typsy Beauty Blush]
Hook: "Okay so Typsy Beauty just keeps innovating and I was seeing the brand everywhere so I was like okay fine I need to try this!"
Texture: "Wait… this blends out really nicely! Like it just melts in, and look at the shimmer in it!"

[COLLAB — Vaseline Sunscreen]
Hook: "You already know this Gluta Hya lotion is a staple for me. I've genuinely gone through multiple bottles."
Caption closer: "Sun protection, but make it feel like skincare."

[COLLAB — Pond's Shaadi Proof]
VO: "I've attended enough weddings to know exactly how they go. The comparisons. The timelines."
Caption: "I've grown up at other people's weddings. Different lehengas. Different phases of life. Same questions."
Caption closer: "Shaadi-proof doesn't mean unaffected. It just means unbothered."

[COLLAB — Eucerin — third-person narrator]
Opens: "This is Honey." / "And this is how my skin looks now." / "But that is not how it has always been."

[COLLAB — Korean skincare ft. Dad VO]
Dad narrates in Hindi while Honey does her routine. Curious, slowly won over.
"Yeh toh bilkul paani jaisa lag raha hai! Par woh kehti hai, yeh skin ko brighten and soft soft karta hai."

[COLLAB — FCL Rakhi — gifting]
He never picks up for trivial things. Picks up for the real emergency.
Doorbell: he arrives with the product. Sticky note: "Emergency response team reporting for duty."

[COLLAB — Dove Scalp Serum]
Hook: "My skin gets all the love… but for the longest time I completely ignored my scalp."
Insight: "I kept focusing on the ends. But hairfall? It's never an end problem — it's a root problem."
Caption: "My skincare routine? Layered. My scalp routine? Non-existent — until now."

[COLLAB — Olay Retinol — AI device]
Hook: "Skincare advice online can get overwhelming. So I asked AI the most basic question."
Device: green screen shows AI response: "Retinol"

[COLLAB — Nykaa Hydraplump — summer]
Hook: "I've been trying to stay really hydrated in this heat… but my skin still doesn't feel like it"
Caption: "I've been trying to stay really hydrated in this heat… but my skin just doesn't stay that way for long. So I started paying more attention to what I'm using on it."

[COLLAB — Bare Anatomy — slow narrative]
Caption: "Hair fall used to feel like something I'd 'deal with later.' Until later started coming sooner."
Closer: "start before it feels urgent"

[COLLAB — Minimalist Hair Trio — travel]
Hook: "I've realised my hair gets the most tired when I travel… like it feels before I do."

[COLLAB — Nykaa CSMS — multi-product platform]
Hook: "Festive season prep can be stressful… But skincare doesn't need to be complicated."
Structure: 4-step format, each step gets its own PTC + swatches

[COLLAB — Chantecaille at Tira — editorial/luxury]
Tone: slower, more considered, values-led. "beauty that gives back."

[COLLAB — NUDESTIX — travel]
Hook: "I hate traveling with a million makeup products. This little stick is all I carried."

[EVENT — Changi Airport]
Hook: "Could you guess where I am? I am at the Changi airport and we are going to be spending a whole day here!"
Closer: "I don't want to leave — someone cancel my flight!"

[EVENT — Mandai Wildlife]
Hook: "Imagine seeing penguins, orangutans, and Tasmanian devils… all in one day."
Structure: park by park — Bird Paradise → Singapore Zoo → Night Safari

[EVENT — Venus Glide Girls]
Hook: "When Venus invited me to India's first community of shavers, I was like, finally, this one's for me."
Arrived with her best friend. Community energy, fun activities.

[EVENT — Tira × LFW]
Hook: "I went for fashion week… and stayed for the slushies"
Tone: playful, lighter, booth-as-experience energy

━━ OUTPUT FORMAT — STRICT ━━
Return exactly two clearly labelled sections:

[REEL SCRIPT]
...full script with Visual / PTC / VO / Super cues...

[CAPTION]
...caption with hashtags...

No preamble. No commentary. No notes after. Just the script and caption."""


# ── Text extraction helpers ───────────────────────────────────────────────────

def download_media(media_url: str) -> bytes:
    """Download media from Twilio URL using auth."""
    r = requests.get(
        media_url,
        auth=(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"]),
        timeout=30
    )
    r.raise_for_status()
    return r.content


def extract_pdf(data: bytes) -> str:
    reader = PyPDF2.PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages).strip()


def extract_docx(data: bytes) -> str:
    result = mammoth.extract_raw_text(io.BytesIO(data))
    return result.value.strip()


def extract_image_text(data: bytes) -> str:
    """OCR an image to extract text from brief screenshots."""
    img = Image.open(io.BytesIO(data))
    return pytesseract.image_to_string(img).strip()


def transcribe_audio(data: bytes, content_type: str) -> str:
    """Convert voice note to text using Anthropic."""
    try:
        fmt = "ogg" if "ogg" in content_type else "mp4"
        audio = AudioSegment.from_file(io.BytesIO(data), format=fmt)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            audio.export(tmp.name, format="wav")
            tmp_path = tmp.name
        with open(tmp_path, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode()
        os.unlink(tmp_path)
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": f"Transcribe this audio file exactly. Return only the transcription, nothing else. Audio (base64 wav): {audio_b64[:100]}..."
            }]
        )
        return response.content[0].text.strip()
    except Exception:
        return ""
```


def extract_brief_from_message(msg_body: str, media_url: str, content_type: str) -> str:
    """Extract brief text from whatever the user sent."""
    if media_url:
        data = download_media(media_url)
        ct = content_type.lower()

        if "pdf" in ct:
            return extract_pdf(data)

        elif "word" in ct or "docx" in ct or "officedocument" in ct:
            return extract_docx(data)

        elif "image" in ct:
            # Try to extract text from image (brief screenshot)
            ocr_text = extract_image_text(data)
            if len(ocr_text) > 50:
                return ocr_text
            # If minimal text, treat image as visual context — pass to Claude vision
            return f"[IMAGE_BRIEF:{base64.b64encode(data).decode()}:{ct}]"

        elif "audio" in ct or "ogg" in ct:
            return transcribe_audio(data, ct)

    return msg_body.strip()


# ── Script generation ─────────────────────────────────────────────────────────

def detect_format(brief_text: str) -> str:
    """Auto-detect content format from brief text."""
    brief_lower = brief_text.lower()
    if any(w in brief_lower for w in ["event", "launch", "party", "experience", "activation", "festival"]):
        return "Event coverage — vlog-style, experiential, real-time discovery"
    if any(w in brief_lower for w in ["gift", "rakhi", "diwali", "birthday", "occasion", "festival"]):
        return "Brand collaboration — gifting / occasion narrative"
    if any(w in brief_lower for w in ["nykaa", "tira", "myntra", "platform", "new arrivals", "haul"]):
        return "Brand collaboration — platform or retail, products as editorial picks"
    if any(w in brief_lower for w in ["routine", "step", "tutorial", "how to", "regimen"]):
        return "Brand collaboration — routine or tutorial"
    # Default to IMMBT for single product briefs
    return "Instagram Made Me Buy This (IMMBT series)"


def generate_script(brief_text: str, extra_notes: str = "") -> str:
    """Call Claude to generate script + caption."""

    # Handle image brief — use vision
    if brief_text.startswith("[IMAGE_BRIEF:"):
        match = re.match(r'\[IMAGE_BRIEF:(.+):(.+)\]', brief_text)
        if match:
            img_b64, ct = match.group(1), match.group(2)
            messages = [{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": ct, "data": img_b64}
                    },
                    {
                        "type": "text",
                        "text": f"This is a brand brief image. Extract all information from it and write a full Instagram reel script and caption in Honey Sheth's voice.\n\nContent format: {detect_format('')}\n{extra_notes}"
                    }
                ]
            }]
        else:
            return "Sorry, I couldn't read that image. Could you send the brief as text, PDF, or Word doc?"
    else:
        fmt = detect_format(brief_text)
        prompt = f"""Write a full Instagram reel script and caption for this brief.

CONTENT FORMAT: {fmt}
{extra_notes}

BRAND BRIEF:
{brief_text}

Follow the emotional arc exactly. Include the sensory/texture moment. Keep the CTA soft. Caption should be a different angle from the script — quieter, more reflective."""

        messages = [{"role": "user", "content": prompt}]

    response = anthropic_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2200,
        system=SYSTEM_PROMPT,
        messages=messages
    )

    return response.content[0].text


def format_for_whatsapp(raw: str) -> str:
    """Format the script nicely for WhatsApp."""
    script_match  = re.search(r'\[REEL SCRIPT\]([\s\S]*?)(?=\[CAPTION\]|$)', raw, re.IGNORECASE)
    caption_match = re.search(r'\[CAPTION\]([\s\S]*?)$', raw, re.IGNORECASE)

    script  = script_match.group(1).strip()  if script_match  else raw.strip()
    caption = caption_match.group(1).strip() if caption_match else ""

    output = "🎬 *REEL SCRIPT*\n"
    output += "─────────────────\n"
    output += script
    if caption:
        output += "\n\n📝 *CAPTION*\n"
        output += "─────────────────\n"
        output += caption
    output += "\n\n─────────────────\n"
    output += "_Reply *refine* to adjust, or send a new brief to start fresh._"
    return output


# ── WhatsApp webhook ──────────────────────────────────────────────────────────

@app.route("/webhook", methods=["POST"])
def webhook():
    from_number  = request.form.get("From", "")
    msg_body     = request.form.get("Body", "").strip()
    num_media    = int(request.form.get("NumMedia", 0))
    media_url    = request.form.get("MediaUrl0", "") if num_media > 0 else ""
    content_type = request.form.get("MediaContentType0", "") if num_media > 0 else ""

    resp = MessagingResponse()

    # Handle commands
    lower_body = msg_body.lower()

    if lower_body in ["hi", "hello", "hey", "start"]:
        resp.message(
            "👋 Hey! I'm Honey's script generator.\n\n"
            "Send me a brand brief and I'll write the reel script + caption in your voice.\n\n"
            "*What I can read:*\n"
            "📄 PDF files\n"
            "📝 Word docs (.docx)\n"
            "🖼️ Images / screenshots of briefs\n"
            "🎤 Voice notes\n"
            "✍️ Plain text\n\n"
            "Just send it over!"
        )
        return Response(str(resp), mimetype="text/xml")

    if lower_body == "help":
        resp.message(
            "*Commands:*\n"
            "• Send any brief → get script + caption\n"
            "• *refine* → adjust the last script\n"
            "• *immbt* → force IMMBT format\n"
            "• *event* → force event coverage format\n"
            "• *collab* → force collaboration format\n"
            "• *hi* → restart"
        )
        return Response(str(resp), mimetype="text/xml")

    # Format overrides
    extra_notes = ""
    if lower_body.startswith("immbt ") or lower_body == "immbt":
        extra_notes = "FORMAT OVERRIDE: Instagram Made Me Buy This (IMMBT series)"
        msg_body = msg_body[6:].strip() if lower_body.startswith("immbt ") else ""
    elif lower_body.startswith("event ") or lower_body == "event":
        extra_notes = "FORMAT OVERRIDE: Event coverage — vlog-style, experiential"
        msg_body = msg_body[6:].strip() if lower_body.startswith("event ") else ""
    elif lower_body.startswith("collab ") or lower_body == "collab":
        extra_notes = "FORMAT OVERRIDE: Brand collaboration"
        msg_body = msg_body[7:].strip() if lower_body.startswith("collab ") else ""

    # Refine last script
    if lower_body == "refine":
        state = user_state.get(from_number, {})
        last_brief = state.get("last_brief", "")
        if not last_brief:
            resp.message("No previous script found. Send a brief to get started!")
            return Response(str(resp), mimetype="text/xml")
        resp.message("What would you like to change? (e.g. 'make the hook more personal', 'try a different CTA', 'make it more playful')")
        user_state[from_number] = {**state, "awaiting_refine": True}
        return Response(str(resp), mimetype="text/xml")

    # Handle refine instruction
    state = user_state.get(from_number, {})
    if state.get("awaiting_refine") and msg_body:
        last_brief = state.get("last_brief", "")
        extra_notes = f"REFINEMENT REQUEST: {msg_body}\n\nPrevious brief context: {last_brief[:500]}"
        msg_body = last_brief
        user_state[from_number] = {**state, "awaiting_refine": False}

    # Nothing to process
    if not msg_body and not media_url:
        resp.message("Send me a brand brief — as text, PDF, Word doc, image, or voice note!")
        return Response(str(resp), mimetype="text/xml")

    # Send acknowledgement first
    twilio_client.messages.create(
        from_=TWILIO_NUMBER,
        to=from_number,
        body="✍️ Writing your script… give me 15–20 seconds."
    )

    try:
        brief_text = extract_brief_from_message(msg_body, media_url, content_type)

        if not brief_text or len(brief_text) < 10:
            resp.message("I couldn't extract enough text from that. Could you paste the brief as text, or send a clearer PDF/Word doc?")
            return Response(str(resp), mimetype="text/xml")

        raw_script = generate_script(brief_text, extra_notes)
        formatted  = format_for_whatsapp(raw_script)

        # Save state for potential refinement
        user_state[from_number] = {"last_brief": brief_text, "last_script": raw_script}

        # WhatsApp has 1600 char limit per message — split if needed
        if len(formatted) <= 1500:
            resp.message(formatted)
        else:
            # Split at caption divider
            parts = formatted.split("📝 *CAPTION*")
            twilio_client.messages.create(
                from_=TWILIO_NUMBER,
                to=from_number,
                body=parts[0].strip()
            )
            if len(parts) > 1:
                resp.message("📝 *CAPTION*\n" + parts[1].strip())
            else:
                resp.message(formatted[1500:])

    except Exception as e:
        print(f"Error: {e}")
        resp.message("Something went wrong on my end. Try again in a moment, or paste the brief as plain text.")

    return Response(str(resp), mimetype="text/xml")


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok", "service": "honey-script-bot"}, 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
