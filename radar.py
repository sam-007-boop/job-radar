#!/usr/bin/env python3
"""job-radar: find finance roles posted today or yesterday (US Eastern) at Sam's target companies.

Reads watchlist.yaml, pulls each company's public job feed (Greenhouse, Lever, Ashby, Workday),
keeps roles that are (1) posted today/yesterday, (2) finance-relevant by title, (3) US-based,
and writes:
  data/fresh.json        today's fresh roles (what the morning Claude task reads)
  data/fresh.md          the same, human-readable
  data/seen.json         every role ID ever reported, so nothing is reported twice
  data/probe-report.md   which watchlist sources resolved and which failed
Read-only: it only reads public job listings. It never logs in or applies.
"""
from __future__ import annotations
import json, re, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yaml

ROOT = Path(__file__).parent
DATA = ROOT / "data"
ET = ZoneInfo("America/New_York")
UA = {"User-Agent": "job-radar/1.0 (personal job search; read-only)", "Accept": "application/json"}
TIMEOUT = 25

INCLUDE = re.compile(
    r"financ|fp&a|fp & a|capital|corporate development|corp dev|strateg|invest|associate|analyst|"
    r"m&a|mergers|treasury|valuation|private equity|credit|infrastructure|portfolio|"
    r"analytics|data analyst|bizops|business operations|mba|intern|summer|off-cycle|rotational",
    re.I)
EXCLUDE = re.compile(
    r"engineer|engineering|technician|software|developer|sales|account executive|account manager|"
    r"recruit|legal|counsel|paralegal|attorney|nurse|facilit|construction|electrician|mechanical|"
    r"security officer|guard|receptionist|executive assistant|administrative|\bhr\b|human resources|"
    r"vice president|\bvp\b|managing director|\bhead of|\bprincipal\b|\bpartner\b|chief|"
    r"senior manager|\bdirector\b(?<!associate director)|scientist|research engineer|designer|marketing manager",
    re.I)
NON_US = re.compile(
    r"london|united kingdom|\buk\b|singapore|india|bangalore|bengaluru|mumbai|hyderabad|toronto|canada|"
    r"seoul|korea|tokyo|japan|sydney|melbourne|australia|hong kong|paris|france|frankfurt|germany|"
    r"dublin|ireland|amsterdam|netherlands|luxembourg|madrid|spain|milan|italy|stockholm|zurich|"
    r"switzerland|dubai|abu dhabi|riyadh|são paulo|sao paulo|brazil|mexico|bogota|colombia|"
    r"warsaw|poland|tel aviv|israel|shanghai|beijing|china|manila|philippines|johannesburg|emea|apac",
    re.I)


def today_et() -> datetime:
    return datetime.now(ET)


def is_fresh_date(posted: datetime | None) -> bool:
    """Posted today or yesterday, in US Eastern time."""
    if posted is None:
        return False
    d = posted.astimezone(ET).date()
    t = today_et().date()
    return t - timedelta(days=1) <= d <= t


def title_ok(title: str) -> bool:
    if not INCLUDE.search(title):
        return False
    t = title.lower()
    if "associate director" in t:
        return True
    return not EXCLUDE.search(title)


def location_ok(loc: str) -> bool:
    if not loc:
        return True
    if re.search(r"united states|\busa\b|\bus\b|remote|new york|nyc", loc, re.I):
        return True
    return not NON_US.search(loc)


def parse_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------- fetchers: each returns list of dicts {id,title,location,posted(datetime|None),posted_label,url}

def fetch_greenhouse(slug):
    r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for j in r.json().get("jobs", []):
        posted = parse_iso(j.get("first_published")) or parse_iso(j.get("updated_at"))
        out.append({"id": f"gh:{slug}:{j['id']}", "title": j.get("title", ""),
                    "location": (j.get("location") or {}).get("name", ""),
                    "posted": posted,
                    "posted_label": "first published" if j.get("first_published") else "last updated (no publish date)",
                    "date_reliable": bool(j.get("first_published")),
                    "url": j.get("absolute_url", "")})
    return out


