"""LifeOS Streamlit app — main entry point.

Run locally:  streamlit run app.py
Deploy:       push to GitHub, then connect repo on streamlit.io.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import streamlit as st

from lifeos.config import DATA_DIR, AGENT_MODEL, JUDGE_MODEL
from lifeos.llm import LLMClient, LLMError
from lifeos.orchestrator import Orchestrator


st.set_page_config(
    page_title="LifeOS — Multi-Agent Personal Optimization",
    page_icon="🧠",
    layout="wide",
)


# ---------------- secrets / api key resolution ----------------
def resolve_api_key() -> str | None:
    key = os.getenv("GEMINI_API_KEY")
    if key and key != "PASTE_YOUR_KEY_HERE":
        return key
    try:
        secret = st.secrets.get("GEMINI_API_KEY")
        if secret:
            return secret
    except Exception:
        pass
    return st.session_state.get("user_api_key")


# ---------------- CV parsing ----------------
def parse_cv_upload(uploaded) -> str:
    """Return plain text from an uploaded PDF or TXT."""
    if uploaded is None:
        return ""
    name = uploaded.name.lower()
    data = uploaded.read()
    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader  # type: ignore
        except ImportError:
            return "(pypdf not installed — pip install pypdf)"
        try:
            reader = PdfReader(io.BytesIO(data))
            return "\n".join((page.extract_text() or "") for page in reader.pages).strip()
        except Exception as e:
            return f"(PDF parse error: {e})"
    # txt / md / anything else — decode
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(enc).strip()
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace").strip()


def format_mood(sleep_h: float, energy: int, stress: str) -> str:
    return f"Slept {sleep_h:.1f}h, energy {energy}/10, stress {stress}."


# ---------------- sidebar ----------------
st.sidebar.title("🧠 LifeOS")
st.sidebar.caption("Multi-agent personal optimization with a governance layer.")

with st.sidebar.expander("ℹ️ About this system", expanded=False):
    st.markdown(
        f"""
**Agents** ({AGENT_MODEL})
- **Career & Internship** → real job search + English overview + learning task
- **Schedule** → time-blocked daily plan
- **Productivity** → focus rule + top priority + score

**Judge** ({JUDGE_MODEL}, deliberately a stronger tier than the agents)
1. Deterministic contract validator
2. LLM consistency checker

Each agent's output passes through the Judge.

