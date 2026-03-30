# Honey Script Bot — Setup Guide
## From zero to working WhatsApp bot in ~45 minutes

---

## What you'll have when done
A WhatsApp number you can forward brand briefs to.
It reads PDFs, Word docs, images, voice notes, and text.
It replies with a full reel script + caption in your voice.

---

## STEP 1 — Get your code onto GitHub (5 min)

1. Go to github.com and sign in (or create a free account)
2. Click the **+** button top right → **New repository**
3. Name it: `honey-script-bot`
4. Set to **Private**
5. Click **Create repository**
6. On the next screen, click **uploading an existing file**
7. Upload all 5 files from the folder I gave you:
   - `app.py`
   - `requirements.txt`
   - `Procfile`
   - `railway.toml`
   - `nixpacks.toml`
8. Click **Commit changes**

---

## STEP 2 — Deploy to Railway (10 min)

Railway hosts your bot so it's always running.

1. Go to **railway.app** and sign up with your GitHub account
2. Click **New Project** → **Deploy from GitHub repo**
3. Select `honey-script-bot`
4. Railway will start building automatically — wait for it to say **Deployed** (takes ~3 min)
5. Click on your service → **Settings** → **Networking** → **Generate Domain**
6. Copy the domain it gives you — looks like: `honey-script-bot-production.up.railway.app`
   *(You'll need this in Step 4)*

**Add your environment variables:**
Still in Railway → your service → **Variables** tab → Add these one by one:

| Variable | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `TWILIO_ACCOUNT_SID` | From Twilio (Step 3) |
| `TWILIO_AUTH_TOKEN` | From Twilio (Step 3) |
| `TWILIO_WHATSAPP_NUMBER` | From Twilio (Step 3) |

*(Come back to fill the Twilio ones after Step 3)*

---

## STEP 3 — Set up Twilio WhatsApp (15 min)

Twilio is the service that connects WhatsApp to your bot.

1. Go to **twilio.com** → Sign up for a free account
2. Verify your phone number during signup
3. From the Twilio Console dashboard, note down:
   - **Account SID** (starts with `AC...`)
   - **Auth Token** (click the eye icon to reveal)
4. In the left sidebar → **Messaging** → **Try it out** → **Send a WhatsApp message**
5. Follow the instructions to join the Twilio sandbox:
   - You'll be given a WhatsApp number (e.g. `+1 415 523 8886`)
   - Send the join code from YOUR WhatsApp to that number
   - e.g. send `join apple-mango` to `+1 415 523 8886`
6. Once joined, go to **Messaging** → **Settings** → **WhatsApp Sandbox Settings**
7. In the **"When a message comes in"** field, paste:
   ```
   https://YOUR-RAILWAY-DOMAIN/webhook
   ```
   (Replace `YOUR-RAILWAY-DOMAIN` with what you copied in Step 2)
8. Set the HTTP method to **POST**
9. Click **Save**

**Copy these back into Railway variables:**
- `TWILIO_ACCOUNT_SID` → your Account SID
- `TWILIO_AUTH_TOKEN` → your Auth Token
- `TWILIO_WHATSAPP_NUMBER` → `whatsapp:+14155238886` (the sandbox number, with `whatsapp:` prefix)

---

## STEP 4 — Test it (5 min)

1. Open WhatsApp on your phone
2. Message the Twilio sandbox number: `+1 415 523 8886`
3. Send: `hi`
4. You should get a welcome message back within a few seconds
5. Now paste any brand brief as text and hit send
6. Wait ~15-20 seconds — your script and caption will arrive

**Test with a file:**
- Forward a PDF brand brief to the same number
- It will extract the text and write the script automatically

---

## HOW TO USE IT DAY-TO-DAY

**Send a brief as text:**
Just paste it and send. The bot auto-detects whether it's IMMBT, event, or collab format.

**Send a PDF or Word doc:**
Attach and send — it reads and extracts the text automatically.

**Send an image/screenshot of a brief:**
It will OCR the text and extract the brief.

**Send a voice note:**
Record yourself summarising the brief. It transcribes and writes the script.

**Force a specific format:**
Start your message with the format name:
- `immbt [brief]` → forces IMMBT format
- `event [brief]` → forces event coverage format
- `collab [brief]` → forces collaboration format

**Refine a script:**
Send `refine` after receiving a script, then tell it what to change.
e.g. `make the hook more personal` or `try a different CTA`

**Get help:**
Send `help` anytime.

---

## GOING LIVE (when ready to move beyond sandbox)

The sandbox is for testing. When you want a dedicated WhatsApp number:

1. In Twilio → **Messaging** → **Senders** → **WhatsApp Senders**
2. Apply for a WhatsApp Business number (~1-2 days approval)
3. Update `TWILIO_WHATSAPP_NUMBER` in Railway to your new number
4. Cost: ~$1/month for the number + $0.005 per message

---

## COSTS SUMMARY

| Service | Free tier | Paid |
|---|---|---|
| Railway | 500 hrs/month free | $5/month after |
| Twilio sandbox | Free for testing | $1/month + $0.005/msg |
| Anthropic API | Pay per use | ~$0.01-0.03 per script |

**Estimated monthly cost for regular use: $6-10/month**

---

## TROUBLESHOOTING

**Bot not responding:**
- Check Railway → your service → **Logs** tab for errors
- Make sure all 4 environment variables are set correctly
- Make sure the webhook URL in Twilio matches your Railway domain exactly

**"I couldn't extract enough text" error:**
- Try sending the brief as plain text instead
- Make sure PDFs aren't password-protected
- For images, make sure the text is clear and not too small

**Script feels off:**
- Use `refine` to adjust
- Or add more context to your brief about the personal angle

---

*Questions? Come back to Claude and share the error message — I'll help debug it.*
