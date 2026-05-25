"""Job search aggregator. Hits multiple free job-board APIs in parallel
and returns a normalised, ranked list. No LLM in this module — pure data.

Sources (priority order, as requested by user):
1. Bucharest local      -> Adzuna (Romania filter, needs free key) + Arbeitnow
2. Remote in Europe     -> Arbeitnow (EU + remote tag) + Remotive (EU filter)
3. Remote anywhere      -> Remotive + RemoteOK
"""
from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import urllib.request


# ---------------- data model ----------------

@dataclass
class Job:
    title: str
    company: str
    location: str
    remote: bool
    url: str
    source: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    posted_at: str | None = None
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "remote": self.remote,
            "url": self.url,
            "source": self.source,
            "description": (self.description or "")[:600],
            "tags": self.tags[:10],
            "posted_at": self.posted_at,
            "score": round(self.score, 2),
        }


# ---------------- helpers ----------------

def _http_get_json(url: str, timeout: int = 10) -> dict | list | None:
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "LifeOS/0.1 (educational project)"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            import json as _json
            return _json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return None


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", " ", s or "").strip()


# ---------------- source adapters ----------------

def _fetch_arbeitnow(query: str) -> list[Job]:
    """Public API, no auth. Covers EU + remote."""
    data = _http_get_json("https://www.arbeitnow.com/api/job-board-api")
    if not data or "data" not in data:
        return []
    out: list[Job] = []
    for j in data["data"][:60]:
        tags = j.get("tags") or []
        out.append(
            Job(
                title=j.get("title", ""),
                company=j.get("company_name", ""),
                location=j.get("location", "") or "EU",
                remote=bool(j.get("remote")),
                url=j.get("url", ""),
                source="arbeitnow",
                description=_strip_html(j.get("description", "")),
                tags=[str(t) for t in tags],
                posted_at=str(j.get("created_at") or ""),
            )
        )
    return out


def _fetch_remotive(query: str) -> list[Job]:
    """Public API, no auth. Remote jobs."""
    url = "https://remotive.com/api/remote-jobs?" + urlencode({"limit": 50, "search": query})
    data = _http_get_json(url)
    if not data or "jobs" not in data:
        return []
    out: list[Job] = []
    for j in data["jobs"]:
        out.append(
            Job(
                title=j.get("title", ""),
                company=j.get("company_name", ""),
                location=j.get("candidate_required_location", "Remote"),
                remote=True,
                url=j.get("url", ""),
                source="remotive",
                description=_strip_html(j.get("description", ""))[:1500],
                tags=j.get("tags") or [],
                posted_at=j.get("publication_date"),
            )
        )
    return out


def _fetch_remoteok(query: str) -> list[Job]:
    """Public-ish API. Returns a list whose first item is metadata."""
    data = _http_get_json("https://remoteok.com/api")
    if not isinstance(data, list):
        return []
    out: list[Job] = []
    for j in data[1:80]:  # skip the first metadata element
        if not isinstance(j, dict):
            continue
        title = j.get("position") or j.get("title", "")
        out.append(
            Job(
                title=title,
                company=j.get("company", ""),
                location=j.get("location", "Remote") or "Remote",
                remote=True,
                url=j.get("url") or j.get("apply_url", ""),
                source="remoteok",
                description=_strip_html(j.get("description", ""))[:1500],
                tags=j.get("tags") or [],
                posted_at=j.get("date"),
            )
        )
    return out


def _fetch_ejobs_ro(query: str) -> list[Job]:
    """Direct scrape of ejobs.ro (Romania's largest job board).

    ejobs.ro is a Vue SPA — only the first ~3 cards are server-rendered.
    This is a known limitation; static scraping cannot get the lazy-loaded
    rest without a headless browser. We take what's available.
    """
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except ImportError:
        return []

    # Pick a category slug based on the user's query.
    slug = "internship" if "intern" in query.lower() else "programare"
    url = f"https://www.ejobs.ro/locuri-de-munca/{slug}"
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en,ro;q=0.9"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return []

    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.job-card")
    out: list[Job] = []
    for card in cards:
        title_el = card.select_one("h2.job-card-content-middle__title")
        title = title_el.get_text(strip=True) if title_el else ""
        company_el = card.select_one("h3.job-card-content-middle__info--darker, .job-card-content-middle__info--darker")
        company = company_el.get_text(strip=True) if company_el else ""
        # Location = the non-darker info div
        location = "Romania"
        for info in card.select("div.job-card-content-middle__info"):
            classes = info.get("class") or []
            if "job-card-content-middle__info--darker" not in classes:
                location = info.get_text(strip=True) or "Romania"
                break
        salary_el = card.select_one(".job-card-content-middle__salary")
        salary = salary_el.get_text(strip=True) if salary_el else ""
        url_el = card.select_one("a.job-card-content__logo, a[class*='logo']")
        href = url_el.get("href") if url_el else ""
        if href and not href.startswith("http"):
            href = "https://www.ejobs.ro" + href

        if not title:
            continue
        out.append(
            Job(
                title=title,
                company=company,
                location=location,
                remote="remote" in location.lower() or "remote" in title.lower(),
                url=href or url,
                source="ejobs.ro",
                description=salary,  # use salary as the short description
                tags=[],
            )
        )
    return out