**Job sources**: Arbeitnow, Remotive, RemoteOK, ejobs.ro (Romania), Adzuna (with key), LinkedIn (Apify, with token).
"""
    )

key_present = (
    os.getenv("GEMINI_API_KEY")
    and os.getenv("GEMINI_API_KEY") != "PASTE_YOUR_KEY_HERE"
)
if not key_present:
    st.sidebar.warning("Gemini API key not found in env.")
    st.sidebar.text_input(
        "Paste API key (kept in browser session only)",
        type="password",
        key="user_api_key",
    )


# ---------------- persona loading ----------------
PERSONAS_PATH = DATA_DIR / "personas.json"
PERSONAS: dict = {}
if PERSONAS_PATH.exists():
    with PERSONAS_PATH.open(encoding="utf-8") as f:
        PERSONAS = json.load(f)


def load_persona(key: str) -> dict[str, str]:
    p = PERSONAS.get(key, {})
    cv = p.get("cv_inline", "")
    if not cv and p.get("cv_file"):
        cv_path = DATA_DIR / p["cv_file"]
        cv = cv_path.read_text(encoding="utf-8") if cv_path.exists() else ""
    events = ""
    if p.get("events_file"):
        ep = DATA_DIR / p["events_file"]
        events = ep.read_text(encoding="utf-8") if ep.exists() else ""
    return {
        "cv": cv,
        "goal": p.get("goal", ""),
        "events": events,
        "mood": p.get("mood", ""),
        "notes": p.get("notes", ""),
        "expected_judge": p.get("expected_judge", ""),
    }


# ---------------- main ----------------
st.title("LifeOS")
st.caption(
    "Multi-agent personal optimization. Real job search + day planning + productivity briefing, "
    "with a Judge layer that verifies and gates every agent output."
)

tab_run, tab_trace, tab_judge, tab_logs, tab_arch = st.tabs(
    ["▶ Run", "🔗 Agent Trace", "⚖ Judge", "📜 Logs", "🏗 Architecture"]
)


# ---- Run tab ----
with tab_run:
    col_left, col_right = st.columns([5, 7], gap="large")

    with col_left:
        st.subheader("Inputs")
        persona_key = st.selectbox(
            "Demo persona",
            options=["custom"] + list(PERSONAS.keys()),
            format_func=lambda k: "✏ Type my own"
            if k == "custom"
            else PERSONAS.get(k, {}).get("label", k),
        )

        if persona_key != "custom":
            p = load_persona(persona_key)
            if p["notes"]:
                st.info(p["notes"])

        # CV — file uploader OR textarea
        st.markdown("**Your CV**")
        cv_file = st.file_uploader(
            "Upload PDF or .txt (overrides the textarea below)",
            type=["pdf", "txt", "md"],
            label_visibility="visible",
        )
        cv_from_file = parse_cv_upload(cv_file) if cv_file else ""
        cv_default = cv_from_file or (load_persona(persona_key)["cv"] if persona_key != "custom" else "")
        cv = st.text_area("Or paste CV text here", value=cv_default, height=180, label_visibility="collapsed")

        goal_default = load_persona(persona_key)["goal"] if persona_key != "custom" else ""
        goal = st.text_input(
            "Career goal (one sentence)",
            value=goal_default,
            placeholder="e.g. Backend engineering internship at a fintech, Bucharest or EU remote",
        )

        events_default = load_persona(persona_key)["events"] if persona_key != "custom" else ""
        events = st.text_area(
            "Today's fixed events (one per line)",
            value=events_default,
            height=110,
            placeholder="09:00 - 10:30  Lecture\n13:00 - 14:00  Lunch with X",
        )

        st.markdown("**How you feel today**")
        c1, c2, c3 = st.columns(3)
        sleep_h = c1.number_input("Sleep (hours)", min_value=0.0, max_value=14.0, value=7.0, step=0.5)
        energy = c2.slider("Energy /10", min_value=1, max_value=10, value=6)
        stress = c3.selectbox("Stress", options=["low", "medium", "high"], index=1)

        run_clicked = st.button("▶ Run LifeOS", type="primary", use_container_width=True)

    with col_right:
        st.subheader("Result")
        if run_clicked:
            api_key = resolve_api_key()
            if not api_key:
                st.error(
                    "No API key available. Paste one in the sidebar or set GEMINI_API_KEY in your .env file."
                )
            elif not cv.strip():
                st.error("Please upload a CV or paste CV text before running.")
            else:
                try:
                    llm = LLMClient(api_key=api_key)
                    orch = Orchestrator(llm=llm)
                    mood = format_mood(sleep_h, energy, stress)
                    with st.spinner(
                        "Searching jobs · Career Agent · Judge · Schedule Agent · Judge · Productivity Agent · Judge..."
                    ):
                        result = orch.run(cv=cv, goal=goal, events=events, mood=mood)
                    st.session_state["last_result"] = result.to_dict()
                except LLMError as e:
                    st.error(str(e))
                except Exception as e:
                    st.exception(e)

        last = st.session_state.get("last_result")
        if last:
            badge = "✅" if last["accepted"] else "🛑"
            st.markdown(f"#### {badge} Run `{last['run_id']}` — accepted={last['accepted']}")
            if last.get("halted_reason"):
                st.error(last["halted_reason"])

            fp = last.get("final_plan") or {}

            # --- Career card ---
            ct = fp.get("career_task") or {}
            all_jobs = last.get("all_jobs") or []
            picked_idx = ct.get("selected_job_index", 0)
            with st.container(border=True):
                st.markdown("##### 🎯 Job match")
                sj = ct.get("selected_job")
                if sj and picked_idx != 0:
                    st.markdown(f"**{sj.get('title','')}**  · _{sj.get('company','')}_")
                    st.caption(
                        f"📍 {sj.get('location','')}  ·  "
                        f"source: `{sj.get('source','')}`  ·  "
                        f"confidence: **{ct.get('confidence','?')}**"
                    )
                    st.write(ct.get("job_summary_english", ""))
                    if sj.get("url"):
                        st.markdown(f"🔗 [Open the listing →]({sj['url']})")
                else:
                    st.warning(
                        ct.get("job_summary_english")
                        or "No suitable match in the current listings."
                    )
                st.divider()
                st.markdown(
                    f"**Today's learning task:** {ct.get('task','—')}  \n"
                    f"_~{ct.get('estimated_minutes','?')} min · "
                    f"confidence: {ct.get('confidence','?')}_"
                )
                # Other candidates the aggregator surfaced but the agent did not pick.
                other_jobs = [
                    j for i, j in enumerate(all_jobs, start=1) if i != picked_idx
                ]
                if other_jobs:
                    with st.expander(
                        f"📋 {len(other_jobs)} other matches the system considered"
                    ):
                        for j in other_jobs:
                            cols = st.columns([6, 2])
                            with cols[0]:
                                st.markdown(
                                    f"**{j.get('title','')}** · _{j.get('company','')}_"
                                )
                                st.caption(
                                    f"📍 {j.get('location','')[:40]}  ·  "
                                    f"source: `{j.get('source','')}`  ·  "
                                    f"score: {j.get('score',0):.2f}"
                                )
                            with cols[1]:
                                if j.get("url"):
                                    st.markdown(
                                        f"[Open →]({j['url']})",
                                        help="Opens the original listing in a new tab",
                                    )
                            st.divider()

            # --- Schedule card ---
            sched = fp.get("schedule") or {}
            blocks = sched.get("blocks", [])
            if blocks:
                with st.container(border=True):
                    st.markdown("##### 📅 Today's plan")
                    st.dataframe(
                        blocks,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "start": "Start",
                            "end": "End",
                            "activity": "Activity",
                            "category": "Category",
                        },
                    )
                    with st.expander("Schedule reasoning"):
                        st.write(sched.get("reasoning", ""))

            # --- Productivity card ---
            prod = fp.get("productivity") or {}
            if prod:
                with st.container(border=True):
                    st.markdown("##### ⚡ Productivity briefing")
                    p1, p2, p3 = st.columns(3)
                    p1.metric("Productivity", f"{prod.get('productivity_score','?')}/10")
                    p2.metric("Procrastination risk", str(prod.get("procrastination_risk", "?")).upper())
                    p3.metric("Confidence", str(prod.get("confidence", "?")))
                    st.markdown(f"**Focus rule today:** {prod.get('focus_rule_today','—')}")
                    st.markdown(f"**Top priority block:** {prod.get('top_priority_block','—')}")
                    with st.expander("Rationale"):
                        st.write(prod.get("rationale", ""))


# ---- Agent Trace tab ----
with tab_trace:
    last = st.session_state.get("last_result")
    if not last:
        st.info("Run something first.")
    else:
        for stage in last["stages"]:
            verdict = stage["verdict"]
            badge = {"accept": "🟢", "revise": "🟡", "reject": "🔴"}.get(verdict["label"], "⚪")
            st.markdown(f"### {badge} {stage['agent_name']}  —  verdict: **{verdict['label']}**")
            st.caption(f"latency: {stage['latency_ms']} ms")
            with st.expander("Agent output (raw JSON)"):
                st.json(stage["output"])
            with st.expander("Judge verdict"):
                st.json(verdict)


# ---- Judge tab ----
with tab_judge:
    st.markdown(
        """
