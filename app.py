import os
import re
import json
import uuid
import requests
from datetime import datetime
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

# Validate required env vars at startup
_REQUIRED_ENV = ["ANTHROPIC_API_KEY", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_WHATSAPP_NUMBER", "GROQ_API_KEY"]
for _key in _REQUIRED_ENV:
    if not os.environ.get(_key):
        raise RuntimeError(f"Missing required environment variable: {_key}")

anthropic_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
twilio_client = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])
TWILIO_NUMBER = os.environ["TWILIO_WHATSAPP_NUMBER"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

# ── Persistent storage ────────────────────────────────────────────────────────
# Uses /data if Railway volume is mounted, falls back to /tmp
STORAGE_PATH = "/data" if os.path.isdir("/data") else "/tmp"
STATE_DB     = os.path.join(STORAGE_PATH, "honey_state")
LIBRARY_FILE = os.path.join(STORAGE_PATH, "honey_library.json")
FEEDBACK_FILE = os.path.join(STORAGE_PATH, "honey_feedback.json")

print(f"Storage path: {STORAGE_PATH}")

state_lock   = threading.Lock()
library_lock = threading.Lock()

MAX_LIBRARY_SIZE  = 200  # cap to avoid giant GitHub commits
MAX_FEEDBACK_SIZE = 30   # rolling window of feedback entries
EXAMPLES_IN_PROMPT = 5   # how many approved scripts to inject per generation

# ── GitHub-backed library cache ───────────────────────────────────────────────
_library_cache      = None   # list[dict] | None
_library_cache_time = 0.0
LIBRARY_CACHE_TTL   = 300    # seconds before re-fetching from GitHub

def _gh_headers():
    token = os.environ.get("GITHUB_LIBRARY_TOKEN", "")
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }

def _gh_repo():
    return os.environ.get("GITHUB_REPO", "shethhoney/honey-script-bot")

def _gh_path():
    return "honey_library.json"

