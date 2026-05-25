# LifeOS — Demo Script

What to say, in what order, in front of the panel. ~5 minutes if pressed.

## Opening (30 sec)

> "LifeOS is a multi-agent personal optimization system. Most multi-agent demos in this category have the same problem: agents hallucinate, contradict each other, or just rephrase the prompt. The thing I want to show you is **the layer that catches that** — the Judge."

Open the deployed Streamlit app. Make sure the URL is visible.

## Pitch the architecture (60 sec)

Click the **🏗 Architecture** tab.

> "Three agents collaborate. Career searches real job listings and recommends one, with an English overview and a link. Schedule builds a day plan that includes a learning task aimed at the job. Productivity adds a focus rule and a score. All three run on Gemini 3.1 Flash-Lite."
>
> "The Judge runs on Gemini 3.5 Flash — a **different model tier** on purpose, because same-model self-grading is a known weakness in LLM-as-judge research."
>
> "Every agent output passes through two checks: a deterministic contract validator that costs nothing, then an LLM consistency check. The verdict is accept, revise, or reject."

## Demo 1 — happy path (90 sec)

Click **▶ Run** tab. Either upload your CV or pick a persona. Hit "Run LifeOS".

While it runs:

> "Behind the scenes: the orchestrator just hit Arbeitnow, Remotive, RemoteOK, and ejobs.ro in parallel. It deduped and scored the listings, then passed the top 8 to the Career Agent. The Career Agent picks one **by index** — it returns an integer, not free-text. So it cannot hallucinate a job that doesn't exist. The orchestrator fills in the verbatim title and URL from the original listing."

When the result appears:

> "Here's the job — title, company, English summary, link. Click the link and you can apply yourself. The system does not apply for you."
>
> "Here's the day plan — every fixed event preserved, the learning task placed in a sensible slot."
>
> "And here's the productivity briefing — focus rule, top-priority block, score out of 10."

Click the **⚖ Judge** tab.

> "Every agent's output got a verdict. Contract checks passed for all three. Consistency scores are visible. The Judge's reasoning is here below each."

## Demo 2 — Judge actually says no (90 sec)

Two ways to trigger this:

**Option A** — change the CV to be very weak ("3rd year student, no projects, no skills"). The Career Agent should return index=0 ("no suitable match for an intern in current listings") — that's the agent **correctly refusing to recommend a senior role for a junior CV**.

> "Watch — same job list, weaker CV. The Career Agent now refuses to recommend any of the senior roles. Returns index 0 with confidence low. This is not the Judge rejecting it — this is the Career Agent's own contract saying 'no good match'. The Judge then accepts that refusal."

**Option B** — pick the "Empty CV" persona (if you have one).

> "Empty CV. A naive multi-agent system would still confidently invent a 'learning task aligned with your goal.' Watch the Judge."

When done:

> "Look at the Judge tab. The Career Agent's `sources_from_cv` list is empty because the CV is empty — there's nothing to ground in. The Judge caught it and lowered the score. This is the safety net working."

## Demo 3 — Burnout adaptation (60 sec, optional)

Run with mood: sleep 4h, energy 2/10, stress high.

> "Same CV. Same events. Only the mood changed — burnout signals."

Show the plan:

> "Deep work blocks are reduced. More breaks. The Productivity score dropped. Procrastination risk flipped to high. The Productivity Agent's focus rule got gentler. None of this was hardcoded — the contracts have escalation rules that the agents read at runtime, and the Judge verifies the agents actually applied them."

## The "why this design" close (30 sec)

> "Three things to remember:
>
> One — the Judge is a separate component running a different model tier. That's a real architectural decision, not a wrapper.
>
> Two — the Career Agent picks jobs by integer index. Hallucination of jobs is structurally impossible, not just prompted against.
>
> Three — the agentic contracts are YAML files, not hardcoded prompts. You can change agent behaviour without touching code. The Judge reads them at runtime."

## If they ask hard questions

**Q: Why not just use OpenAI's GPT for both agents and judge?**
> The Judge needing a *different* model is the point. Cross-provider would be even stronger; that's in the roadmap. Free-tier kept us in one family for this iteration.

**Q: How do you handle LLM hallucination on the job picks?**
> Index-based selection. The agent returns an integer between 1 and N (or 0 for no match). The orchestrator fills in the actual job from the original API result. The agent cannot invent a job that wasn't in the list — that's a structural guarantee, not a prompted rule.

**Q: What's stopping the agent from picking the wrong job?**
> Two checks: (1) the agent's own prompt has explicit seniority-matching rules — "don't pick Senior/Staff/Lead for a junior CV". (2) The Judge's consistency layer reviews the pick against the CV and the chosen job's requirements. If there's a mismatch, it scores low.

**Q: What stops the Judge from being too strict and rejecting everything?**
> Threshold tuning. ACCEPT_THRESHOLD and REVISE_THRESHOLD live in one file (`lifeos/judge/judge.py`). During development we saw the Judge correctly catch an out-of-bounds index, a fabricated time block, and a senior-for-junior mismatch. The thresholds are conservative but the system still produces output on most runs.

**Q: Where do the jobs come from? Aren't most job APIs paid?**
> Five sources, four of which are completely free and need no signup: Arbeitnow (EU + remote), Remotive (global remote), RemoteOK (global remote), and ejobs.ro for Romania-local. Two are optional and require free keys: Adzuna (better Romania coverage, 250 calls/month free) and LinkedIn via Apify ($5/month free credit).

**Q: How does this scale to more agents?**
> Each new agent needs a YAML contract + a Python class extending BaseAgent. The Judge is agent-agnostic — it reads whatever contract you pass it. Adding the Energy Agent or Anti-Doomscrolling Agent from the original brief is ~40 lines each.

**Q: Real users? Real data?**
> I am the test user. The CV in the demo is mine. The calendar pipeline isn't wired in this version — events are pasted — but the n8n integration doc in the repo covers that exact wiring on my home machine.

**Q: Is this safe? Can it do anything bad?**
> No. The system has no tools. It cannot write to my calendar, send messages, or modify any external state. It only proposes text. That's a deliberate design choice — adding action-taking would need a stronger Judge tier specifically for side-effects.