### How the Judge works

Every agent output passes through a **two-layer governance check**:

1. **Deterministic contract validator** (no LLM)
   - Required fields present?
   - Types and enums correct?
   - Schedule blocks: no overlap, end > start, total ≤ 16h?
   - Forbidden phrases absent?
   - If this fails → immediate **reject** (no Judge-tier API call spent).

2. **LLM consistency checker** (different model tier than the agents)
   - Does the output fabricate facts not in the input?
   - Does it contradict the input?
   - Is it overconfident?
   - Returns a `consistency_score` in [0, 1].

| score          | label   |
|----------------|---------|
| ≥ 0.7          | accept  |
| 0.4 – 0.7      | revise  |
| < 0.4 or contract fail | reject |
"""
    )
    last = st.session_state.get("last_result")
    if last:
        for stage in last["stages"]:
            v = stage["verdict"]
            st.divider()
            st.markdown(f"#### {stage['agent_name']} — `{v['label']}`")
            cols = st.columns(3)
            cols[0].metric("Contract", "passed" if v["contract_passed"] else "failed")
            cols[1].metric("Consistency", f"{v['consistency_score']:.2f}")
            cols[2].metric("Latency", f"{stage['latency_ms']} ms")
            if v["contract_issues"]:
                st.error("Contract issues: " + "; ".join(v["contract_issues"][:5]))
            if v["consistency_issues"]:
                st.warning("Consistency issues: " + "; ".join(v["consistency_issues"][:5]))
            if v["consistency_reasoning"]:
                with st.expander("Judge reasoning"):
                    st.write(v["consistency_reasoning"])


# ---- Logs tab ----
with tab_logs:
    log_dir = Path("logs")
    if not log_dir.exists():
        st.info("No logs directory yet.")
    else:
        files = sorted(log_dir.glob("run_*.jsonl"), reverse=True)
        if not files:
            st.info("No runs logged yet.")
        else:
            picked = st.selectbox(
                "Select a run", files, format_func=lambda p: p.name
            )
            if picked:
                lines = picked.read_text(encoding="utf-8").splitlines()
                for line in lines:
                    try:
                        entry = json.loads(line)
                        st.code(
                            json.dumps(entry, indent=2, ensure_ascii=False),
                            language="json",
                        )
                    except json.JSONDecodeError:
                        st.text(line)


# ---- Architecture tab ----
with tab_arch:
    st.markdown(
        f"""
