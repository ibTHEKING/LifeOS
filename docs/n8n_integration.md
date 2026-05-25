# n8n Integration — Standalone Handoff Guide

> **Read this on the laptop where n8n runs.**
> This guide is self-contained. It does not assume you have AI assistance available while you follow it.

## What this gives you

A daily n8n workflow that:

1. Fires at 08:00 every morning (cron)
2. Asks you "sleep / energy / top priority?" via Telegram
3. Sends your reply, plus today's Google Calendar events, plus your CV, to the LifeOS API
4. Receives the Judge-verified plan
5. Posts the plan back to you on Telegram

You can use this without a Telegram bot too — the n8n workflow can fire and write the result to a file, or to a Notion page, or to anything else n8n supports.

## Prerequisites on the n8n machine

- n8n already running in Docker (you have this).
- The machine can make outbound HTTPS requests to the LifeOS Streamlit Cloud URL.
- (Optional) Telegram bot token, if you want Telegram delivery.
- (Optional) Google OAuth credentials for the Google Calendar node.

You do **not** need Python installed on the n8n machine. n8n only calls the deployed LifeOS app over HTTP.

## Step 1 — Expose LifeOS as an HTTP endpoint

The current Streamlit app is a UI. n8n needs an HTTP endpoint. You have three options.

### Option A — quickest: deploy a FastAPI wrapper next to Streamlit

Add the following file to the repo on the *coding* machine:

**`api.py`**
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
```

Add `fastapi` and `uvicorn` to `requirements.txt`. Deploy this on **Render** or **Fly.io** free tier as a Web Service (Streamlit Cloud only serves the Streamlit app, not arbitrary FastAPI). Note the public URL — call it `LIFEOS_API_URL` below.

### Option B — slowest, but no second deploy

Keep only Streamlit. Make n8n drive a headless browser (Puppeteer / Browserless) against the Streamlit URL. Fragile, not recommended.

### Option C — n8n itself runs the Python

Mount the LifeOS repo into the n8n Docker container and call the orchestrator via the "Execute Command" node. Works only if you self-host n8n with Python available inside the container. Detailed setup not covered here.

**Go with Option A.** Below assumes you have `LIFEOS_API_URL` from a Render deploy.

## Step 2 — Create the n8n workflow

In the n8n UI, build this graph:

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
Function (build prompt payload)
    │
    ▼
HTTP Request - POST {LIFEOS_API_URL}/run
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
- Operation: Send Message
- Chat ID: your personal chat ID
- Text: `Good morning. Reply with: sleep_hours, energy 1-10, top priority for today.`

**Telegram Trigger (wait for reply)**
- Updates: message
- Make the workflow wait for the reply by chaining off this trigger or by using "Wait" semantics.

**Google Calendar - Get Events**
- Calendar: your primary
- Time range: today 00:00 → today 23:59
- Map the event list to a simple string in the next Function node

**Function node — build payload**
```javascript
const mood = $input.first().json.message.text;
const events = $('Google Calendar').all()
  .map(e => `${e.json.start.dateTime.slice(11,16)} - ${e.json.end.dateTime.slice(11,16)}  ${e.json.summary}`)
  .join('\n');

// Paste your CV inline OR fetch it from a Notion/Drive node first.
const cv = `<<<paste your CV text here, or load it from a file/Drive node>>>`;
const goal = `Land a backend engineering internship at a fintech in the next 3 months.`;

return [{ json: { cv, goal, events, mood } }];
```

**HTTP Request node**
- Method: POST
- URL: `{LIFEOS_API_URL}/run`
- Body Content Type: JSON
- Body: `={{ $json }}`
- Authentication: None (the LIFEOS_API_URL is sufficient secrecy for v1; add an API key later)

**Function node — format the result**
```javascript
const r = $input.first().json;
if (!r.accepted) {
  return [{ json: { text: `LifeOS halted: ${r.halted_reason}` } }];
}
const ct = r.final_plan.career_task;
const sched = r.final_plan.schedule;
const blocks = sched.blocks.map(b => `${b.start}-${b.end}  ${b.activity}`).join('\n');
const text = `*Today's learning task*: ${ct.task}\n_${ct.rationale}_\n\n*Plan*:\n${blocks}\n\n_${sched.reasoning}_`;
return [{ json: { text } }];
```

**Telegram node — send plan**
- Operation: Send Message
- Chat ID: same as above
- Text: `={{ $json.text }}`
- Parse Mode: Markdown

## Step 3 — Secrets

In n8n, set credentials for:
- Telegram bot token
- Google account (Calendar OAuth)

Do **not** put your Gemini API key in n8n. The key lives on the Render/Fly deployment of the FastAPI wrapper (`api.py`) as an environment variable. n8n never sees it.

## Step 4 — Test

Trigger the workflow manually from the n8n UI first. Walk through each node and inspect the data shape. Common gotchas:

- The Telegram trigger needs the bot to be a member of your chat (DM your bot at least once to start the conversation).
- Google Calendar OAuth: the n8n redirect URI must match the one in the Google Cloud console.
- The HTTP Request node times out at 30s by default — Streamlit Cloud cold starts can exceed this. Use Render free tier for the API, not Streamlit Cloud, because Streamlit doesn't expose arbitrary HTTP endpoints.
- If the LifeOS API returns a `reject` verdict, the Telegram message will say so. That's correct behaviour — the Judge stopped a bad output before it reached you.

## Step 5 — Optional polish

- Add a daily evening review node that asks "what did you finish?" and writes it to a Notion / Sheets log
- Add a "Skip today" command via Telegram that disables the morning workflow for one day
- Add a second Cron at 22:00 to ask for tomorrow's sleep target

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| HTTP node returns 401/403 | API key wrong on the FastAPI deploy |
| HTTP node times out | Render free tier cold start. Hit the URL once 30s before to wake it. |
| Telegram never sends | Bot token wrong, or you never DM'd the bot |
| Plan is full of `[]` and empty fields | Judge rejected — open the LifeOS UI and check the Logs tab |
| n8n complains about JSON | Function node didn't return `[{ json: {...} }]` — n8n expects a list |

If something breaks on the n8n side and you can't reach a Claude session: the LifeOS Python project on the *other* laptop is self-contained. Run it locally with `streamlit run app.py` and you have the full app without n8n.

---

That's the entire handoff. Save this file for offline reference.
