import os
import re
import requests
from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
import anthropic
import mammoth
import PyPDF2
import io
import base64

app = Flask(__name__)

anthropic_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
twilio_client = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])
TWILIO_NUMBER = os.environ["TWILIO_WHATSAPP_NUMBER"]

user_state = {}

SYSTEM_PROMPT = """You are a script and caption writer for Honey Sheth — an Indian lifestyle, beauty, and travel content creator. You write EXCLUSIVELY in her voice, trained on 37 of her real scripts.

HONEY'S VOICE:
- Warm, confident, visually descriptive. Luxury feels lived-in, never distant.
- Real over perfect. "I noticed" and "it feels like" not "it transformed my skin."
- Each piece reads like a small story: sensory, honest, reflective.
- She code-switches into Hindi naturally — never forced, only when emotion calls for it.
- Calm confidence. Never hype. The product earns its place in the story.
- She picks 1-2 benefits and builds around them — never a feature dump.
- Captions are quieter and more essay-like. Fewer emojis. More thought.

SCRIPT CUES:
Visual: [what the camera sees]
PTC: [piece to camera — personal, emotional, opinion]
VO: [voiceover — product detail, sensory description]
Super: [text overlay]

PTC = feelings, reactions, verdicts. VO = product info, texture, ingredients.
Never a talking head throughout. Always alternate.

EMOTIONAL ARC:
1. HOOK — relatable, visual, personal
2. PRODUCT MOMENT — seamless, arrives inside the story
3. DEMO / EXPERIENCE — sensory, texture, how it feels. Non-negotiable.
4. TRANSFORMATION / REFLECTION — what quietly shifted
5. CTA — soft, natural, conversational

CAPTION RULES:
Line 1: hook — truth, confession, or moment. Not a product claim.
2-3 short paragraphs: sensory storytelling + personal perspective.
Final line: a thought that lingers.
2-5 hashtags max. Include #Ad and brand tag.
Captions extend the story — never a transcript of the video.

FORMATS:
IMMBT: Open with why it kept catching your attention. Insert <IMMBT theme intro> after hook. End with genuine verdict.
EVENT: Vlog energy, VO carries the story, name specific things, end on a feeling not a feature list.
COLLAB ROUTINE: Step by step, each product gets its own sensory moment.
COLLAB NARRATIVE: Emotional hook first, product arrives as the solution.
COLLAB MULTI-PRODUCT: One editorial hook holds everything together.
COLLAB GIFTING: Relationship narrative first, product is the act of care.
COLLAB PLATFORM: Platform is the brand, products are editorial picks.

RULES:
ALWAYS: Connect product to a real moment. Include texture moment. Give emotional way in before selling.
NEVER: Overclaim. Dump all benefits. Hard sell CTA. Caption that transcripts the video.

REFERENCE VOICES:
"I've actually avoided retinol for years because my skin can be a little sensitive… But this kept showing up on my Instagram so eventually curiosity won"
"it just gets the balance right — lightweight but still hydrating, gentle but still effective"
"There's a difference between a moisturiser that works… and one that just doesn't mess your skin up."
"I've grown up at other people's weddings. Different lehengas. Different phases of life. Same questions."
"Shaadi-proof doesn't mean unaffected. It just means unbothered."
"My skin gets all the love… but for the longest time I completely ignored my scalp."
"Hair fall used to feel like something I'd deal with later. Until later started coming sooner."
"I hate traveling with a million makeup products. This little stick is all I carried."
"I went for fashion week… and stayed for the slushies"
"Could you guess where I am? I am at the Changi airport and we are going to be spending a whole day here!"

OUTPUT FORMAT — STRICT:
Return exactly:

[REEL SCRIPT]
...full script...

[CAPTION]
...caption with hashtags...

No preamble. No notes. Just the script and caption."""


def download_media(media_url):
    r = requests.get(
        media_url,
        auth=(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"]),
        timeout=30
    )
    r.raise_for_status()
    return r.content


def extract_pdf(data):
    reader = PyPDF2.PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages).strip()


def extract_docx(data):
    result = mammoth.extract_raw_text(io.BytesIO(data))
    return result.value.strip()


def extract_brief(msg_body, media_url, content_type):
    if media_url:
        data = download_media(media_url)
        ct = content_type.lower()
        if "pdf" in ct:
            return extract_pdf(data)
        elif "word" in ct or "docx" in ct or "officedocument" in ct:
            return extract_docx(data)
        elif "image" in ct:
            img_b64 = base64.b64encode(data).decode()
            return f"[IMAGE:{img_b64}:{ct}]"
        elif "audio" in ct or "ogg" in ct:
            return "[AUDIO]"
    return msg_body.strip()


def detect_format(brief_text):
    b = brief_text.lower()
    if any(w in b for w in ["event", "launch", "party", "activation", "experience"]):
        return "Event coverage — vlog-style, experiential"
    if any(w in b for w in ["gift", "rakhi", "diwali", "occasion"]):
        return "Brand collaboration — gifting narrative"
    if any(w in b for w in ["nykaa", "tira", "myntra", "platform", "haul", "new arrivals"]):
        return "Brand collaboration — platform, products as editorial picks"
    if any(w in b for w in ["routine", "step", "tutorial", "how to"]):
        return "Brand collaboration — routine or tutorial"
    return "Instagram Made Me Buy This (IMMBT series)"