def fetch_lever(slug):
    r = requests.get(f"https://api.lever.co/v0/postings/{slug}?mode=json", headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for j in r.json():
        ms = j.get("createdAt")
        posted = datetime.fromtimestamp(ms / 1000, tz=timezone.utc) if ms else None
        cat = j.get("categories") or {}
        out.append({"id": f"lv:{slug}:{j['id']}", "title": j.get("text", ""),
                    "location": cat.get("location") or ", ".join(cat.get("allLocations") or []),
                    "posted": posted, "posted_label": "created", "date_reliable": True,
                    "url": j.get("hostedUrl", "")})
    return out


def fetch_ashby(slug):
    r = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for j in r.json().get("jobs", []):
        if j.get("isListed") is False:
            continue
        out.append({"id": f"ab:{slug}:{j.get('id')}", "title": j.get("title", ""),
                    "location": j.get("location", "") or "",
                    "posted": parse_iso(j.get("publishedAt")), "posted_label": "published",
                    "date_reliable": bool(j.get("publishedAt")),
                    "url": j.get("jobUrl", "")})
    return out


def _workday_age(label: str):
    """'Posted Today' -> 0, 'Posted Yesterday' -> 1, 'Posted 3 Days Ago' -> 3, '30+' -> 99."""
    l = (label or "").lower()
    if "today" in l:
        return 0
    if "yesterday" in l:
        return 1
    m = re.search(r"(\d+)\+?\s*day", l)
    return int(m.group(1)) if m else None


def fetch_workday(spec):
    tenant, wd, site = spec.split("|")
    base = f"https://{tenant}.{wd}.myworkdayjobs.com"
    api = f"{base}/wday/cxs/{tenant}/{site}/jobs"
    out, offset, total = [], 0, None
    while True:
        body = {"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": ""}
        r = requests.post(api, json=body, headers={**UA, "Content-Type": "application/json"}, timeout=TIMEOUT)
        r.raise_for_status()
        js = r.json()
        total = js.get("total", total) or 0
        posts = js.get("jobPostings", [])
        for p in posts:
            age = _workday_age(p.get("postedOn", ""))
            posted = (today_et() - timedelta(days=age)) if age is not None and age <= 1 else None
            out.append({"id": f"wd:{tenant}:{p.get('externalPath', p.get('title'))}", "title": p.get("title", ""),
                        "location": p.get("locationsText", ""), "posted": posted,
                        "posted_label": p.get("postedOn", ""), "date_reliable": age is not None,
                        "url": f"{base}/{site}{p.get('externalPath', '')}"})
        offset += 20
        if not posts or offset >= total or offset >= 2000:
            break
        time.sleep(0.4)
    return out


FETCHERS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby, "workday": fetch_workday}


def sources_for(entry):
    if "try" in entry:
        for t in entry["try"]:
            kind, _, spec = t.partition(":")
            yield kind, spec
    else:
        for kind in FETCHERS:
            if kind in entry:
                yield kind, entry[kind]


def main() -> int:
    DATA.mkdir(exist_ok=True)
    wl = yaml.safe_load((ROOT / "watchlist.yaml").read_text())
    seen_path = DATA / "seen.json"
    seen = set(json.loads(seen_path.read_text())) if seen_path.exists() else set()

    fresh, probe_lines, errors = [], [], []
    for group in ("verified", "probe"):
        for entry in wl.get(group) or []:
            resolved = False
            for kind, spec in sources_for(entry):
                try:
                    jobs = FETCHERS[kind](spec)
                except Exception as e:  # noqa: BLE001 — report and keep going
                    if group == "verified":
                        errors.append(f"- {entry['name']} ({kind}:{spec}): {type(e).__name__} {str(e)[:120]}")
                    continue
                if group == "probe" and not jobs:
                    continue
                resolved = True
                probe_lines.append(f"- OK  {entry['name']} -> {kind}:{spec} ({len(jobs)} open roles)")
                for j in jobs:
                    if not (is_fresh_date(j["posted"]) and j["date_reliable"]):
                        continue
                    if not (title_ok(j["title"]) and location_ok(j["location"])):
                        continue
                    if j["id"] in seen:
                        continue
                    seen.add(j["id"])
                    fresh.append({"company": entry["name"], "track": entry.get("track", ""),
                                  "title": j["title"], "location": j["location"],
                                  "postedDate": j["posted"].astimezone(ET).date().isoformat(),
                                  "postedLabel": j["posted_label"], "source": kind, "url": j["url"], "id": j["id"]})
                break
            if not resolved:
                probe_lines.append(f"- --  {entry['name']}: no source resolved")
            time.sleep(0.3)

    run = today_et().strftime("%Y-%m-%d %H:%M ET")
    (DATA / "fresh.json").write_text(json.dumps({"run": run, "roles": fresh}, indent=1))
    md = [f"# Fresh roles — {run}", "", f"{len(fresh)} new finance roles posted today or yesterday.", ""]
    for f in sorted(fresh, key=lambda x: (x["track"], x["company"])):
        md.append(f"- **{f['company']}** — [{f['title']}]({f['url']}) · {f['location']} · posted {f['postedDate']} · {f['track']}")
    (DATA / "fresh.md").write_text("\n".join(md) + "\n")
    (DATA / "probe-report.md").write_text(f"# Source check — {run}\n\n" + "\n".join(probe_lines) +
                                          ("\n\n## Errors on verified sources\n" + "\n".join(errors) if errors else "") + "\n")
    seen_path.write_text(json.dumps(sorted(seen)))
    print(f"{len(fresh)} fresh roles; {sum(l.startswith('- OK') for l in probe_lines)} sources resolved; {len(errors)} errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