def _fetch_linkedin_apify(query: str) -> list[Job]:
    """LinkedIn jobs via Apify (token-gated, with short timeout for demo).

    Requires APIFY_TOKEN in env. If not set, returns [] silently.
    Uses a sync API endpoint with a 25-second timeout — if Apify is slow,
    the rest of the pipeline still proceeds with the other sources.
    """
    token = os.getenv("APIFY_TOKEN")
    if not token:
        return []

    actor = os.getenv("APIFY_LINKEDIN_ACTOR", "bebity~linkedin-jobs-scraper")
    # Apify uses ~ separator in URL paths
    actor_path = actor.replace("/", "~")

    import json as _json
    payload = _json.dumps({
        "keywords": query,
        "location": "Bucharest, Romania",
        "rows": 15,
        "proxy": {"useApifyProxy": True},
    }).encode("utf-8")

    url = (
        f"https://api.apify.com/v2/acts/{actor_path}/"
        f"run-sync-get-dataset-items?token={token}&timeout=25"
    )
    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "LifeOS/0.1"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = _json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return []

    if not isinstance(data, list):
        return []
    out: list[Job] = []
    for j in data:
        if not isinstance(j, dict):
            continue
        title = j.get("title") or j.get("position") or ""
        company = j.get("companyName") or j.get("company") or ""
        location = j.get("location") or "LinkedIn"
        url_v = j.get("link") or j.get("url") or ""
        if not title:
            continue
        out.append(
            Job(
                title=title,
                company=company,
                location=location,
                remote="remote" in location.lower(),
                url=url_v,
                source="linkedin",
                description=_strip_html((j.get("description") or "")[:600]),
                tags=[],
                posted_at=j.get("postedAt") or j.get("postedTime"),
            )
        )
    return out