def _load_from_github():
    """Fetch honey_library.json from GitHub. Returns (entries, sha) or (None, None)."""
    token = os.environ.get("GITHUB_LIBRARY_TOKEN", "")
    if not token:
        return None, None
    try:
        r = requests.get(
            f"https://api.github.com/repos/{_gh_repo()}/contents/{_gh_path()}",
            headers=_gh_headers(), timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            content = base64.b64decode(data["content"]).decode("utf-8")
            return json.loads(content), data["sha"]
        print(f"GitHub library fetch status: {r.status_code}")
        return [], None
    except Exception as e:
        print(f"GitHub library load error: {e}")
        return None, None

def _save_to_github(entries):
    """Write entries to GitHub. Returns True on success."""
    token = os.environ.get("GITHUB_LIBRARY_TOKEN", "")
    if not token:
        return False
    try:
        # Get current SHA (needed for update)
        r = requests.get(
            f"https://api.github.com/repos/{_gh_repo()}/contents/{_gh_path()}",
            headers=_gh_headers(), timeout=10
        )
        sha = r.json().get("sha") if r.status_code == 200 else None

        content_b64 = base64.b64encode(
            json.dumps(entries, indent=2, ensure_ascii=False).encode()
        ).decode()
        payload = {
            "message": f"library: {len(entries)} approved scripts [bot]",
            "content": content_b64,
            "branch": "main",
        }
        if sha:
            payload["sha"] = sha

        r = requests.put(
            f"https://api.github.com/repos/{_gh_repo()}/contents/{_gh_path()}",
            headers=_gh_headers(), json=payload, timeout=15
        )
        ok = r.status_code in [200, 201]
        if not ok:
            print(f"GitHub library save error {r.status_code}: {r.text[:200]}")
        return ok
    except Exception as e:
        print(f"GitHub library save error: {e}")
        return False


# ── State (conversation flow) ─────────────────────────────────────────────────

def get_state(number):
    with state_lock:
        with shelve.open(STATE_DB) as db:
            return dict(db.get(number, {"step": "idle"}))

def set_state(number, data):
    with state_lock:
        with shelve.open(STATE_DB) as db:
            db[number] = data


# ── Script library ────────────────────────────────────────────────────────────

def load_library():
    """Return script library. Order of precedence: in-memory cache → GitHub → local file."""
    global _library_cache, _library_cache_time
    with library_lock:
        # 1. Serve from cache if fresh
        if _library_cache is not None and (time.time() - _library_cache_time) < LIBRARY_CACHE_TTL:
            return list(_library_cache)

        # 2. Try GitHub (primary permanent storage)
        entries, _ = _load_from_github()

        # 3. Fall back to local file if GitHub unavailable
        if entries is None:
            try:
                if os.path.exists(LIBRARY_FILE):
                    with open(LIBRARY_FILE, "r") as f:
                        entries = json.load(f)
                else:
                    entries = []
            except Exception as e:
                print(f"Local library load error: {e}")
                entries = _library_cache or []

        _library_cache      = list(entries)
        _library_cache_time = time.time()
        return list(entries)

def _save_library_background(entries):
    """Background: write to GitHub + local. Updates cache on success."""
    global _library_cache, _library_cache_time
    ok = _save_to_github(entries)
    if ok:
        print(f"Library saved to GitHub ({len(entries)} entries).")
    # Always save locally as backup regardless of GitHub result
    try:
        with open(LIBRARY_FILE, "w") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Local library backup save error: {e}")

def save_library(entries):
    """Update cache immediately, persist to GitHub + local in background."""
    global _library_cache, _library_cache_time
    with library_lock:
        _library_cache      = list(entries)
        _library_cache_time = time.time()
    threading.Thread(target=_save_library_background, args=(list(entries),), daemon=True).start()

def add_to_library(script, caption, format_label, brief):
    entries = load_library()
    entries.append({
        "id": str(uuid.uuid4())[:8],
        "saved_at": datetime.utcnow().isoformat(),
        "format": format_label,
        "script": script,
        "caption": caption,
        "brief_snippet": brief[:500] if brief else ""
    })
    # Keep only the most recent MAX_LIBRARY_SIZE
    if len(entries) > MAX_LIBRARY_SIZE:
        entries = entries[-MAX_LIBRARY_SIZE:]
    save_library(entries)
    return len(entries)

def get_examples_for_prompt(format_label, n=EXAMPLES_IN_PROMPT):
    """Return N most relevant approved scripts formatted for prompt injection.
    Prioritises same-format examples; includes brief→script mapping for few-shot quality."""
    entries = load_library()
    if not entries:
        return ""

    # Exact format match first (full label comparison), then partial, then anything
    fmt_lower = (format_label or "").lower()
    exact     = [e for e in entries if fmt_lower and e.get("format", "").lower() == fmt_lower]
    partial   = [e for e in entries if fmt_lower and fmt_lower[:20] in e.get("format", "").lower() and e not in exact]
    rest      = [e for e in entries if e not in exact and e not in partial]

    # Build pool: prefer exact matches, pad with partial/rest
    pool = exact + partial + rest
    # Take the n most recent from the format-relevant pool
    selected = pool[:n * 2]  # candidate set
    # Sort by recency — saved_at desc — then take n
    selected.sort(key=lambda e: e.get("saved_at", ""), reverse=True)
    selected = selected[:n]
    # Put exact-format examples first
    selected.sort(key=lambda e: (0 if e in exact else 1 if e in partial else 2))

    section  = "\n\n══════════════════════════════════════════\n"
    section += f"HONEY'S APPROVED SCRIPTS ({len(selected)} examples)\n"
    section += "These are scripts Honey actually approved — in her real voice.\n"
    section += "Your job: match this voice EXACTLY. Same rhythm. Same sentence length.\n"
    section += "Same PTC/VO/Visual structure. Same tone. Same level of sensory detail.\n"
    section += "══════════════════════════════════════════\n\n"
    for i, ex in enumerate(selected, 1):
        fmt   = ex.get("format", "")
        brief = ex.get("brief_snippet", "")
        section += f"── EXAMPLE {i}"
        if fmt:
            section += f" [{fmt}]"
        section += " ──\n"
        if brief:
            section += f"Brief context: {brief}\n\n"
        section += f"[REEL SCRIPT]\n{ex.get('script', '')}\n\n"
        if ex.get("caption"):
            section += f"[CAPTION]\n{ex.get('caption', '')}\n\n"
        section += "──────────────────────────────────────────\n\n"
    section += "Now write a NEW script for the brief below. Mirror the voice above exactly.\n\n"
    return section


# ── Feedback tracker ──────────────────────────────────────────────────────────

def load_feedback():
    try:
        if os.path.exists(FEEDBACK_FILE):
            with open(FEEDBACK_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        print(f"Feedback load error: {e}")
    return []

def save_feedback_log(entries):
    try:
        with open(FEEDBACK_FILE, "w") as f:
            json.dump(entries, f, indent=2)
    except Exception as e:
        print(f"Feedback save error: {e}")

def log_feedback(instruction, format_label):
    """Log a refinement instruction to build preference patterns."""
    entries = load_feedback()
    entries.append({
        "timestamp": datetime.utcnow().isoformat(),
        "format": format_label,
        "instruction": instruction
    })
    if len(entries) > MAX_FEEDBACK_SIZE:
        entries = entries[-MAX_FEEDBACK_SIZE:]
    save_feedback_log(entries)

def get_feedback_for_prompt():
    """Return recent feedback patterns for injection into refine prompt."""
    entries = load_feedback()
    if len(entries) < 3:
        return ""
    recent = entries[-10:]
    instructions = [e["instruction"] for e in recent]
    section = "\n\nHONEY'S RECENT FEEDBACK PATTERNS — things she has asked to change in past scripts:\n"
    for instr in instructions:
        section += f"• {instr}\n"
    section += "\nLearn from these patterns. Avoid repeating what she consistently corrects.\n"
    return section


# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a script writer for Honey Sheth — Indian lifestyle, beauty, and travel creator. You write in HER voice only. You have 36 of her real approved scripts as your ground truth. Match them exactly.

━━━ HONEY'S VOICE — WHAT IT SOUNDS LIKE ━━━

SENTENCE RHYTHM:
- Short. Punchy. Then one longer thought that lands.
- She writes how she talks. Incomplete sentences are fine. Em-dashes mid-thought.
- Never long explanatory sentences. "It's lightweight. Absorbs fast. Doesn't leave a residue."
- Pauses built into the writing — a line break IS a pause.

PTC TONE (piece to camera — her direct voice):
- Starts with something personal she's been thinking/feeling/avoiding. Not a product pitch.
- Honest qualifiers: "I think", "it feels like", "I've noticed", "I'm not sure why but"
- Conversational — like she's telling a friend, not an audience
- Pattern: [personal admission] → [what changed] → [soft verdict]
- She does NOT say: "I'm obsessed", "this is a game changer", "absolutely love", "I'm blown away"
- She DOES say: "I've noticed", "something about it just works", "it's the kind of thing that", "bas itna tha"

VO TONE (voiceover — product facts, sensory detail):
- Textures, temperatures, finishes, smells — specific and shootable
- "It melts in", "a little goes a long way", "sinks in without that heavy feeling"
- Product claims phrased as personal observation: "It claims X — and honestly, I think it's right"
- One ingredient or claim gets depth. Not a feature list.

HINDI CODE-SWITCHING:
- Natural, not forced. Only when emotion calls for it.
- Examples: "yaar", "bas itna tha", "aur kya chahiye", "honestly toh"
- Never transliterated in a way that feels like a translation exercise

VISUAL DIRECTION:
- Specific and shootable. The reader can picture the shot.
- "Close-up on fingers working the serum in" not "applying the product"
- Environment matters: morning light, airport bathroom, bathroom counter at night

━━━ SCRIPT STRUCTURE ━━━

Cue types:
Visual: [exact shot — what camera sees, lighting, environment]
PTC: [direct to camera — personal, honest, emotional. Eye contact moment.]
VO: [voiceover — sensory product detail, facts, texture]
Super: [text on screen — short, punchy, reinforces the moment]

EMOTIONAL ARC — every script:
1. HOOK — A personal moment, confession, or question. NOT a product intro. Stops the scroll.
2. PRODUCT ENTRY — product arrives naturally inside the story. Never announced.
3. SENSORY MOMENT — texture, application, how it actually feels. Non-negotiable.
4. QUIET SHIFT — what changed. Soft, earned, not dramatic.
5. CTA — one soft natural line. Never "link in bio", never "go buy it now."

━━━ CAPTIONS ━━━

- Opening line: truth, confession, or a moment — not a product claim
- 2–3 short paragraphs: sensory story + personal perspective
- Closing line: something that lingers. A thought, not a summary.
- Max 5 hashtags. Always #Ad. Brand handle.
- Caption is a DIFFERENT ANGLE from the video — quieter, more internal
- Style: reads like a diary entry or a short essay. Minimal emojis.

━━━ NEVER ━━━
- "obsessed", "game changer", "holy grail", "absolutely love", "I'm blown away"
- Hard sell CTA or "link in bio"
- Feature dumps — pick 1–2 things and go deep
- Caption that just summarises the video
- Generic PTC openers like "So I tried this product" or "I've been using this lately"
- Overly polished language — it should feel like she wrote it herself

━━━ FORMAT-SPECIFIC NOTES ━━━
IMMBT SINGLE: Opens with why it kept showing up / catching her attention. Honest scepticism first.
IMMBT HYPE CHECK: Leads with "I kept seeing this everywhere." Real scepticism. Gets won over by one specific thing.
IMMBT SCEPTIC: Resistance first — specific concern she had. Product resolves exactly that.
EVENT BOOTH: She discovers the brand in the space. Products come through activations and reactions.
EVENT DESTINATION: VO carries the journey. Names specific moments. Ends on feeling, not feature list.
EVENT COMMUNITY: Came with a friend. Group energy. Shared reactions are the story.
COLLAB ROUTINE: Step by step. Each product gets its own sensory moment and personal note.
COLLAB NARRATIVE: Emotional entry point first. Product arrives as the natural solution.
COLLAB HAUL: One editorial theme holds it together. Not a list — a perspective.
COLLAB GIFTING: The relationship or occasion is the story. Product is the act of care.
COLLAB PLATFORM: Platform is the character. Products are editorial picks within that world.

━━━ OUTPUT FORMAT — EXACT ━━━
[REEL SCRIPT]
(full script with Visual/PTC/VO/Super cues)

[CAPTION]
(caption with hashtags)

No preamble. No explanations. No notes after. Just the two sections."""

FORMAT_MENU = (
    "Which format?\n\n"
    "1️⃣ IMMBT _(Instagram Made Me Buy This)_\n\n"
    "2️⃣ Event _(launch, experience, destination)_\n\n"
    "3️⃣ Collab _(routine, narrative, haul, gifting)_"
)

SUBFORMAT_MENUS = {
    "immbt": (
        "What angle?\n\n"
        "1️⃣ Single product discovery\n"
        "2️⃣ Viral / hype check\n"
        "3️⃣ Sceptic won over"
    ),
    "event": (
        "What kind?\n\n"
        "1️⃣ Brand booth or launch\n"
        "2️⃣ Destination / travel day\n"
        "3️⃣ Community or group event"
    ),
    "collab": (
        "What kind?\n\n"
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
GREETING_TRIGGERS = {"hi", "hello", "hey", "start", "hi!", "hello!", "hey!"}

def is_greeting(text):
    return text.lower().strip().rstrip("!.,? ") in GREETING_TRIGGERS


# ── Messaging helpers ─────────────────────────────────────────────────────────

def send_message(to, body):
    try:
        twilio_client.messages.create(from_=TWILIO_NUMBER, to=to, body=body)
    except Exception as e:
        print(f"Send error: {e}")

def send_in_chunks(to, text, chunk_size=1500):
    if not text:
        return
    text = text.strip()
    if not text:
        return
    if len(text) <= chunk_size:
        send_message(to, text)
        return
    chunks = []
    while len(text) > chunk_size:
        split_at = text.rfind("\n", 0, chunk_size)
        if split_at == -1:
            split_at = chunk_size
        chunks.append(text[:split_at].strip())
        text = text[split_at:].strip()
    if text:
        chunks.append(text)
    for chunk in chunks:
        send_message(to, chunk)
        time.sleep(0.5)


# ── Media helpers ─────────────────────────────────────────────────────────────

def download_media(media_url):
    r = requests.get(
        media_url,
        auth=(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"]),
        timeout=30
    )
    r.raise_for_status()
    return r.content

def transcribe_audio(data, content_type):
    tmp_path = None
    try:
        ext = ".ogg"
        if "mp4" in content_type or "m4a" in content_type: ext = ".m4a"
        elif "mpeg" in content_type or "mp3" in content_type: ext = ".mp3"
        elif "webm" in content_type: ext = ".webm"

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
    finally:
        if tmp_path:
            try: os.unlink(tmp_path)
            except: pass

def extract_pdf(data):
    try:
        reader = PyPDF2.PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except Exception as e:
        print(f"PDF error: {e}")
        return ""

def extract_docx(data):
    try:
        result = mammoth.extract_raw_text(io.BytesIO(data))
        return result.value.strip()
    except Exception as e:
        print(f"DOCX error: {e}")
        return ""

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
    signals = ["from:", "subject:", "dear honey", "hi honey", "hello honey",
               "we would like", "we are reaching out", "collaboration",
               "partnership", "deliverables", "compensation", "deadline",
               "fwd:", "forwarded message", "------"]
    lower = text.lower()
    return sum(1 for s in signals if s in lower) >= 2

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
        model="claude-opus-4-6",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text.strip()


# ── Web search enrichment ─────────────────────────────────────────────────────

def search_product_usps(query):
    """Search for product details using Brave Search API. Returns snippets or empty string."""
    brave_key = os.environ.get("BRAVE_SEARCH_API_KEY", "")
    if not brave_key:
        return ""
    try:
        r = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"Accept": "application/json", "X-Subscription-Token": brave_key},
            params={"q": query, "count": 5},
            timeout=10
        )
        if r.status_code != 200:
            print(f"Brave search error: {r.status_code}")
            return ""
        results = r.json().get("web", {}).get("results", [])
        snippets = []
        for res in results[:5]:
            desc = res.get("description", "")
            title = res.get("title", "")
            if desc:
                snippets.append(f"• {title}: {desc}")
        return "\n".join(snippets)
    except Exception as e:
        print(f"Search error: {e}")
        return ""


def extract_brand_and_search(brief_text):
    """Extract brand/product from brief and search for USPs. Returns enrichment text or empty string."""
    if not os.environ.get("BRAVE_SEARCH_API_KEY", ""):
        return ""
    try:
        resp = anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=60,
            messages=[{"role": "user", "content": (
                f"Extract the brand name and product name from this brief.\n"
                f"Return ONLY two lines: BRAND: [name] and PRODUCT: [name].\n"
                f"If unclear, return BRAND: unknown PRODUCT: unknown.\n\n"
                f"BRIEF: {brief_text[:600]}"
            )}]
        )
        text = resp.content[0].text.strip()
        brand_m = re.search(r'BRAND:\s*(.+)', text, re.IGNORECASE)
        product_m = re.search(r'PRODUCT:\s*(.+)', text, re.IGNORECASE)
        brand = brand_m.group(1).strip() if brand_m else ""
        product = product_m.group(1).strip() if product_m else ""
        if not brand or brand.lower() == "unknown":
            return ""
        query = f"{brand} {product} key ingredients benefits claims".strip()
        snippets = search_product_usps(query)
        if not snippets:
            return ""
        return f"\n\nWEB-FETCHED PRODUCT DETAILS for {brand} {product}:\n{snippets}\n(Use these facts to make the script specific and accurate.)"
    except Exception as e:
        print(f"Brief enrichment error: {e}")
        return ""


# ── AI generation ─────────────────────────────────────────────────────────────

def generate_concepts(brief_text, format_label):
    examples = get_examples_for_prompt(format_label)
    prompt = f"""Based on this brand brief, generate 4 distinct creative concepts for an Instagram reel by Honey Sheth.

CONTENT FORMAT: {format_label}

BRAND BRIEF:
{brief_text}
{examples}
Each concept should have a different angle, hook, or emotional approach — consistent with Honey's approved voice above.

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
        model="claude-opus-4-6",
        max_tokens=600,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text.strip()


def generate_script(brief_text, format_label, concept=None, extra_notes="", count=1):
    concept_line = f"\nCHOSEN CONCEPT TO EXECUTE:\n{concept}\n" if concept else ""
    examples = get_examples_for_prompt(format_label)

    if count > 1:
        prompt = f"""Write {count} distinct Instagram reel script variations for Honey Sheth, each with a different angle or hook.

CONTENT FORMAT: {format_label}
{concept_line}
{extra_notes}

BRAND BRIEF:
{brief_text}
{examples}
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

        response = anthropic_client.messages.create(
            model="claude-opus-4-6",
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.content[0].text.strip()
        return raw if raw else "", None, None

    if brief_text.startswith("[IMAGE:"):
        match = re.match(r'\[IMAGE:(.+):(.+)\]', brief_text)
        if match:
            img_b64, ct = match.group(1), match.group(2)
            messages = [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": ct, "data": img_b64}},
                    {"type": "text", "text": f"This is a brand brief image. Extract all info.\n\nCONTENT FORMAT: {format_label}\n{concept_line}\n{extra_notes}\n{examples}\nWrite a full Instagram reel script and caption in Honey Sheth's voice."}
                ]
            }]
        else:
            return None, None, "Sorry, could not read that image. Please send as text, PDF, or Word doc."
    else:
        prompt = f"""FORMAT: {format_label}
{concept_line}
{extra_notes}

{examples}BRIEF:
{brief_text}

Write the script and caption for this brief. Voice must match the approved examples exactly — same rhythm, same PTC openings, same sensory VO detail, same soft CTA. Caption is a different angle from the video, not a summary."""
        messages = [{"role": "user", "content": prompt}]

    response = anthropic_client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2200,
        system=SYSTEM_PROMPT,
        messages=messages
    )
    raw = response.content[0].text
    sm = re.search(r'\[REEL SCRIPT\]([\s\S]*?)(?=\[CAPTION\])', raw, re.IGNORECASE)
    cm = re.search(r'\[CAPTION\]([\s\S]*?)$', raw, re.IGNORECASE)
    script = sm.group(1).strip() if sm else raw.strip()
    caption = cm.group(1).strip() if cm else ""
    return script, caption, None


def refine_script(brief_text, format_label, last_script, last_caption, instruction):
    feedback_patterns = get_feedback_for_prompt()
    examples = get_examples_for_prompt(format_label, n=2)

    prompt = f"""FORMAT: {format_label}

BRIEF:
{brief_text}

PREVIOUS SCRIPT:
{last_script}

PREVIOUS CAPTION:
{last_caption}

CHANGE REQUESTED:
{instruction}
{feedback_patterns}
{examples}Apply the change. Keep everything that worked. Do not rewrite what wasn't asked about. Stay in Honey's voice — match the approved examples above."""

    response = anthropic_client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2200,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.content[0].text
    sm = re.search(r'\[REEL SCRIPT\]([\s\S]*?)(?=\[CAPTION\])', raw, re.IGNORECASE)
    cm = re.search(r'\[CAPTION\]([\s\S]*?)$', raw, re.IGNORECASE)
    script = sm.group(1).strip() if sm else raw.strip()
    caption = cm.group(1).strip() if cm else ""
    return script, caption


# ── Background workers ────────────────────────────────────────────────────────

def send_script_and_caption(to, script, caption, multiple_raw=None):
    if multiple_raw:
        send_in_chunks(to, multiple_raw)
    else:
        send_in_chunks(to, "*SCRIPT*\n\n" + script)
        time.sleep(1)
        if caption:
            send_in_chunks(to, "*CAPTION*\n\n" + caption)
            time.sleep(0.5)
    send_message(to,
        "─\n"
        "Tell me what to tweak — text or voice note 🎤\n"
        "*again* → different angle  •  *save* → approve it 🧠"
    )

def process_concepts_and_send(from_number, brief_text, format_label):
    done = {"value": False}
    def progress():
        time.sleep(15)
        if not done["value"]:
            send_message(from_number, "Thinking up concepts… almost there ✍️")
    threading.Thread(target=progress, daemon=True).start()

    try:
        # Auto-enrich brief with web-searched product USPs if Brave API key is set
        enrichment = extract_brand_and_search(brief_text)
        if enrichment:
            brief_text = brief_text + enrichment
            current_state = get_state(from_number)
            set_state(from_number, {**current_state, "brief": brief_text})
            send_message(from_number, "🔍 Found product details online — enriching your brief with real USPs...")

        concepts_text = generate_concepts(brief_text, format_label)
        done["value"] = True
        concepts = []
        pattern = re.findall(r'CONCEPT \d+:\s*(.+?)(?=CONCEPT \d+:|$)', concepts_text, re.DOTALL)
        for c in pattern:
            stripped = c.strip()
            if stripped:
                concepts.append(stripped)

        if not concepts:
            set_state(from_number, {**get_state(from_number), "step": "idle"})
            send_message(from_number, "Couldn't parse the concepts. Send your brief again.")
            return

        state = get_state(from_number)
        set_state(from_number, {**state, "concepts": concepts, "step": "awaiting_concept"})

        count = len(concepts)
        msg = "Here are your concept options:\n\n"
        for i, concept in enumerate(concepts, 1):
            msg += f"{i}️⃣ {concept}\n\n"
        options_str = "/".join(str(i) for i in range(1, count + 1))
        msg += f"Reply with {options_str} to choose.\nOr reply *all* to get all {count} written out."
        send_in_chunks(from_number, msg.strip())

    except Exception as e:
        done["value"] = True
        print(f"Concept error: {e}")
        set_state(from_number, {**get_state(from_number), "step": "idle"})
        send_message(from_number, "Something went wrong generating concepts. Send your brief again.")


def process_and_send(from_number, brief_text, format_label, concept=None, extra_notes="", count=1):
    done = {"value": False}
    def progress():
        time.sleep(20)
        if not done["value"]:
            send_message(from_number, "Still writing… almost there ✍️")
    threading.Thread(target=progress, daemon=True).start()

    try:
        if count > 1:
            raw_multiple, _, _ = generate_script(brief_text, format_label, concept, extra_notes, count=count)
            done["value"] = True
            if not raw_multiple:
                set_state(from_number, {**get_state(from_number), "step": "idle"})
                send_message(from_number, "Something went wrong. Send your brief again.")
                return
            state = get_state(from_number)
            set_state(from_number, {**state, "last_script": raw_multiple, "last_caption": "", "step": "idle"})
            send_script_and_caption(from_number, None, None, multiple_raw=raw_multiple)
        else:
            script, caption, error = generate_script(brief_text, format_label, concept, extra_notes)
            done["value"] = True
            if error:
                set_state(from_number, {**get_state(from_number), "step": "idle"})
                send_message(from_number, error)
                return
            state = get_state(from_number)
            set_state(from_number, {**state, "last_script": script, "last_caption": caption, "step": "idle"})
            send_script_and_caption(from_number, script, caption)
    except Exception as e:
        done["value"] = True
        print(f"Generate error: {e}")
        set_state(from_number, {**get_state(from_number), "step": "idle"})
        send_message(from_number, "Something went wrong writing the script. Send your brief again.")


def process_refine_and_send(from_number, instruction):
    state = get_state(from_number)
    brief_text   = state.get("brief", "")
    format_label = state.get("subformat_label", "Instagram Made Me Buy This (IMMBT series)")
    last_script  = state.get("last_script", "")
    last_caption = state.get("last_caption", "")

    # Log this feedback to build preference patterns
    if instruction:
        log_feedback(instruction, format_label)

    done = {"value": False}
    def progress():
        time.sleep(20)
        if not done["value"]:
            send_message(from_number, "Refining… almost done ✍️")
    threading.Thread(target=progress, daemon=True).start()

    try:
        script, caption = refine_script(brief_text, format_label, last_script, last_caption, instruction)
        done["value"] = True
        set_state(from_number, {**state, "last_script": script, "last_caption": caption, "step": "idle"})
        send_message(from_number, "Here's your refined version:")
        send_script_and_caption(from_number, script, caption)
    except Exception as e:
        done["value"] = True
        print(f"Refine error: {e}")
        set_state(from_number, {**state, "step": "idle"})
        send_message(from_number, "Something went wrong refining. Send your feedback again.")


def process_brief_and_send(from_number, msg_body, media_url, content_type, prev_last_script, prev_last_caption):
    try:
        brief_text, _ = extract_brief(msg_body, media_url, content_type)
    except Exception as e:
        print(f"Extract error: {e}")
        send_message(from_number, "Could not read that file. Please paste the brief as plain text.")
        return

    if not brief_text or len(brief_text) < 10:
        send_message(from_number, "Could not extract enough text. Please paste as text or send a clearer file.")
        return

    if looks_like_email(brief_text) and not media_url:
        send_message(from_number, "📧 Looks like a brand email! Extracting the brief… one moment.")
        try:
            extracted = extract_email_brief(brief_text)
            brief_text = extracted
            send_message(from_number, f"✅ Here's what I extracted:\n\n{extracted}\n\nProceeding to format selection...")
        except Exception as e:
            print(f"Email extract error: {e}")
            send_message(from_number, "Couldn't auto-extract — proceeding with the full email text.")

    set_state(from_number, {
        "step": "awaiting_format",
        "brief": brief_text,
        "last_script": prev_last_script,
        "last_caption": prev_last_caption
    })
    send_message(from_number, "Got your brief!\n\n" + FORMAT_MENU)


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


# ── Webhook ───────────────────────────────────────────────────────────────────

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

    # ── Voice notes ───────────────────────────────────────────────────────────
    if media_url and content_type and any(x in content_type.lower() for x in ["audio", "ogg", "mpeg", "mp4", "webm"]):
        resp.message("🎤 Transcribing your voice note…")
        def handle_voice():
            try:
                data = download_media(media_url)
                transcribed = transcribe_audio(data, content_type.lower())
                if not transcribed:
                    send_message(from_number, "Couldn't make out what you said. Could you type it or try again?")
                    return
                current_state = get_state(from_number)
                current_step  = current_state.get("step", "idle")
                has_script    = bool(current_state.get("last_script", ""))
                if current_step == "awaiting_refine" or (current_step == "idle" and has_script):
                    send_message(from_number, f"🎤 Got your feedback:\n\n_{transcribed}_\n\nRefining now… give me 30 seconds.")
                    process_refine_and_send(from_number, transcribed)
                else:
                    process_voice_brief_and_send(from_number, transcribed)
            except Exception as e:
                print(f"Voice error: {e}")
                send_message(from_number, "Something went wrong with your voice note. Please try again.")
        threading.Thread(target=handle_voice, daemon=True).start()
        return Response(str(resp), mimetype="text/xml")

    # ── Save command ──────────────────────────────────────────────────────────
    if lower == "save":
        last_script  = state.get("last_script", "")
        last_caption = state.get("last_caption", "")
        format_label = state.get("subformat_label", "")
        brief        = state.get("brief", "")
        if not last_script:
            resp.message("No script to save yet. Generate one first!")
            return Response(str(resp), mimetype="text/xml")
        count = add_to_library(last_script, last_caption, format_label, brief)
        resp.message(
            f"✅ Saved! ({count} approved script{'s' if count != 1 else ''} in your library)\n\n"
            f"Every script from now uses this as a reference. The more you save, the more it sounds like you."
        )
        return Response(str(resp), mimetype="text/xml")

    # ── Again command — regenerate with a different angle ─────────────────────
    if lower == "again":
        brief_text   = state.get("brief", "")
        format_label = state.get("subformat_label", "")
        if not brief_text or not format_label:
            resp.message("No brief in memory yet — send me one first!")
            return Response(str(resp), mimetype="text/xml")
        set_state(from_number, {**state, "step": "generating"})
        resp.message("Different angle, coming up… 30 secs ✍️")
        threading.Thread(
            target=process_and_send,
            args=(from_number, brief_text, format_label, None,
                  "Try a completely different hook, opening moment, and emotional angle from any previous version."),
            daemon=True
        ).start()
        return Response(str(resp), mimetype="text/xml")

    # ── Library command ───────────────────────────────────────────────────────
    if lower in ["library", "my scripts", "examples"]:
        entries  = load_library()
        feedback = load_feedback()
        if not entries:
            resp.message(
                "Your library is empty.\n\n"
                "After generating a script you're happy with, type *save* to add it. "
                "The bot learns from every script you approve."
            )
        else:
            lines = [f"📚 *Your script library* — {len(entries)} approved script{'s' if len(entries) != 1 else ''}:\n"]
            for e in entries[-10:]:
                saved = e.get("saved_at", "")[:10]
                fmt   = e.get("format", "unknown")
                lines.append(f"• {saved} — {fmt}")
            if feedback:
                lines.append(f"\n🔁 {len(feedback)} feedback notes logged — these shape every refinement.")
            resp.message("\n".join(lines))
        return Response(str(resp), mimetype="text/xml")

    # ── Global commands ───────────────────────────────────────────────────────
    if is_greeting(msg_body) and not media_url:
        set_state(from_number, {"step": "idle"})
        library_count = len(load_library())
        library_line  = f"\n\n📚 Your library has {library_count} approved script{'s' if library_count != 1 else ''} — I'm learning from {'them' if library_count != 1 else 'it'}." if library_count > 0 else ""
        resp.message(
            "Hey Honey! 👋 Ready when you are.\n\n"
            "Drop a brief — text, PDF, Word doc, screenshot, forwarded email, or voice note — and I'll write the script + caption in your voice.\n\n"
            "*Commands:* save · again · library · help · cancel"
            + library_line
        )
        return Response(str(resp), mimetype="text/xml")

    if lower == "help":
        resp.message(
            "*How it works:*\n"
            "1. Send brief (text, PDF, doc, image, voice note, email)\n"
            "2. Pick format → sub-format\n"
            "3. Get script + caption\n"
            "4. Give feedback to refine (text or voice 🎤)\n\n"
            "*Commands:*\n"
            "• *again* — totally different angle, same brief\n"
            "• *save* — approve this version, teaches me your voice\n"
            "• *library* — see saved scripts\n"
            "• *cancel* — start over"
        )
        return Response(str(resp), mimetype="text/xml")

    if lower == "cancel":
        set_state(from_number, {"step": "idle"})
        resp.message("Cancelled. Send a new brief whenever you're ready!")
        return Response(str(resp), mimetype="text/xml")

    # ── Awaiting format ───────────────────────────────────────────────────────
    if step == "awaiting_format":
        if lower not in ["1", "2", "3"]:
            resp.message("Please reply with 1, 2, or 3.\n\n" + FORMAT_MENU)
            return Response(str(resp), mimetype="text/xml")
        chosen_format = FORMAT_KEYS[lower]
        set_state(from_number, {**state, "format": chosen_format, "step": "awaiting_subformat"})
        resp.message(SUBFORMAT_MENUS[chosen_format])
        return Response(str(resp), mimetype="text/xml")

    # ── Awaiting sub-format ───────────────────────────────────────────────────
    if step == "awaiting_subformat":
        chosen_format = state.get("format", "immbt")
        max_opts = VALID_SUBFORMAT_COUNTS.get(chosen_format, 3)
        valid = [str(i) for i in range(1, max_opts + 1)]
        if lower not in valid:
            resp.message(f"Pick a number between 1 and {max_opts} 👇\n\n" + SUBFORMAT_MENUS[chosen_format])
            return Response(str(resp), mimetype="text/xml")
        subformat_label = SUBFORMAT_LABELS[chosen_format][lower]
        brief_text = state.get("brief", "")
        lib_count  = len(load_library())
        learning_note = f" Using your {lib_count} saved scripts as reference." if lib_count > 0 else ""
        set_state(from_number, {**state, "subformat_label": subformat_label, "step": "generating"})
        resp.message(f"Perfect — *{subformat_label}*. Writing now… 30 secs ✍️{learning_note}")
        threading.Thread(target=process_and_send, args=(from_number, brief_text, subformat_label), daemon=True).start()
        return Response(str(resp), mimetype="text/xml")

    # ── Awaiting concept ──────────────────────────────────────────────────────
    if step == "awaiting_concept":
        concepts     = state.get("concepts", [])
        brief_text   = state.get("brief", "")
        format_label = state.get("subformat_label", "")
        count        = len(concepts)

        if lower == "all":
            set_state(from_number, {**state, "step": "generating"})
            resp.message(f"Writing all {count} variations… give me 60 seconds ✍️")
            threading.Thread(target=process_and_send, args=(from_number, brief_text, format_label, None, "", count), daemon=True).start()
            return Response(str(resp), mimetype="text/xml")

        valid = [str(i) for i in range(1, count + 1)]
        if lower not in valid:
            options_str = "/".join(valid)
            resp.message(f"Please reply with {options_str} — or reply *all* to get all variations.")
            return Response(str(resp), mimetype="text/xml")

        chosen_concept = concepts[int(lower) - 1]
        set_state(from_number, {**state, "chosen_concept": chosen_concept, "step": "generating"})
        resp.message("Love it! ✍️ Writing your script… give me 30 seconds.")
        threading.Thread(target=process_and_send, args=(from_number, brief_text, format_label, chosen_concept), daemon=True).start()
        return Response(str(resp), mimetype="text/xml")

    # ── Awaiting refine ───────────────────────────────────────────────────────
    if step == "awaiting_refine":
        if not msg_body:
            resp.message("What would you like to change? Type or send a voice note.")
            return Response(str(resp), mimetype="text/xml")
        set_state(from_number, {**state, "step": "generating"})
        resp.message("✍️ Refining… give me 30 seconds.")
        threading.Thread(target=process_refine_and_send, args=(from_number, msg_body), daemon=True).start()
        return Response(str(resp), mimetype="text/xml")

    # ── Idle with previous script — short message goes straight to refine ─────
    if step == "idle" and state.get("last_script") and not media_url:
        if not is_greeting(msg_body) and lower not in ["help", "cancel", "save", "again", "library", "my scripts", "examples"]:
            # Only treat as a new brief if it explicitly says so or is very long
            brief_signals = ["brand brief", "new brief", "collab brief", "new campaign", "new collab"]
            looks_like_brief = len(msg_body) > 500 or any(s in lower for s in brief_signals)
            if not looks_like_brief:
                set_state(from_number, {**state, "step": "generating"})
                resp.message("✍️ Refining… give me 30 seconds.")
                threading.Thread(target=process_refine_and_send, args=(from_number, msg_body), daemon=True).start()
                return Response(str(resp), mimetype="text/xml")

    # ── New brief ─────────────────────────────────────────────────────────────
    if not msg_body and not media_url:
        resp.message("Send me a brand brief — text, PDF, Word doc, image, or voice note!")
        return Response(str(resp), mimetype="text/xml")

    if msg_body and len(msg_body) > 8000:
        resp.message("That brief is very long! Please trim it to the key details — brand, product, key claims, and deliverables.")
        return Response(str(resp), mimetype="text/xml")

    resp.message("📨 Got it! Reading your brief…")
    threading.Thread(
        target=process_brief_and_send,
        args=(from_number, msg_body, media_url, content_type, state.get("last_script", ""), state.get("last_caption", "")),
        daemon=True
    ).start()
    return Response(str(resp), mimetype="text/xml")


@app.route("/health", methods=["GET"])
def health():
    return "ok", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
