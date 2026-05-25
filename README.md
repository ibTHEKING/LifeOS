# LifeOS

A multi-agent personal optimization system with a **Judge governance layer**.

LifeOS is a university AI project built to demonstrate **constrained, verifiable multi-agent collaboration** — the opposite of "wire an LLM into every box and hope for the best."

> Live demo: _add your `https://lifeos-ie.streamlit.app` link here once deployed_
> Code + docs page: _add your `https://ibTHEKING.github.io/LifeOS` link here once deployed_

## What it does

Upload your CV, state your career goal, and tell the system how you feel today. LifeOS will:

- **Search real job listings** across 4-6 free job boards (Arbeitnow, Remotive, RemoteOK, ejobs.ro for Romania, Adzuna if a key is provided, LinkedIn if an Apify token is provided).
- **Pick one seniority-appropriate match**, give you a short English overview of it, and a link to the original listing. You apply yourself — the system does not.
- **Build a realistic time-blocked day plan** that respects your fixed events, mood, and energy, and includes a small learning task aimed at the job's domain.
- **Produce a productivity briefing**: one focus rule for today, your top-priority block, a procrastination-risk score, a 1-10 productivity score.
- **Gate every agent output through the Judge** — a separate verification layer running on a different model tier. Outputs that fabricate facts or contradict the input are rejected before they reach you.

## Architecture

```
        ┌─────────────────────────────┐
        │       Streamlit UI          │
        │ CV(file) · goal · events ·  │
        │ sleep · energy · stress     │
        └──────────────┬──────────────┘
                       ▼
        ┌─────────────────────────────┐
        │        Orchestrator         │
        └──┬──────┬────────────┬──────┘
           │      │            │
           ▼      ▼            ▼
   ┌─────────┐ ┌────────┐ ┌──────────────┐
   │ Jobs    │ │ Career │→│ Schedule     │
   │ aggreg. │ │ Agent  │ │ Agent        │
   └─────────┘ └───┬────┘ └──────┬───────┘
                   │             │
                   │             ▼
                   │      ┌──────────────┐
                   │      │ Productivity │
                   │      │ Agent        │
                   │      └──────┬───────┘
                   │             │
                   ▼             ▼
        ┌─────────────────────────────┐
        │   Judge (different model)   │
        │  contract + consistency     │
        │  accept / revise / reject   │
        └─────────────────────────────┘
                       │
                       ▼
                logs/run_*.jsonl
```

- **Career Agent** (Gemini 3.1 Flash-Lite) → picks one job by INDEX from a real listings feed (hallucination-proof), writes an English overview, recommends a small learning task.
- **Schedule Agent** (Gemini 3.1 Flash-Lite) → time-blocked day plan including fixed events + the Career task.
- **Productivity Agent** (Gemini 3.1 Flash-Lite) → focus rule, top-priority block, productivity score, procrastination risk.
- **Judge** (Gemini 3.5 Flash, intentionally a stronger tier than the agents) → two layers:
  1. **Deterministic contract validator** — required fields, types, time-block sanity, forbidden phrases. No LLM call.
  2. **LLM consistency checker** — does the output fabricate facts not in the input? does it contradict the input?

Every run writes a structured JSON-lines log under `logs/run_<id>.jsonl` for traceability.

## Agentic contracts

Each agent operates under an explicit contract in YAML (`contracts/*.yml`):

- output schema (types, enums, length limits, regex patterns)
- forbidden phrases (e.g. "guaranteed", "you must")
- truthfulness rules (e.g. "never fabricate companies not in the CV", "never invent clock times")
- escalation rules (e.g. "if mood indicates burnout, reduce deep_work time and lower confidence")

The Judge enforces the contract on every output. Changing agent behaviour is a config edit, not a code change.

## Why this design