### LifeOS architecture

```
        ┌──────────────────────────────────────────────────┐
        │                  Streamlit UI                    │
        │  inputs: CV (file/text), goal, events, sleep,    │
        │          energy, stress                          │
        └────────────────────────┬─────────────────────────┘
                                 │
                                 ▼
        ┌──────────────────────────────────────────────────┐
        │                 Orchestrator                     │
        │   Python · sequential · JSON-logged              │
        └──┬───────────┬─────────────────────────────┬─────┘
           │           │                             │
           ▼           ▼                             ▼
   ┌─────────────┐ ┌─────────────────┐    ┌──────────────────┐
   │ Job sources │ │ Career Agent    │    │ Schedule Agent   │
   │ Arbeitnow   │ │ ({AGENT_MODEL}) │───►│ ({AGENT_MODEL})  │
   │ Remotive    │ │ index + EN      │    │ time-blocked     │
   │ RemoteOK    │ │ overview + task │    │ day plan         │
   │ ejobs.ro    │ └────────┬────────┘    └────────┬─────────┘
   │ Adzuna(key) │          │                      │
   │ LinkedIn    │          │                      ▼
   │  (Apify)    │          │             ┌──────────────────┐
   └─────────────┘          │             │ Productivity     │
                            │             │ Agent            │
                            │             │ ({AGENT_MODEL})  │
                            │             │ focus + score    │
                            │             └────────┬─────────┘
                            │                      │
                            ▼                      ▼
        ┌──────────────────────────────────────────────────┐
        │              Judge ({JUDGE_MODEL})               │
        │  Contract Validator  +  Consistency Checker      │
        │  per-output verdict: accept / revise / reject    │
        └────────────────────────┬─────────────────────────┘
                                 ▼
                          logs/run_*.jsonl
```

**Design choices**
- **3 collaborating agents** (Career → Schedule → Productivity), not parallel silos. Each agent's output feeds the next.
- **Judge runs a different model tier** — same-model self-grading is a known weakness in LLM-as-judge research.
- **Two-layer Judge**: cheap deterministic check first (catches structural errors free), LLM consistency check only when contract passes.
- **Agentic contracts as YAML** — agent behaviour is declared in config, not hardcoded prompts. Easy to inspect.
- **Index-based job selection** prevents the Career Agent from fabricating a job that isn't in the live listings.
- **Career Agent stops at "here is a job link"** — no auto-application, no contact. Human-in-the-loop by design.
- **Free job APIs** — no paid integrations or scraping middlemen required; LinkedIn + ejobs.ro are optional add-ons.
"""
    )
