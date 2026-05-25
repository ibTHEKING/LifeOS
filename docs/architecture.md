# LifeOS — Architecture & Design Notes

This document is what you hand the professor / committee. It explains _why_ the system looks the way it does.

## 1. Problem framing

The course asked for a multi-agent AI personal optimization system. Most student projects in this space fail in one of two ways:

1. **Many shallow agents.** Each "agent" is a single LLM prompt with no real contract. They never reject anything. They routinely hallucinate. The "system" is a thin wrapper around N API calls.
2. **One monolith with a multi-agent label.** A single prompt pretending to be a system.

LifeOS deliberately avoids both by:

- **Limiting to 3 agents** that produce different artefacts and genuinely depend on each other (Career → Schedule → Productivity).
- **Treating governance as a first-class component**, not an afterthought.
- **Making hallucination structurally impossible** where possible (e.g. the Career Agent picks a job by integer index, not by re-typing the title).

## 2. Component overview

| Component | File | Role |
|---|---|---|
| Job aggregator | `lifeos/jobs.py` | Pure data. Hits Arbeitnow, Remotive, RemoteOK, ejobs.ro, Adzuna (key), LinkedIn (Apify token). Dedupes + ranks. |
| Career Agent | `lifeos/agents/career.py` | CV + goal + jobs → INDEX of one job, English overview, learning task |
| Schedule Agent | `lifeos/agents/schedule.py` | Events + mood + Career task → time-blocked plan |
| Productivity Agent | `lifeos/agents/productivity.py` | Plan + mood → focus rule, top priority block, score 1-10 |
| Contract Validator | `lifeos/judge/contract_validator.py` | Deterministic schema + rule checks |
| Consistency Checker | `lifeos/judge/consistency_checker.py` | LLM-based grounding/fabrication check (compact input view) |
| Judge | `lifeos/judge/judge.py` | Combines the two checks into accept/revise/reject |
| Orchestrator | `lifeos/orchestrator.py` | Runs the pipeline, handles handoff, halts on rejection |
| Logger | `lifeos/logger.py` | Append-only JSONL trace per run |
| UI | `app.py` | Streamlit — inputs, results, trace, judge tab, logs |

## 3. The "index-based selection" trick

A key architectural choice in the Career Agent: the agent does NOT return job titles, companies, or URLs. It returns an INTEGER — the index of its choice in the candidate list. The orchestrator then fills in the verbatim job details from the original listing.