def generate_script(brief_text, extra_notes=""):
    if brief_text.startswith("[IMAGE:"):
        match = re.match(r'\[IMAGE:(.+):(.+)\]', brief_text)
        if match:
            img_b64, ct = match.group(1), match.group(2)
            messages = [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": ct, "data": img_b64}},
                    {"type": "text", "text": "This is a brand brief image. Extract all info and write a full Instagram reel script and caption in Honey Sheth's voice."}
                ]
            }]
        else:
            return "Sorry, could not read that image. Please send as text, PDF, or Word doc."
    elif brief_text == "[AUDIO]":
        return "I cannot process voice notes right now. Please type the brief or send it as a PDF or Word doc!"
    else:
        fmt = detect_format(brief_text)
        prompt = f"""Write a full Instagram reel script and caption.

CONTENT FORMAT: {fmt}
{extra_notes}

BRAND BRIEF:
{brief_text}

Follow the emotional arc. Include the sensory texture moment. Keep CTA soft. Caption should be a different angle from the script."""
        messages = [{"role": "user", "content": prompt}]

    response = anthropic_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2200,
        system=SYSTEM_PROMPT,
        messages=messages
    )
    return response.content[0].text


def format_for_whatsapp(raw):
    sm = re.search(r'\[REEL SCRIPT\]([\s\S]*?)(?=\[CAPTION\]|$)', raw, re.IGNORECASE)
    cm = re.search(r'\[CAPTION\]([\s\S]*?)$', raw, re.IGNORECASE)
    script = sm.group(1).strip() if sm else raw.strip()
    caption = cm.group(1).strip() if cm else ""
    out = "🎬 *REEL SCRIPT*\n─────────────────\n" + script
    if caption:
        out += "\n\n📝 *CAPTION*\n─────────────────\n" + caption
    out += "\n\n─────────────────\n_Reply *refine* to adjust, or send a new brief to start fresh._"
    return out


@app.route("/webhook", methods=["POST"])
def webhook():
    from_number = request.form.get("From", "")
    msg_body = request.form.get("Body", "").strip()
    num_media = int(request.form.get("NumMedia", 0))
    media_url = request.form.get("MediaUrl0", "") if num_media > 0 else ""
    content_type = request.form.get("MediaContentType0", "") if num_media > 0 else ""

    resp = MessagingResponse()
    lower = msg_body.lower()

    if lower in ["hi", "hello", "hey", "start"]:
        resp.message(
            "Hey! I am Honey's script generator.\n\n"
            "Send me a brand brief and I'll write the reel script and caption in your voice.\n\n"
            "What I can read:\n"
            "PDF files\n"
            "Word docs\n"
            "Images and screenshots\n"
            "Plain text\n\n"
            "Just send it over!"
        )
        return Response(str(resp), mimetype="text/xml")

    if lower == "help":
        resp.message(
            "Commands:\n"
            "Send any brief to get script and caption\n"
            "Reply refine to adjust the last script\n"
            "Start message with immbt to force IMMBT format\n"
            "Start with event to force event format\n"
            "Start with collab to force collab format\n"
            "Send hi to restart"
        )
        return Response(str(resp), mimetype="text/xml")

    extra_notes = ""
    if lower.startswith("immbt"):
        extra_notes = "FORMAT: Instagram Made Me Buy This (IMMBT)"
        msg_body = msg_body[5:].strip()
    elif lower.startswith("event"):
        extra_notes = "FORMAT: Event coverage vlog-style"
        msg_body = msg_body[5:].strip()
    elif lower.startswith("collab"):
        extra_notes = "FORMAT: Brand collaboration"
        msg_body = msg_body[6:].strip()

    state = user_state.get(from_number, {})

    if lower == "refine":
        last_brief = state.get("last_brief", "")
        if not last_brief:
            resp.message("No previous script found. Send a brief to get started!")
            return Response(str(resp), mimetype="text/xml")
        resp.message("What would you like to change? For example: make the hook more personal, or try a more playful tone.")
        user_state[from_number] = {**state, "awaiting_refine": True}
        return Response(str(resp), mimetype="text/xml")

    if state.get("awaiting_refine") and msg_body:
        extra_notes = f"REFINEMENT: {msg_body}"
        msg_body = state.get("last_brief", "")
        user_state[from_number] = {**state, "awaiting_refine": False}

    if not msg_body and not media_url:
        resp.message("Send me a brand brief as text, PDF, Word doc, or image!")
        return Response(str(resp), mimetype="text/xml")

    twilio_client.messages.create(
        from_=TWILIO_NUMBER,
        to=from_number,
        body="Writing your script... give me 20 seconds."
    )

    try:
        brief_text = extract_brief(msg_body, media_url, content_type)
        if not brief_text or len(brief_text) < 5:
            resp.message("Could not extract enough text. Please paste the brief as text or send a clearer PDF or Word doc.")
            return Response(str(resp), mimetype="text/xml")

        raw = generate_script(brief_text, extra_notes)
        formatted = format_for_whatsapp(raw)
        user_state[from_number] = {"last_brief": brief_text, "last_script": raw}

        if len(formatted) <= 1500:
            resp.message(formatted)
        else:
            parts = formatted.split("📝 *CAPTION*")
            twilio_client.messages.create(from_=TWILIO_NUMBER, to=from_number, body=parts[0].strip())
            if len(parts) > 1:
                resp.message("📝 *CAPTION*\n" + parts[1].strip())

    except Exception as e:
        print(f"Error: {e}")
        resp.message("Something went wrong. Try again or paste the brief as plain text.")

    return Response(str(resp), mimetype="text/xml")


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}, 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
