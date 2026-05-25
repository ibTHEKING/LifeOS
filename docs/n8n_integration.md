# n8n Integration — Standalone Handoff Guide

> **Read this on the laptop where n8n runs.**
> This guide is fully self-contained. It does not assume Claude is available.

## What this gives you

A daily n8n workflow that:

1. Fires every morning via Cron
2. Asks you "sleep / energy / top priority?" via Telegram
3. Sends your reply + today's Google Calendar events + your CV to the LifeOS API
4. Receives the Judge-verified plan
5. Posts the plan back to you on Telegram

You can use this without Telegram too — the same payload can be written to a file, a Notion page, or any service n8n supports.

---

## 0. Plan of attack (read this first)

Total time: ~60-90 min if everything goes smoothly.

Order matters:

1. **[Quickstart minimal workflow](#quickstart-minimal-viable-workflow)** — prove the pipe works in 15 min, no Telegram or Calendar yet. Skip if you're confident.
2. **[Run LifeOS locally on this laptop](#1-run-lifeos-locally-on-this-laptop)**
3. **[Expose LifeOS as an HTTP API](#2-expose-lifeos-as-an-http-api)**
4. **[Set up the Telegram bot](#prereq-a-telegram-bot-setup-90-seconds)**
5. **[Set up Google Calendar OAuth](#prereq-b-google-calendar-oauth-setup-5-min)**
6. **[Build the full n8n workflow](#3-build-the-full-n8n-workflow)**
7. **[Test it end-to-end](#4-test-end-to-end)**

If you only have time for half of it, do steps 1-3 and skip Telegram/Calendar. You'll still have an automation you can trigger from the n8n UI manually.

---

## Quickstart: Minimal Viable Workflow

**Goal:** prove n8n can talk to LifeOS in 15 min, no Telegram, no Calendar.

This catches the connectivity / networking / Docker issues BEFORE you add the harder parts.

### Steps

1. Get LifeOS running locally on this laptop (next section).
2. Add the FastAPI wrapper (`api.py`) and start it. URL will be `http://localhost:8000/run`.
3. In n8n, create a new workflow with ONLY two nodes:
   - **Webhook trigger** (test mode is fine)
   - **HTTP Request node** posting to `http://localhost:8000/run` (or `http://host.docker.internal:8000/run` if n8n is in Docker — see [Docker gotchas](#docker-networking-gotchas))
4. In the HTTP Request body, hardcode a minimal payload:
   ```json
   {
     "cv": "Ibrahim Ammar, M.Sc. Data Science. Python, ETL, Power BI.",
     "goal": "BI internship at a fintech",
     "events": "09:00 - 10:30  Lecture",
     "mood": "Slept 7h, energy 6/10, stress medium."
   }
   ```
5. Click "Execute Workflow". The HTTP node should return JSON with `accepted: true` and `final_plan: {...}`.

If you see that JSON, **everything else in this doc is just plumbing on top**. If you see a connection error, it's a networking issue — go to [Docker gotchas](#docker-networking-gotchas).

---

## 1. Run LifeOS locally on this laptop

You should have Python 3.10+ installed. If not, install it from python.org.

```bash
git clone https://github.com/ibTHEKING/LifeOS.git
cd LifeOS
python -m pip install -r requirements.txt
```

Create a `.env` file in the `LifeOS` folder with one line:

```
GEMINI_API_KEY=AIzaSy...your-key-from-aistudio.google.com...
```

(The `.env` is gitignored — that's why you have to recreate it on each machine. The key itself is the same as on your other laptop.)

Verify it works:

```bash
streamlit run app.py
```

Visit `http://localhost:8501`. You should see the LifeOS UI. Try the "Ibrahim — normal day" persona once.

If that works, **you have proven all the agent logic works on this machine**. Now you stop using Streamlit and start using the API.

---

## 2. Expose LifeOS as an HTTP API

n8n needs an HTTP endpoint to POST to. Streamlit isn't that. We add a tiny FastAPI wrapper that shares the same agent code.

### Create `api.py` in the LifeOS folder root

```python
import os
from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv
from lifeos.llm import LLMClient
from lifeos.orchestrator import Orchestrator

load_dotenv()

app = FastAPI(title="LifeOS API")

class RunRequest(BaseModel):
    cv: str
    goal: str
    events: str
    mood: str

@app.post("/run")
def run(req: RunRequest):
    llm = LLMClient(api_key=os.getenv("GEMINI_API_KEY"))
    orch = Orchestrator(llm=llm)
    result = orch.run(cv=req.cv, goal=req.goal, events=req.events, mood=req.mood)
    return result.to_dict()

@app.get("/health")
def health():
    return {"status": "ok"}
```

### Install FastAPI and Uvicorn

```bash
pip install fastapi uvicorn
```

(Also add them to `requirements.txt` so the next clone gets them.)

### Run it

```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```

Now your machine has TWO LifeOS surfaces running side-by-side:
- `http://localhost:8501` — Streamlit UI (optional, you can stop it)
- `http://localhost:8000` — FastAPI for n8n

Test the API from another terminal:

```bash
curl http://localhost:8000/health
```

Should return `{"status":"ok"}`. If yes, the API is reachable.

### Production tip

You'll want this API to be running 24/7 in the background. On Windows, two cheap options:
- Open a terminal and just leave it running (simplest)
- Run it under `nssm` (a Windows service wrapper) so it auto-starts on boot

For tomorrow's setup, just leave a terminal open.

---

## Docker networking gotchas

If your n8n is running inside a Docker container (yours is, you mentioned), `localhost` from inside n8n does NOT mean your Windows host. It means the n8n container itself.

To reach a service running on your Windows host from a container:

- **Docker Desktop on Windows / Mac:** use `http://host.docker.internal:8000` instead of `http://localhost:8000`
- **Docker on Linux (older versions):** use the host's actual LAN IP (e.g. `http://192.168.1.42:8000`), or start the container with `--add-host=host.docker.internal:host-gateway`

To confirm which one applies to you, from inside the n8n container shell:

```bash
docker exec -it <n8n-container-name> sh
ping host.docker.internal
```

If ping succeeds, use `host.docker.internal`. If not, use your host's LAN IP.

**You'll plug this URL into the HTTP Request node** in every workflow that calls LifeOS.

---

## Prereq A: Telegram bot setup (90 seconds)

You need three things for n8n's Telegram nodes:
- A bot token (from BotFather)
- Your personal chat ID (from a quick API call)
- Your bot must have been DM'd at least once

### Steps

1. **Open Telegram** on your phone or desktop.
2. **Search for `@BotFather`** (official Telegram bot) and start a chat with it.
3. Send `/newbot`. BotFather will ask:
   - **Name** for your bot — e.g. "LifeOS Daily"
   - **Username** — must end in `bot`, e.g. `lifeos_daily_bot`
4. BotFather replies with a **token** like `7842957392:AAH-xxxxxxxxxxxxxxxxxxxxxxx`. **Save this** — you'll paste it into n8n.
5. **Open a chat with your new bot** (BotFather gives you a link). Send any message — `hi`. The bot won't reply (it has no code yet), but this step is REQUIRED to "activate" the conversation.
6. **Find your chat ID.** In a browser, open:
   ```
   https://api.telegram.org/bot<YOUR-TOKEN>/getUpdates
   ```
   Replace `<YOUR-TOKEN>` with the BotFather token. You'll see JSON. Look for `"chat":{"id":123456789,"first_name":"Ibrahim",...}`. The `id` number is your **chat_id**. Save it.

You now have:
- Bot token: `7842957392:AAH-xxx...`
- Chat ID: `123456789`

### Set up the n8n Telegram credential

1. In n8n, go to **Settings → Credentials → New** → search "Telegram"
2. Pick **Telegram API**
3. Paste the **token**, give the credential a name like "LifeOS Bot"
4. Save

Done. The Telegram nodes in your workflow will use this credential.

---

## Prereq B: Google Calendar OAuth setup (5 min)

n8n's Google Calendar node needs OAuth credentials from your Google Cloud project.

### Steps

1. **Open Google Cloud Console:** https://console.cloud.google.com
2. **Create a new project** (top bar, project selector → New Project). Name it "lifeos-n8n". Click Create.
3. **Enable the Calendar API:**
   - Left sidebar → "APIs & Services" → "Library"
   - Search "Google Calendar API" → click → **Enable**
4. **Configure the OAuth consent screen:**
   - Left sidebar → "APIs & Services" → "OAuth consent screen"
   - User type: **External** → Create
   - App name: "LifeOS n8n", user support email: your email, developer contact: your email
   - Skip "Scopes" (defaults are fine), skip "Test users" for now → Save and Continue
   - Back on the dashboard → click **"Publish app"** so you don't need to add yourself as a test user every time
5. **Create OAuth credentials:**
   - Left sidebar → "APIs & Services" → "Credentials"
   - Click **+ CREATE CREDENTIALS** → **OAuth client ID**
   - Application type: **Web application**
   - Name: "n8n Calendar"
   - **Authorized redirect URIs** — this is the critical part. Add:
     ```
     http://localhost:5678/rest/oauth2-credential/callback
     ```
     (Adjust port if your n8n runs on a different port. Default is 5678.)
     If n8n is on a domain or a remote host, use that domain instead of localhost.
   - Click **Create**
6. **Copy the Client ID and Client Secret** that pop up. Save both.

### Set up the n8n Google Calendar credential

1. In n8n: **Settings → Credentials → New** → search "Google Calendar"
2. Pick **Google Calendar OAuth2 API**
3. Paste the **Client ID** and **Client Secret** from step 6
4. Click **Sign in with Google** — opens a Google login. Sign in with the same Google account whose calendar you want to read.
5. Approve the permissions.
6. Save the credential.

Done. The Google Calendar node in your workflow will use this credential.

---

## 3. Build the full n8n workflow

This is the morning automation. Open n8n, create a new workflow, and add nodes in this order.

```
Cron (08:00 daily)
    │
    ▼
Telegram - Send Message
   "Good morning. Sleep? Energy? Top priority?"
    │
    ▼
Telegram Trigger (wait for reply)
    │
    ▼
Google Calendar - Get Events (today)
    │
    ▼
Function (build payload)
    │
    ▼
HTTP Request - POST {LIFEOS_API}/run
    │
    ▼
Function (format the plan as Markdown)
    │
    ▼
Telegram - Send Message (formatted plan)
```

### Detailed node settings

**Cron node**
- Mode: Every day
- Trigger time: 08:00
- Timezone: Europe/Bucharest

**Telegram node (the question)**
- Credential: "LifeOS Bot" (from Prereq A)
- Operation: Send Message
- Chat ID: your chat ID from Prereq A
- Text: `Good morning. Reply with: sleep_hours, energy 1-10, top priority for today.`

**Telegram Trigger (wait for reply)**
- Same credential
- Updates: message
- Make the workflow wait for the reply by chaining off this trigger or using a Wait node.

**Google Calendar - Get Events**
- Credential: from Prereq B
- Calendar: your primary
- Time range: today 00:00 → today 23:59

**Function node — build payload**

```javascript
const mood = $input.first().json.message.text;

// Pull events from the Google Calendar node output.
// Adapt the field names if your Calendar node uses different naming.
const events = $('Google Calendar').all()
  .map(e => {
    const start = (e.json.start?.dateTime || '').slice(11, 16);
    const end   = (e.json.end?.dateTime   || '').slice(11, 16);
    const summary = e.json.summary || '(no title)';
    return `${start} - ${end}  ${summary}`;
  })
  .join('\n');

// Paste your CV inline OR load it from a Notion / Drive node.
const cv = `Ibrahim Ammar
Bucharest, Romania

EDUCATION
- M.Sc. Data Science & Software Dev (in progress)
- B.Sc. Business Intelligence

SKILLS
- Python, SQL, Power BI, ETL, REST APIs
...paste the rest of your CV here as a JS template string...
`;

const goal = `Land a BI or Data Science role at a fintech in the next 3 months.`;

return [{ json: { cv, goal, events, mood } }];
```

**HTTP Request node**
- Method: POST
- URL: `http://host.docker.internal:8000/run` (or your actual API URL — see [Docker gotchas](#docker-networking-gotchas))
- Body Content Type: JSON
- Body: `={{ $json }}`
- Authentication: None (acceptable for v1 since the API is on your local network)
- Timeout: 60000 (60 sec — LifeOS takes ~30 sec end-to-end)

**Function node — format the result**

```javascript
const r = $input.first().json;

if (!r.accepted) {
  return [{ json: { text: `⚠️ LifeOS halted: ${r.halted_reason}` } }];
}

const ct = r.final_plan.career_task || {};
const sched = r.final_plan.schedule || {};
const prod = r.final_plan.productivity || {};

let jobLine = '_(no job match in current listings)_';
if (ct.selected_job) {
  const sj = ct.selected_job;
  jobLine = `*${sj.title}* @ ${sj.company}\n[Open listing](${sj.url})`;
}

const blocks = (sched.blocks || [])
  .map(b => `${b.start}-${b.end}  ${b.activity}`)
  .join('\n');

const text =
  `*🎯 Job match*\n${jobLine}\n\n` +
  `*Today's learning task*: ${ct.task || '—'}\n\n` +
  `*📅 Plan*:\n${blocks}\n\n` +
  `*⚡ Focus rule*: ${prod.focus_rule_today || '—'}\n` +
  `*Top priority*: ${prod.top_priority_block || '—'}\n` +
  `*Productivity score*: ${prod.productivity_score || '?'}/10\n`;

return [{ json: { text } }];
```

**Telegram node — send plan**
- Credential: "LifeOS Bot"
- Operation: Send Message
- Chat ID: your chat ID
- Text: `={{ $json.text }}`
- Parse Mode: **Markdown**

---

## 4. Test end-to-end

1. With LifeOS API still running (`uvicorn api:app ...`), in the n8n workflow editor click **"Execute Workflow"**.
2. Watch each node light up green as it runs.
3. The first Telegram node should send the morning question to your phone.
4. Reply on Telegram with something like `slept 7h, energy 6, top priority finish exam prep`.
5. The Calendar node fetches today's events (use a test event if today is empty).
6. The HTTP node takes ~30 sec — that's the LLM doing its job.
7. The final Telegram node sends back the plan as a Markdown message.

If something breaks, the failing node will show red. Click it to see the error.

---

## 5. Optional polish (post-deadline)

- Add a daily evening review node that asks "what did you finish?" and writes the answer to a Notion / Sheets log.
- Add a `/skip` command via Telegram that disables the morning workflow for one day.
- Add a second Cron at 22:00 to ask for tomorrow's sleep target.
- Pre-load the CV from a Notion page or Google Drive file rather than hardcoding it in the Function node.
- Add request signing or a simple shared secret to the FastAPI endpoint so only n8n can call it.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| HTTP node returns connection refused | API isn't running (start `uvicorn`). Or n8n in Docker is using `localhost` instead of `host.docker.internal`. |
| HTTP node returns 500 | `GEMINI_API_KEY` not in the FastAPI's environment. Restart `uvicorn` after editing `.env`. |
| HTTP node times out | LifeOS is slow on first call (~30 sec). Bump timeout to 90000. |
| Telegram bot never sends | Bot token wrong, or you never DM'd the bot. Double-check token, then send "hi" to the bot. |
| `getUpdates` returns empty | You haven't messaged the bot yet. Open the bot in Telegram, send any message, retry. |
| Google Calendar node fails OAuth | Redirect URI in Google Cloud Console doesn't EXACTLY match the one n8n shows you. Copy the n8n one verbatim. |
| Function node complains about JSON | Make sure it returns `[{ json: {...} }]` — n8n expects a list of objects. |
| LifeOS returns `accepted: false` | Judge rejected an agent. Open the LifeOS Streamlit UI locally, run the same inputs, check the Logs tab for the reasoning. Then fix the inputs (usually CV is too short or events are malformed). |
| API key works locally but not in workflow | Two different `.env` files. The FastAPI uses `LifeOS/.env`. Confirm it's the right path. |

If something breaks badly and you can't reach a Claude session: **the LifeOS Python project on its own works fine without n8n.** Run `streamlit run app.py` and you have the full app via the browser UI. n8n is just a delivery channel.

---

That's the entire handoff. Save this file for offline reference.