This makes hallucination of job titles or companies **structurally impossible**. The agent can still:
- Pick the wrong index (caught by the Judge's seniority check)
- Pick an out-of-range index (deterministically rejected)
- Write a bad English overview (caught by the Judge's consistency check)

But it cannot invent a job. That class of error is removed by design, not by prompting.

A similar move in the Productivity Agent: it receives schedule blocks **without their times** (only `[category] activity`). It cannot fabricate a "10:30-12:30 block" because it never saw 10:30 in the first place. Times are reconstructed from the schedule's verbatim output when displayed in the UI.

## 4. Agentic contracts

Each agent operates under a contract written as YAML (see `contracts/`). A contract declares:

- **output_schema** — types, required fields, enums, regex patterns, max lengths
- **forbidden_phrases** — phrases the agent must not use (e.g. "guaranteed", "as a certified")
- **truthfulness_rules** — natural-language rules the Judge enforces ("never fabricate companies not present in the CV")
- **escalation_rules** — context-dependent behaviour ("if user mood indicates burnout, reduce deep_work time and lower confidence")

Contracts are loaded at runtime; the Judge prompt embeds a summary of the contract when evaluating output. Changing agent behaviour is a config edit, not a code change.

## 5. The Judge — two layers, in order

### Layer 1 — Deterministic contract validator (no LLM)

Runs first because it is free, instant, and catches the structural errors LLMs are bad at noticing in their own output:

- Required fields present? Types and enum values correct?
- String patterns (e.g. `HH:MM`) match regex?
- Schedule-specific domain checks: no overlaps, end > start, total ≤ 16h?
- Forbidden phrases absent?

If this layer fails, the Judge returns **reject** immediately. No Judge-tier API call is made.

### Layer 2 — LLM consistency checker

Runs only when layer 1 passes. Sends the agent's input, the agent's output, and a summary of the agent's contract to **Gemini 3.5 Flash** (deliberately a different model tier from the agents).

The input is reformatted to a **compact view** before being sent to the Judge — full job list as `(index, title, company, location)` tuples rather than full descriptions. This was a real bug we hit during development: a 6000-char truncation made the Judge miscount the jobs list and reject valid agent picks. See `consistency_checker._compact_input`.

The Judge prompt asks:
- Does the output cite facts not present in the input?
- Does it contradict the input?
- Is it overconfident given the available evidence?
- Are the contract's truthfulness rules honoured?

Returns a `consistency_score` in [0, 1].

### Decision rule

```
contract failed                 -> reject
contract passed, score >= 0.70  -> accept
contract passed, 0.40 <= s<0.70 -> revise (accept but flag)
contract passed, score < 0.40   -> reject
```

The thresholds are visible in `lifeos/judge/judge.py` and tunable in one place.

## 6. Why a *different* model for the Judge

Same-model self-grading ("ask GPT-4 to evaluate GPT-4's output") is a known weakness in the LLM-as-judge literature — the judge model shares the agent model's blind spots and biases.

LifeOS uses **Gemini 3.1 Flash-Lite** for all three agents and **Gemini 3.5 Flash** for the Judge. Different model families would be even better (e.g. GPT-4 judging Gemini), and the architecture supports that — `lifeos/llm.py` would gain a second provider. The free-tier constraint kept us within one family for this iteration.

## 7. Human-in-the-loop, by design

The system does not:
- Apply to jobs
- Contact employers
- Write to the user's calendar
- Send messages

It produces text. The user clicks through to the original job listing themselves and decides. This is a deliberate scope choice consistent with the project's stated philosophy:

> LifeOS does NOT attempt to create AGI or fully autonomous uncontrollable agents.

Adding action-taking is a future scope decision that would also require adding a stronger Judge tier (e.g. a separate approval step on side-effects).

## 8. Failure modes & what we did about them

| Failure mode | Mitigation |
|---|---|
| Career Agent invents a job not in listings | Index-based selection — structurally impossible. |
| Career Agent picks a senior role for an intern CV | Explicit seniority-matching rules in the prompt; Judge catches mismatches anyway. |
| Schedule Agent invents events | Schedule contract: "Never invent fixed events the user did not list." Judge consistency check verifies. |
| Productivity Agent fabricates clock times | Time references removed from input. The agent literally cannot see "10:30" so cannot quote it. Forbidden_patterns regex backup. |
| Agent produces malformed JSON | LLM client uses `response_mime_type=application/json`. Validator reports `_parse_error`. Judge rejects. |
| Schedule blocks overlap | Domain check in `ContractValidator._domain_checks`. |
| Judge biased by sharing model with agent | Different model tier. |
| Judge spends quota on already-broken outputs | Layer-1 deterministic check gates layer-2 LLM call. |
| Free-tier rate limit hit | Sequential (not parallel) agent execution; LLM client has retry-with-fallback to weaker models on 503/429. |
| Judge miscounts jobs due to input truncation | Compact-view input formatting preserves the full job list at low token cost. |

## 9. What's intentionally *not* in v1

- No memory across sessions. Each run is independent.
- No vector database. Not needed at this scale.
- No tool use by agents. They take text in, return JSON.
- No automated retries on `revise`. The system accepts revise outputs but flags them. Adding a retry loop is straightforward but eats free-tier quota; left for v2.
- Action-taking (calendar writes, applications, emails). Strictly text-only.

## 10. Evaluation plan

The system logs every run (`logs/run_*.jsonl`). For a quantitative section in the report:

1. Run each persona in `data/personas.json` 10 times.
2. For each persona, count Judge verdict distribution (accept / revise / reject) across the three agents.
3. The `empty_cv_should_trigger_rejection` persona expects ≥ 50% non-accept verdicts on the Career Agent.
4. Compare the median consistency score for normal vs adversarial personas. A working Judge should show a meaningful gap.

These numbers go directly into the report.

## 11. What would change in v2

- Add the remaining agents from the original brief: Energy, Anti-Doomscrolling, Trading-Education
- Real Google Calendar / Gmail OAuth instead of pasted events
- Telegram delivery via n8n (see `docs/n8n_integration.md`)
- Cross-provider Judge (e.g. Claude judging Gemini)
- Per-user persistent memory with provenance