def _fetch_adzuna(query: str, country: str = "gb") -> list[Job]:
    """Adzuna — needs free API key. Best for country-specific search (Romania = 'ro')."""
    app_id = os.getenv("ADZUNA_APP_ID")
    app_key = os.getenv("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        return []
    params = {
        "app_id": app_id,
        "app_key": app_key,
        "results_per_page": 30,
        "what": query,
        "content-type": "application/json",
    }
    url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1?" + urlencode(params)
    data = _http_get_json(url)
    if not data or "results" not in data:
        return []
    out: list[Job] = []
    for j in data["results"]:
        loc = (j.get("location") or {}).get("display_name", "")
        out.append(
            Job(
                title=j.get("title", ""),
                company=(j.get("company") or {}).get("display_name", ""),
                location=loc,
                remote="remote" in (j.get("description") or "").lower(),
                url=j.get("redirect_url", ""),
                source=f"adzuna-{country}",
                description=_strip_html(j.get("description", "")),
                posted_at=j.get("created"),
            )
        )
    return out


# ---------------- scoring + ranking ----------------

_TECH_KEYWORDS = re.compile(
    r"\b("
    r"python|django|flask|fastapi|java|spring|node|node\.js|typescript|react|vue|angular|"
    r"sql|postgres|mysql|mongodb|redis|kafka|aws|gcp|azure|docker|kubernetes|terraform|"
    r"linux|git|rest|graphql|microservices|backend|frontend|fullstack|fintech|"
    r"machine learning|ml|llm|nlp|data engineer|data analyst|data scientist|software engineer|swe|devops|sre|"
    r"power bi|tableau|etl|bi developer|business intelligence|"
    r"intern|internship|junior|graduate|trainee"
    r")\b",
    re.IGNORECASE,
)

# Stricter gate — must contain at least one ACTUAL tech token, not just a seniority word.
_TECH_RELEVANCE = re.compile(
    r"\b("
    r"python|django|flask|fastapi|java|spring|node|node\.js|typescript|javascript|react|vue|angular|"
    r"sql|postgres|mysql|mongodb|redis|kafka|aws|gcp|azure|docker|kubernetes|terraform|"
    r"linux|git|rest|graphql|microservices|backend|frontend|fullstack|fintech|api|"
    r"machine learning|ml engineer|llm|nlp|data engineer|data analyst|data scientist|software engineer|swe|"
    r"devops|sre|developer|engineer|programmer|"
    r"power bi|tableau|etl|bi|business intelligence|analyst|analytics"
    r")\b",
    re.IGNORECASE,
)


def _keyword_set(text: str) -> set[str]:
    return {m.group(0).lower() for m in _TECH_KEYWORDS.finditer(text or "")}


def _score(job: Job, cv_keywords: set[str], goal_keywords: set[str], location_pref: str) -> float:
    job_text = f"{job.title} {job.description} {' '.join(job.tags)}"
    job_keys = _keyword_set(job_text)

    skill_overlap = len(job_keys & cv_keywords) / max(1, len(cv_keywords) | 1)
    goal_overlap = len(job_keys & goal_keywords) / max(1, len(goal_keywords) | 1)

    # location bonus
    loc_bonus = 0.0
    loc_low = (job.location or "").lower()
    if location_pref == "bucharest":
        if "bucharest" in loc_low or "bucuresti" in loc_low or "romania" in loc_low:
            loc_bonus = 0.5
        elif job.remote:
            loc_bonus = 0.25
    elif location_pref == "europe_remote":
        if job.remote and any(eu in loc_low for eu in ["europe", "eu", "emea", "remote"]):
            loc_bonus = 0.4
        elif job.remote:
            loc_bonus = 0.2
    elif location_pref == "remote":
        if job.remote:
            loc_bonus = 0.3

    # internship/junior bonus (note: "entry" alone is excluded because "Data Entry" matches it)
    junior_bonus = 0.0
    if re.search(r"\b(intern|internship|junior|graduate|trainee|entry.level)\b", job.title, re.I):
        junior_bonus = 0.6
    # senior/staff/principal penalty — we are looking for junior roles
    senior_penalty = 0.0
    if re.search(r"\b(senior|staff|principal|lead|head|director|manager|vp)\b", job.title, re.I):
        senior_penalty = 0.8

    # tech-relevance gate: TITLE must contain a tech token (description is too noisy)
    if not _TECH_RELEVANCE.search(job.title):
        return -1.0  # filter it out

    return skill_overlap * 1.0 + goal_overlap * 0.8 + loc_bonus + junior_bonus - senior_penalty


# ---------------- public entry point ----------------

def search_jobs(
    cv_text: str,
    goal_text: str,
    max_results: int = 8,
) -> list[dict[str, Any]]:
    """Hit all sources in parallel, dedupe, rank, return the top N as dicts.

    The location preference is hardcoded to the user's stated order:
    Bucharest -> Europe remote -> Remote anywhere.
    Ranking blends location preference with CV/goal keyword overlap.
    """
    cv_kw = _keyword_set(cv_text)
    goal_kw = _keyword_set(goal_text)

    # Build a query that reflects the GOAL, not a hardcoded "intern".
    # We extract domain keywords from the goal text and use the strongest
    # signal as the query — different sources will dedupe their own results.
    goal_low = (goal_text or "").lower()
    domain_terms = [
        ("data analyst", ["data analyst", "data analysis", "data science", "data scientist"]),
        ("data engineer", ["data engineer", "data engineering", "etl"]),
        ("bi", ["bi developer", "business intelligence", "bi analyst", " bi "]),
        ("backend", ["backend", "back end", "back-end", "fastapi", "django"]),
        ("frontend", ["frontend", "front end", "front-end", "react", "vue"]),
        ("devops", ["devops", "sre", "kubernetes", "infrastructure"]),
        ("machine learning", ["machine learning", " ml ", "ml engineer", "llm"]),
        ("python", ["python developer", "python engineer"]),
        ("software", ["software", "developer", "engineer"]),
    ]
    query = "software"  # safe default
    for term, signals in domain_terms:
        if any(s in goal_low for s in signals) or any(s in (cv_text or "").lower() for s in signals):
            query = term
            break
    # Junior bias — if goal/cv mentions intern/junior, narrow it
    if "intern" in goal_low or "intern" in (cv_text or "").lower():
        query = f"{query} intern"
    elif "junior" in goal_low:
        query = f"{query} junior"

    sources = [
        ("arbeitnow", lambda: _fetch_arbeitnow(query)),
        ("remotive", lambda: _fetch_remotive(query)),
        ("remoteok", lambda: _fetch_remoteok(query)),
        ("ejobs.ro", lambda: _fetch_ejobs_ro(query)),
        ("adzuna-ro", lambda: _fetch_adzuna(query, country="ro")),
        ("adzuna-gb", lambda: _fetch_adzuna(query, country="gb")),
        ("linkedin", lambda: _fetch_linkedin_apify(query)),
    ]

    all_jobs: list[Job] = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(fn): name for name, fn in sources}
        for fut in as_completed(futures):
            try:
                all_jobs.extend(fut.result() or [])
            except Exception:
                pass

    # dedupe by company + normalised title prefix (strip trailing " - <city>" patterns)
    seen: set[tuple[str, str]] = set()
    unique: list[Job] = []
    for j in all_jobs:
        # cut off everything after the first " - " or " | " or " @ " (usually location)
        t = re.split(r" [-|@] ", j.title, maxsplit=1)[0]
        title_key = re.sub(r"\W+", " ", t.lower()).strip()[:30]
        key = (j.company.lower().strip(), title_key)
        if key in seen or not j.title:
            continue
        seen.add(key)
        unique.append(j)

    # score against all three location preferences and pick the best score
    for j in unique:
        score_buc = _score(j, cv_kw, goal_kw, "bucharest")
        score_eu = _score(j, cv_kw, goal_kw, "europe_remote") * 0.85
        score_rem = _score(j, cv_kw, goal_kw, "remote") * 0.7
        j.score = max(score_buc, score_eu, score_rem)

    # filter out negative-scored (non-tech / irrelevant) and sort
    unique = [j for j in unique if j.score >= 0]
    unique.sort(key=lambda x: x.score, reverse=True)
    return [j.to_dict() for j in unique[:max_results]]
