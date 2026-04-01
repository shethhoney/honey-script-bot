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
import threading
import time
import shelve
import tempfile

app = Flask(__name__)

anthropic_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
twilio_client = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])
TWILIO_NUMBER = os.environ["TWILIO_WHATSAPP_NUMBER"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

state_lock = threading.Lock()

def get_state(number):
    with state_lock:
        with shelve.open("/tmp/honey_state") as db:
            return dict(db.get(number, {"step": "idle"}))

def set_state(number, data):
    with state_lock:
        with shelve.open("/tmp/honey_state") as db:
            db[number] = data

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
Visual: [what the camera sees — specific and shootable]
PTC: [piece to camera — personal, emotional, opinion — direct eye contact]
VO: [voiceover — product detail, sensory description while visuals carry the scene]
Super: [text overlay on screen]

PTC = feelings, reactions, verdicts. VO = product info, texture, ingredients.
Never a talking head throughout. Always alternate.

EMOTIONAL ARC:
1. HOOK — relatable, visual, personal. Stops the scroll.
2. PRODUCT MOMENT — seamless. Arrives inside the story.
3. DEMO / EXPERIENCE — sensory. Texture, application, how it feels. Non-negotiable.
4. TRANSFORMATION / REFLECTION — what quietly shifted. Soft and earned.
5. CTA — soft, natural. Conversation not instruction.

CAPTION RULES:
Line 1: hook — truth, confession, or moment. Not a product claim.
2-3 short paragraphs: sensory storytelling + personal perspective.
Final line: a thought that lingers.
2-5 hashtags max. Include #Ad and brand tag.
Captions EXTEND the story — different angle, never a transcript.
Style: quieter, reflective, fewer emojis, reads like a short essay.

FORMAT GUIDES:
IMMBT SINGLE: Open with why it kept catching your attention. Insert <IMMBT theme intro> after hook. Build to genuine verdict.
IMMBT HYPE CHECK: Lead with the hype. Be the sceptic who gets won over.
IMMBT SCEPTIC: Personal resistance first. Product solves the exact thing you worried about.
EVENT BOOTH: Discover the brand in the space. React to products and activations. End on energy.
EVENT DESTINATION: VO carries story. Name specific moments. End on feeling not feature list.
EVENT COMMUNITY: Arrived with a friend. Group energy and shared moments.
COLLAB ROUTINE: Step by step. Each product gets its own sensory moment.
COLLAB NARRATIVE: Emotional hook first. Product arrives as the solution.
COLLAB HAUL: One editorial hook holds everything together.
COLLAB GIFTING: Relationship narrative first. Product is the act of care.
COLLAB PLATFORM: Platform is the brand. Products are editorial picks within it.

HONEY'S RULES:
ALWAYS: Connect product to a real moment. Include texture moment. Give emotional way in before selling. Captions add something the video does not say.
NEVER: Overclaim. Dump all benefits. Hard sell CTA. Caption as video transcript.

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

OUTPUT FORMAT — STRICT:
[REEL SCRIPT]
...full script...

[CAPTION]
...caption with hashtags...

No preamble. No notes. Just the two sections."""

FORMAT_MENU = (
    "What format is this for?\n\n"
    "1️⃣ IMMBT\n"
    "_(Instagram Made Me Buy This)_\n\n"
    "2️⃣ Event coverage\n"
    "_(launch, experience, destination)_\n\n"
    "3️⃣ Collaboration\n"
    "_(routine, narrative, haul, gifting)_"
)

SUBFORMAT_MENUS = {
    "immbt": (
        "Which type of IMMBT?\n\n"
        "1️⃣ Single product discovery\n"
        "2️⃣ Viral / hype check\n"
        "3️⃣ Sceptic won over"
    ),
    "event": (
        "What kind of event?\n\n"
        "1️⃣ Brand booth or launch\n"
        "2️⃣ Destination / travel day\n"
        "3️⃣ Community or group event"
    ),
    "collab": (
        "What kind of collab?\n\n"
        "1️⃣ Routine or tutorial\n"
        "2️⃣ Personal narrative\n"
        "3️⃣ Multi-product or haul\n"
        "4️⃣ Gifting or occasion\n"
        "5️⃣ Platform or retail"
    )
}

SUBFORMAT_LABELS = {
    "immbt": {
        "1": "IMMBT — single product discovery",
        "2": "IMMBT — viral hype check, sceptic who gets won over",
        "3": "IMMBT — personal resistance resolved by the product"
    },
    "event": {
        "1": "Event coverage — brand booth or launch",
        "2": "Event coverage — destination or full day travel experience",
        "3": "Event coverage — community or group event with friends"
    },
    "collab": {
        "1": "Brand collaboration — routine or tutorial, step by step with sensory detail",
        "2": "Brand collaboration — personal narrative, emotional hook, product as solution",
        "3": "Brand collaboration — multi-product haul, one editorial hook holds it together",
        "4": "Brand collaboration — gifting or occasion, relationship narrative first",
        "5": "Brand collaboration — platform or retail collab, platform is the brand"
    }
}

FORMAT_KEYS = {"1": "immbt", "2": "event", "3": "collab"}
VALID_SUBFORMAT_COUNTS = {"immbt": 3, "event": 3, "collab": 5}
GREETING_WORDS = ["hi", "hello", "hey", "start"]


def is_greeting(text):
    cleaned = text.lower().strip().rstrip("!.,? ")
    return any(cleaned.startswith(w) for w in GREETING_WORDS)


def send_message(to, body):
    try:
        twilio_client.messages.create(from_=TWILIO_NUMBER, to=to, body=body)
    except Exception as e:
        print(f"Send error: {e}")


def send_in_chunks(to, text, chunk_size=1500):
    text = text.strip()
    if len(text) <= chunk_size:
        send_message(to, text)
        return
    chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
    for chunk in chunks:
        send_message(to, chunk.strip())
        time.sleep(0.5)


def download_media(media_url):
    r = requests.get(
        media_url,
        auth=(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"]),
        timeout=30
    )
    r.raise_for_status()
    return r.content


def transcribe_audio(data, content_type):
    try:
        if "ogg" in content_type:
            ext = ".ogg"
        elif "mp4" in content_type or "m4a" in content_type:
            ext = ".m4a"
        elif "mpeg" in content_type or "mp3" in content_type:
            ext = ".mp3"
        elif "webm" in content_type:
            ext = ".webm"
        else:
            ext = ".ogg"

        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        with open(tmp_path, "rb") as audio_file:
            response = requests.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                files={"file": (f"audio{ext}", audio_file, content_type)},
                data={"model": "whisper-large-v3", "language": "en"}
            )

        os.unlink(tmp_path)

        if response.status_code == 200:
            result = response.json().get("text", "").strip()
            print(f"Transcription: '{result}'")
            return result
        else:
            print(f"Groq error: {response.text}")
            return ""

    except Exception as e:
        print(f"Transcription error: {e}")
        return ""


def extract_pdf(data):
    reader = PyPDF2.PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages).strip()


def extract_docx(data):
    result = mammoth.extract_raw_text(io.BytesIO(data))
    return result.value.strip()


def extract_email_brief(email_text):
    prompt = f"""This is a forwarded brand email. Extract only the relevant brief information for a content creator.

Return exactly this format:
BRAND: [brand name]
PRODUCT: [product name]
KEY CLAIMS: [2-3 key product claims or benefits]
DELIVERABLES: [what content is required]
DEADLINE: [if mentioned]
EXTRA NOTES: [any other relevant info]

EMAIL:
{email_text}

No preamble. Just the extracted brief."""

    response = anthropic_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text.strip()


def extract_brief(msg_body, media_url, content_type):
    if media_url:
        data = download_media(media_url)
        ct = content_type.lower()
        if "pdf" in ct:
            return extract_pdf(data), False
        elif "word" in ct or "docx" in ct or "officedocument" in ct:
            return extract_docx(data), False
        elif "image" in ct:
            img_b64 = base64.b64encode(data).decode()
            return f"[IMAGE:{img_b64}:{ct}]", False
    return msg_body.strip(), False


def looks_like_email(text):
    email_signals = [
        "from:", "subject:", "dear honey", "hi honey", "hello honey",
        "we would like", "we are reaching out", "collaboration",
        "partnership", "deliverables", "compensation", "deadline",
        "fwd:", "forwarded message", "------"
    ]
    lower = text.lower()
    matches = sum(1 for s in email_signals if s in lower)
    return matches >= 2


def generate_concepts(brief_text, format_label):
    prompt = f"""Based on this brand brief, generate 4 distinct creative concepts for an Instagram reel by Honey Sheth.

CONTENT FORMAT: {format_label}

BRAND BRIEF:
{brief_text}

Each concept should have a different angle, hook, or emotional approach.

Return EXACTLY this format:

CONCEPT 1: [Short punchy title]
[2 sentences describing the hook and angle]

CONCEPT 2: [Short punchy title]
[2 sentences describing the hook and angle]

CONCEPT 3: [Short punchy title]
[2 sentences describing the hook and angle]

CONCEPT 4: [Short punchy title]
[2 sentences describing the hook and angle]

No preamble. No notes. Just the 4 concepts."""

    response = anthropic_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=600,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text.strip()


def generate_script(brief_text, format_label, concept=None, extra_notes="", count=1):
    concept_line = f"\nCHOSEN CONCEPT TO EXECUTE:\n{concept}\n" if concept else ""

    if count > 1:
        prompt = f"""Write {count} distinct Instagram reel script variations for Honey Sheth, each with a different angle or hook.

CONTENT FORMAT: {format_label}
{concept_line}
{extra_notes}

BRAND BRIEF:
{brief_text}

Format each variation exactly like this:

VARIATION 1
[REEL SCRIPT]
...script...
[CAPTION]
...caption...

VARIATION 2
[REEL SCRIPT]
...script...
[CAPTION]
...caption...

No preamble. No notes."""

        messages = [{"role": "user", "content": prompt}]
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            messages=messages
        )
        return response.content[0].text.strip(), None, None

    if brief_text.startswith("[IMAGE:"):
        match = re.match(r'\[IMAGE:(.+):(.+)\]', brief_text)
        if match:
            img_b64, ct = match.group(1), match.group(2)
            messages = [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": ct, "data": img_b64}},
                    {"type": "text", "text": f"This is a brand brief image. Extract all info.\n\nCONTENT FORMAT: {format_label}\n{concept_line}\n{extra_notes}\n\nWrite a full Instagram reel script and caption in Honey Sheth's voice."}
                ]
            }]
        else:
            return None, None, "Sorry, could not read that image. Please send as text, PDF, or Word doc."
    else:
        prompt = f"""Write a full Instagram reel script and caption.

CONTENT FORMAT: {format_label}
{concept_line}
{extra_notes}

BRAND BRIEF:
{brief_text}

Follow the emotional arc. Sensory texture moment is non-negotiable. Keep CTA soft. Caption must be a completely different angle — quieter, more reflective."""
        messages = [{"role": "user", "content": prompt}]

    response = anthropic_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2200,
        system=SYSTEM_PROMPT,
        messages=messages
    )
    raw = response.content[0].text
    sm = re.search(r'\[REEL SCRIPT\]([\s\S]*?)(?=\[CAPTION\]|$)', raw, re.IGNORECASE)
    cm = re.search(r'\[CAPTION\]([\s\S]*?)$', raw, re.IGNORECASE)
    script = sm.group(1).strip() if sm else raw.strip()
    caption = cm.group(1).strip() if cm else ""
    return script, caption, None


def refine_script(brief_text, format_label, last_script, last_caption, instruction):
    prompt = f"""You previously wrote this script and caption for Honey Sheth.

CONTENT FORMAT: {format_label}

ORIGINAL BRIEF:
{brief_text}

PREVIOUS REEL SCRIPT:
{last_script}

PREVIOUS CAPTION:
{last_caption}

REFINEMENT REQUEST:
{instruction}

Rewrite incorporating this feedback. Keep everything that worked. Only change what was asked. Stay in Honey's voice."""

    response = anthropic_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2200,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.content[0].text
    sm = re.search(r'\[REEL SCRIPT\]([\s\S]*?)(?=\[CAPTION\]|$)', raw, re.IGNORECASE)
    cm = re.search(r'\[CAPTION\]([\s\S]*?)$', raw, re.IGNORECASE)
    script = sm.group(1).strip() if sm else raw.strip()
    caption = cm.group(1).strip() if cm else ""
    return script, caption


def send_script_and_caption(to, script, caption, multiple_raw=None):
    if multiple_raw:
        send_in_chunks(to, multiple_raw)
    else:
        send_in_chunks(to, "🎬 *REEL SCRIPT*\n─────────────────\n" + script)
        time.sleep(1)
        if caption:
            send_in_chunks(to, "📝 *CAPTION*\n─────────────────\n" + caption)
            time.sleep(0.5)
    send_message(to,
        "─────────────────\n"
        "Reply with feedback to refine — text or voice note\n"
        "Or send a new brief to start fresh."
    )


def process_concepts_and_send(from_number, brief_text, format_label):
    done = {"value": False}

    def progress():
        time.sleep(15)
        if not done["value"]:
            send_message(from_number, "Thinking up concepts… almost there ✍️")

    t = threading.Thread(target=progress)
    t.daemon = True
    t.start()

    try:
        concepts_text = generate_concepts(brief_text, format_label)
        done["value"] = True
        concepts = []
        pattern = re.findall(r'CONCEPT \d+:(.+?)(?=CONCEPT \d+:|$)', concepts_text, re.DOTALL)
        for c in pattern:
            concepts.append(c.strip())

        state = get_state(from_number)
        set_state(from_number, {**state, "concepts": concepts, "step": "awaiting_concept"})

        msg = "Here are your concept options:\n\n"
        for i, concept in enumerate(concepts, 1):
            msg += f"{i}️⃣ {concept}\n\n"
        msg += "Reply with 1, 2, 3, or 4 to choose.\nOr reply *all* to get all 4 written out."
        send_in_chunks(from_number, msg.strip())

    except Exception as e:
        done["value"] = True
        print(f"Concept error: {e}")
        send_message(from_number, "Something went wrong generating concepts. Send your brief again.")


def process_and_send(from_number, brief_text, format_label, concept=None, extra_notes="", count=1):
    done = {"value": False}

    def progress():
        time.sleep(20)
        if not done["value"]:
            send_message(from_number, "Still writing… almost there ✍️")

    t = threading.Thread(target=progress)
    t.daemon = True
    t.start()

    if count > 1:
        raw_multiple, _, _ = generate_script(brief_text, format_label, concept, extra_notes, count=count)
        done["value"] = True
        state = get_state(from_number)
        set_state(from_number, {**state, "last_script": raw_multiple, "last_caption": "", "step": "idle"})
        send_script_and_caption(from_number, None, None, multiple_raw=raw_multiple)
    else:
        script, caption, error = generate_script(brief_text, format_label, concept, extra_notes)
        done["value"] = True
        if error:
            send_message(from_number, error)
            return
        state = get_state(from_number)
        set_state(from_number, {**state, "last_script": script, "last_caption": caption, "step": "idle"})
        send_script_and_caption(from_number, script, caption)


def process_refine_and_send(from_number, instruction):
    state = get_state(from_number)
    brief_text = state.get("brief", "")
    format_label = state.get("subformat_label", "Instagram Made Me Buy This (IMMBT series)")
    last_script = state.get("last_script", "")
    last_caption = state.get("last_caption", "")

    done = {"value": False}

    def progress():
        time.sleep(20)
        if not done["value"]:
            send_message(from_number, "Refining… almost done ✍️")

    t = threading.Thread(target=progress)
    t.daemon = True
    t.start()

    script, caption = refine_script(brief_text, format_label, last_script, last_caption, instruction)
    done["value"] = True
    set_state(from_number, {**state, "last_script": script, "last_caption": caption, "step": "idle"})
    send_message(from_number, "Here's your refined version:")
    send_script_and_caption(from_number, script, caption)


def process_voice_brief_and_send(from_number, transcribed_text):
    state = get_state(from_number)
    set_state(from_number, {
        **state,
        "step": "awaiting_format",
        "brief": transcribed_text,
        "last_script": state.get("last_script", ""),
        "last_caption": state.get("last_caption", "")
    })
    send_message(from_number, f"🎤 Got your voice brief! Here's what I heard:\n\n_{transcribed_text}_\n\n" + FORMAT_MENU)


@app.route("/webhook", methods=["POST"])
def webhook():
    from_number  = request.form.get("From", "")
    msg_body     = request.form.get("Body", "").strip()
    num_media    = int(request.form.get("NumMedia", 0))
    media_url    = request.form.get("MediaUrl0", "") if num_media > 0 else ""
    content_type = request.form.get("MediaContentType0", "") if num_media > 0 else ""

    resp  = MessagingResponse()
    lower = msg_body.lower().strip()
    state = get_state(from_number)
    step  = state.get("step", "idle")

    # Handle voice notes first
    if media_url and content_type and any(x in content_type.lower() for x in ["audio", "ogg", "mpeg", "mp4", "webm"]):
        resp.message("🎤 Transcribing your voice note…")

        def handle_voice():
            try:
                data = download_media(media_url)
                transcribed = transcribe_audio(data, content_type.lower())

                if not transcribed:
                    send_message(from_number, "Couldn't make out what you said. Could you type it or try again?")
                    return

                # Always get fresh state inside the thread
                current_state = get_state(from_number)
                current_step = current_state.get("step", "idle")
                has_script = bool(current_state.get("last_script", ""))

                print(f"Voice routing — step: {current_step}, has_script: {has_script}, text: {transcribed[:50]}")

                # Has a previous script — treat as feedback
                if current_step in ["awaiting_refine"] or (current_step == "idle" and has_script):
                    send_message(from_number, f"🎤 Got your feedback:\n\n_{transcribed}_\n\nRefining now… give me 30 seconds.")
                    process_refine_and_send(from_number, transcribed)
                else:
                    # New brief
                    process_voice_brief_and_send(from_number, transcribed)

            except Exception as e:
                print(f"Voice handle error: {e}")
                send_message(from_number, "Something went wrong with your voice note. Please try again or type your message.")

        thread = threading.Thread(target=handle_voice)
        thread.daemon = True
        thread.start()
        return Response(str(resp), mimetype="text/xml")

    # Global commands
    if is_greeting(msg_body) and not media_url:
        set_state(from_number, {"step": "idle"})
        resp.message(
            "👋 Hey! I'm Honey's script generator.\n\n"
            "Send me a brand brief and I'll write the reel script + caption in your voice.\n\n"
            "*I can read:*\n"
            "📄 PDF files\n"
            "📝 Word docs\n"
            "🖼️ Images / screenshots\n"
            "📧 Forwarded brand emails\n"
            "🎤 Voice notes\n"
            "✍️ Plain text\n\n"
            "Just send it over!"
        )
        return Response(str(resp), mimetype="text/xml")

    if lower == "help":
        resp.message(
            "*How it works:*\n"
            "1. Send brief / email / voice note\n"
            "2. Choose format (1/2/3)\n"
            "3. Choose sub-format\n"
            "4. Pick a concept (1/2/3/4)\n"
            "5. Get reel script + caption\n"
            "6. Reply with feedback (text or voice) to refine\n\n"
            "*Commands:* hi, help, cancel"
        )
        return Response(str(resp), mimetype="text/xml")

    if lower == "cancel":
        set_state(from_number, {"step": "idle"})
        resp.message("Cancelled. Send a new brief whenever you're ready!")
        return Response(str(resp), mimetype="text/xml")

    # Awaiting format selection
    if step == "awaiting_format":
        if lower not in ["1", "2", "3"]:
            resp.message("Please reply with 1, 2, or 3.\n\n" + FORMAT_MENU)
            return Response(str(resp), mimetype="text/xml")
        chosen_format = FORMAT_KEYS[lower]
        set_state(from_number, {**state, "format": chosen_format, "step": "awaiting_subformat"})
        resp.message(SUBFORMAT_MENUS[chosen_format])
        return Response(str(resp), mimetype="text/xml")

    # Awaiting sub-format selection
    if step == "awaiting_subformat":
        chosen_format = state.get("format", "immbt")
        max_opts = VALID_SUBFORMAT_COUNTS.get(chosen_format, 3)
        valid = [str(i) for i in range(1, max_opts + 1)]
        if lower not in valid:
            resp.message(f"Please reply with a number between 1 and {max_opts}.\n\n" + SUBFORMAT_MENUS[chosen_format])
            return Response(str(resp), mimetype="text/xml")
        subformat_label = SUBFORMAT_LABELS[chosen_format][lower]
        brief_text = state.get("brief", "")
        set_state(from_number, {**state, "subformat_label": subformat_label, "step": "generating_concepts"})
        resp.message(f"Got it — *{subformat_label}*\n\n💡 Generating concept ideas… give me 15 seconds.")
        thread = threading.Thread(target=process_concepts_and_send, args=(from_number, brief_text, subformat_label))
        thread.daemon = True
        thread.start()
        return Response(str(resp), mimetype="text/xml")

    # Awaiting concept selection
    if step == "awaiting_concept":
        concepts = state.get("concepts", [])
        brief_text = state.get("brief", "")
        format_label = state.get("subformat_label", "")

        if lower == "all":
            set_state(from_number, {**state, "step": "generating"})
            resp.message("Writing all 4 variations… give me 60 seconds ✍️")
            thread = threading.Thread(target=process_and_send, args=(from_number, brief_text, format_label, None, "", 4))
            thread.daemon = True
            thread.start()
            return Response(str(resp), mimetype="text/xml")

        valid = [str(i) for i in range(1, len(concepts) + 1)]
        if lower not in valid:
            resp.message("Please reply with 1, 2, 3, or 4 — or reply *all* to get all variations.")
            return Response(str(resp), mimetype="text/xml")

        chosen_concept = concepts[int(lower) - 1]
        set_state(from_number, {**state, "chosen_concept": chosen_concept, "step": "generating"})
        resp.message("Love it! ✍️ Writing your script… give me 30 seconds.")
        thread = threading.Thread(target=process_and_send, args=(from_number, brief_text, format_label, chosen_concept))
        thread.daemon = True
        thread.start()
        return Response(str(resp), mimetype="text/xml")

    # Awaiting refine instruction
    if step == "awaiting_refine":
        if not msg_body:
            resp.message("What would you like to change? Type or send a voice note.")
            return Response(str(resp), mimetype="text/xml")
        set_state(from_number, {**state, "step": "generating"})
        resp.message("✍️ Refining… give me 30 seconds.")
        thread = threading.Thread(target=process_refine_and_send, args=(from_number, msg_body))
        thread.daemon = True
        thread.start()
        return Response(str(resp), mimetype="text/xml")

    # Idle with previous script — short message = refine
    if step == "idle" and state.get("last_script") and not media_url and len(msg_body) < 200:
        if not is_greeting(msg_body) and lower not in ["help", "cancel"]:
            set_state(from_number, {**state, "step": "awaiting_refine"})
            resp.message(
                "Sounds like feedback on your last script!\n\n"
                "Reply with what you'd like to change — text or voice note.\n"
                "Or send *cancel* to start fresh."
            )
            return Response(str(resp), mimetype="text/xml")

    # New brief
    if not msg_body and not media_url:
        resp.message("Send me a brand brief — text, PDF, Word doc, image, or voice note!")
        return Response(str(resp), mimetype="text/xml")

    try:
        brief_text, _ = extract_brief(msg_body, media_url, content_type)
    except Exception as e:
        print(f"Extract error: {e}")
        resp.message("Could not read that file. Please paste the brief as plain text.")
        return Response(str(resp), mimetype="text/xml")

    if not brief_text or len(brief_text) < 10:
        resp.message("Could not extract enough text. Please paste as text or send a clearer file.")
        return Response(str(resp), mimetype="text/xml")

    # Check if it's a forwarded email
    if looks_like_email(brief_text) and not media_url:
        resp.message("📧 Looks like a brand email! Extracting the brief… one moment.")
        try:
            extracted = extract_email_brief(brief_text)
            brief_text = extracted
            send_message(from_number, f"✅ Here's what I extracted:\n\n{extracted}\n\nProceeding to format selection...")
        except Exception as e:
            print(f"Email extract error: {e}")

    set_state(from_number, {
        "step": "awaiting_format",
        "brief": brief_text,
        "last_script": state.get("last_script", ""),
        "last_caption": state.get("last_caption", "")
    })
    resp.message("Got your brief!\n\n" + FORMAT_MENU)
    return Response(str(resp), mimetype="text/xml")


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}, 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