| Decision | Why |
|---|---|
| 3 agents + Judge (not 6 agents) | Depth over breadth. Each agent does its job under a real contract. |
| Judge runs a *different* model tier | Same-model self-grading is a known weakness in LLM-as-judge research. |
| Two-layer Judge | Deterministic checks catch the easy bugs free. LLM call only when deterministic check passes — saves quota. |
| **Index-based** job selection | The Career Agent returns an integer 1..N (or 0). The orchestrator fills the verbatim job details. Fabrication is structurally impossible. |
| Contracts as YAML, not code | Easy to inspect, easy to extend, defensible in a report. |
| Career Agent doesn't apply | Human-in-the-loop. The system surfaces matches with a link; the user decides. No irrecoverable actions. |
| JSONL run logs | Traceability + report screenshots + future evaluation. |

## Stack

- Python 3.10+
- [Streamlit](https://streamlit.io) — UI + free deploy
- [google-genai](https://ai.google.dev) — Gemini API (free tier)
- PyYAML, python-dotenv, requests, beautifulsoup4, pypdf

## Setup (local)

```bash
git clone https://github.com/ibTHEKING/LifeOS
cd lifeos
python -m pip install -r requirements.txt
cp .env.example .env       # then paste your Gemini API key into .env
streamlit run app.py
```

Open http://localhost:8501.

Get a free Gemini API key at https://aistudio.google.com → "Get API key". No credit card required.

## Optional integrations (set env vars, system auto-detects)

- **Adzuna** — better Romania coverage (250 free calls/month). Sign up at developer.adzuna.com → set `ADZUNA_APP_ID` and `ADZUNA_APP_KEY`.
- **LinkedIn via Apify** — adds LinkedIn job listings (free $5/mo Apify credit). Sign up at apify.com → set `APIFY_TOKEN`.

Without either, LifeOS uses Arbeitnow + Remotive + RemoteOK + ejobs.ro (all free, no auth required).

## Deploy (free)

- **Streamlit Community Cloud** (live app): push to a public GitHub repo, connect at https://share.streamlit.io, point at `app.py`. Set `GEMINI_API_KEY` in the app's Secrets panel. Live in ~2 min.
- **GitHub Pages** (landing page + docs): the `docs/` folder is published as a static site. Repo settings → Pages → source: `main` branch, `/docs` folder.

## Project structure

```
LifeOS/
├── app.py                          # Streamlit entry point
├── lifeos/
│   ├── config.py                   # paths, model names
│   ├── llm.py                      # Gemini client with retry + fallback
│   ├── jobs.py                     # multi-source job aggregator
│   ├── logger.py                   # JSONL run logger
│   ├── orchestrator.py             # the run loop
│   ├── agents/
│   │   ├── base.py
│   │   ├── career.py               # index-based job selection
│   │   ├── schedule.py
│   │   └── productivity.py
│   └── judge/
│       ├── contract_validator.py   # deterministic
│       ├── consistency_checker.py  # LLM, with compact input formatting
│       └── judge.py                # combines both
├── contracts/
│   ├── career_contract.yml
│   ├── schedule_contract.yml
│   └── productivity_contract.yml
├── data/
│   ├── cv_example.txt
│   ├── schedule_example.txt
│   └── personas.json
├── docs/
│   ├── index.html                  # GitHub Pages landing
│   ├── architecture.md
│   ├── n8n_integration.md
│   └── demo_script.md
├── logs/                           # runtime logs land here
├── tests/
│   └── test_basic.py
└── requirements.txt
```

## What this project is **not**

- Not a fully autonomous agent system. Every output is gated by the Judge and shown to the user.
- Not a job-application bot. The Career Agent surfaces matches with a link; the user clicks through and applies themselves.
- Not a financial advisor or trading bot.
- Not a hallucination-free system — but every output's confidence is scored and surfaced, so users can decide what to trust.

## Roadmap

- More agents from the original brief: Energy, Anti-Doomscrolling, Trading-Education
- Real Google Calendar / Gmail OAuth (replaces manually pasted events)
- n8n workflow wrapping the orchestrator for daily Telegram delivery
- Self-evaluation: collect Judge verdicts over N runs, plot rejection rate
- Persistent memory: track job recommendations + learning tasks over time

## License

MIT
