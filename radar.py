#!/usr/bin/env python3
"""job-radar: find finance roles posted today or yesterday (US Eastern) at Sam's target companies.

Reads watchlist.yaml, pulls each company's public job feed (Greenhouse, Lever, Ashby, Workday, Oracle,
Jibe, SmartRecruiters, iCIMS) plus job boards (Hacker News, Built In NYC, Remotive, WeWorkRemotely) and
employer APIs (Amazon, Microsoft, Publicis). Boards that publish no posting date run in first-seen mode.
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
BROWSER = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/126.0 Safari/537.36", "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
           "Accept-Language": "en-US,en;q=0.9"}
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
    r"senior manager|\bdirector\b|scientist|designer|marketing|content|procurement|sourcing|security|cyber|"
    r"network|hse\b|safety|product operations|business development|customer|support|"
    r"\bavp\b|lead\b|clinical|warehouse|logistics|\bit\b",
    re.I)
NON_US = re.compile(
    r"london|united kingdom|\buk\b|singapore|india|bangalore|bengaluru|mumbai|hyderabad|toronto|canada|"
    r"seoul|korea|tokyo|japan|sydney|melbourne|australia|hong kong|paris|france|frankfurt|germany|"
    r"dublin|ireland|amsterdam|netherlands|luxembourg|madrid|spain|milan|italy|stockholm|zurich|"
    r"switzerland|dubai|abu dhabi|riyadh|são paulo|sao paulo|brazil|mexico|bogota|colombia|"
    r"gurugram|gurgaon|noida|pune|chennai|telangana|haryana|calgary|ontario|"
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
    return not EXCLUDE.search(title.replace("Associate Director", "AssocDir").replace("associate director", "AssocDir"))


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
                    "url": j.get("absolute_url", ""), "jd_ref": ("greenhouse", slug, j["id"])})
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
                    "url": j.get("hostedUrl", ""),
                    "jd_text": (j.get("descriptionPlain") or "") + "\n" + "\n".join(
                        f"{l.get('text','')}: " + re.sub(r"<[^>]+>", " ", l.get("content", "")) for l in j.get("lists") or [])
                        + "\n" + (j.get("additionalPlain") or "")})
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
                    "url": j.get("jobUrl", ""), "jd_text": j.get("descriptionPlain") or ""})
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
        if total is None:
            total = js.get("total") or 0
        posts = js.get("jobPostings", [])
        for p in posts:
            age = _workday_age(p.get("postedOn", ""))
            posted = (today_et() - timedelta(days=age)) if age is not None and age <= 1 else None
            loc = p.get("locationsText", "")
            if re.match(r"\d+ locations", loc or "", re.I):
                # "3 Locations" hides the cities; the job path starts with the primary one
                m = re.match(r"/job/([^/]+)/", p.get("externalPath", ""))
                loc = (m.group(1).replace("-", " ") if m else loc)
            out.append({"id": f"wd:{tenant}:{p.get('externalPath', p.get('title'))}", "title": p.get("title", ""),
                        "location": loc, "posted": posted,
                        "posted_label": p.get("postedOn", ""), "date_reliable": age is not None,
                        "url": f"{base}/{site}{p.get('externalPath', '')}",
                        "jd_ref": ("workday", f"{base}/wday/cxs/{tenant}/{site}{p.get('externalPath', '')}")})
        offset += 20
        if not posts or offset >= total or offset >= 2000:
            break
        time.sleep(0.4)
    return out


def fetch_oracle(spec):
    """Oracle Recruiting Cloud: spec = <host>|<siteNumber>. Lists newest first."""
    host, site = spec.split("|")
    url = (f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
           f"?onlyData=true&expand=requisitionList.secondaryLocations"
           f"&finder=findReqs;siteNumber={site},facetsList=NONE,limit=200,sortBy=POSTING_DATES_DESC")
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    items = r.json().get("items") or []
    reqs = (items[0].get("requisitionList") if items else None) or []
    out = []
    for j in reqs:
        d = j.get("PostedDate")
        posted = datetime.fromisoformat(d).replace(tzinfo=ET) if d else None
        out.append({"id": f"or:{host}:{j.get('Id')}", "title": j.get("Title", ""),
                    "location": j.get("PrimaryLocation", "") or "", "posted": posted,
                    "posted_label": "posted", "date_reliable": bool(d),
                    "url": f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{j.get('Id')}",
                    "jd_ref": ("oracle", host, site, j.get("Id"))})
    return out


# ---------- added 2026-11-02: job boards, employer APIs, university boards ----------
# Jobs from these fetchers may carry their own "company" (aggregators). Sources with no posting date are
# marked date_reliable=False and run in first-seen mode (see main): a listing counts as new only if it
# wasn't on that board at the previous daily run.

def _kw(spec):
    return [k.strip() for k in spec.split(";") if k.strip()]


def _dedupe(jobs):
    seen, out = set(), []
    for j in jobs:
        if j["id"] not in seen:
            seen.add(j["id"]); out.append(j)
    return out


def fetch_jibe(spec):
    """Jibe-hosted boards (Mount Sinai, Montefiore/Einstein, Rockefeller). spec = host|kw1;kw2"""
    host, kws = spec.split("|", 1)
    out = []
    for kw in _kw(kws):
        r = requests.get(f"https://{host}/api/jobs", params={"keywords": kw, "limit": 40, "sortBy": "posted_date",
                                                            "descending": "true"}, headers=BROWSER, timeout=TIMEOUT)
        r.raise_for_status()
        for it in r.json().get("jobs", []):
            d = it.get("data", it)
            posted = parse_iso(d.get("posted_date") or d.get("create_date"))
            loc = ", ".join(x for x in (d.get("city"), d.get("state"), d.get("country")) if x)
            slug = d.get("slug") or d.get("req_id")
            out.append({"id": f"jb:{host}:{slug}", "title": d.get("title", ""), "location": loc, "posted": posted,
                        "posted_label": "posted", "date_reliable": posted is not None,
                        "url": d.get("apply_url") if not slug else f"https://{host}/jobs/{slug}",
                        "jd_text": d.get("description") or ""})
        time.sleep(0.5)
    return _dedupe(out)


def fetch_smartrecruiters(company):
    r = requests.get(f"https://api.smartrecruiters.com/v1/companies/{company}/postings", params={"limit": 100},
                     headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for j in r.json().get("content", []):
        loc = j.get("location") or {}
        out.append({"id": f"sr:{company}:{j['id']}", "title": j.get("name", ""),
                    "location": ", ".join(x for x in (loc.get("city"), loc.get("region"), loc.get("country")) if x),
                    "posted": parse_iso(j.get("releasedDate")), "posted_label": "released",
                    "date_reliable": bool(j.get("releasedDate")),
                    "url": f"https://jobs.smartrecruiters.com/{company}/{j['id']}", "jd_ref": ("url", j.get("ref", ""))})
    return out


def fetch_amazon(spec):
    """Amazon jobs search API. spec = kw1;kw2 (US only, newest first)."""
    out = []
    for kw in _kw(spec):
        r = requests.get("https://www.amazon.jobs/en/search.json",
                         params={"base_query": kw, "normalized_country_code[]": "USA", "result_limit": 100,
                                 "sort": "recent", "offset": 0}, headers=BROWSER, timeout=TIMEOUT)
        r.raise_for_status()
        for j in r.json().get("jobs", []):
            try:
                posted = datetime.strptime(j.get("posted_date", ""), "%B %d, %Y").replace(tzinfo=ET)
            except ValueError:
                posted = None
            out.append({"id": f"amzn:{j.get('id_icims') or j.get('id')}", "title": j.get("title", ""),
                        "location": j.get("normalized_location") or j.get("location", ""), "posted": posted,
                        "posted_label": "posted", "date_reliable": posted is not None,
                        "url": "https://www.amazon.jobs" + (j.get("job_path") or ""),
                        "jd_text": (j.get("description") or "") + "\n\n" + (j.get("basic_qualifications") or "")
                                   + "\n\n" + (j.get("preferred_qualifications") or "")})
        time.sleep(1)
    return _dedupe(out)


def fetch_microsoft(spec):
    """Microsoft careers search (rate-limited: one query per keyword, backs off on 429)."""
    out = []
    for kw in _kw(spec):
        js = None
        for attempt in range(3):
            r = requests.get("https://apply.careers.microsoft.com/api/pcsx/search",
                             params={"domain": "microsoft.com", "query": kw, "location": "United States",
                                     "start": 0, "sort_by": "timestamp"}, headers=BROWSER, timeout=TIMEOUT)
            if r.status_code == 429:
                time.sleep(20 * (attempt + 1)); continue
            r.raise_for_status(); js = r.json(); break
        if js is None:
            raise RuntimeError("rate-limited (429) after 3 attempts")
        for p in (js.get("data") or {}).get("positions", []):
            ts = p.get("postedTs") or p.get("creationTs") or p.get("postingDate")
            posted = (datetime.fromtimestamp(ts, tz=timezone.utc) if isinstance(ts, (int, float))
                      else parse_iso(ts))
            locs = p.get("locations") or p.get("standardizedLocations") or []
            out.append({"id": f"msft:{p.get('id') or p.get('displayJobId')}", "title": p.get("name", ""),
                        "location": "; ".join(locs) if isinstance(locs, list) else str(locs), "posted": posted,
                        "posted_label": "posted", "date_reliable": posted is not None,
                        "url": p.get("positionUrl") and ("https://apply.careers.microsoft.com" + p["positionUrl"]
                                                        if p["positionUrl"].startswith("/") else p["positionUrl"])
                               or f"https://apply.careers.microsoft.com/careers/job/{p.get('id')}"})
        time.sleep(20)
    return _dedupe(out)


def _walk_job_dicts(obj):
    """Find job-like dicts (have a title-ish key) anywhere in a JSON response."""
    if isinstance(obj, dict):
        if any(k in obj for k in ("title", "jobTitle", "job_title", "name")) and \
           any(k in obj for k in ("id", "jobId", "job_id", "slug", "url", "applyUrl", "link")):
            yield obj
        for v in obj.values():
            yield from _walk_job_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_job_dicts(v)


def fetch_jsonapi(spec):
    """Generic employer job API. spec = url-with-{kw}|kw1;kw2  (used for Publicis)."""
    url_t, kws = spec.split("|", 1)
    out = []
    for kw in _kw(kws):
        r = requests.get(url_t.replace("{kw}", requests.utils.quote(kw)), headers=BROWSER, timeout=TIMEOUT)
        r.raise_for_status()
        for d in _walk_job_dicts(r.json()):
            title = d.get("title") or d.get("jobTitle") or d.get("job_title") or d.get("name") or ""
            posted = parse_iso(d.get("postedDate") or d.get("posted_date") or d.get("datePosted")
                               or d.get("publishedAt") or d.get("createdAt") or d.get("created_at"))
            jid = d.get("id") or d.get("jobId") or d.get("job_id") or d.get("slug") or d.get("url")
            link = d.get("url") or d.get("applyUrl") or d.get("link") or ""
            loc = d.get("location") or d.get("city") or ""
            if isinstance(loc, dict):
                loc = ", ".join(str(v) for v in loc.values() if isinstance(v, str))
            out.append({"id": f"api:{url_t.split('/')[2]}:{jid}", "title": str(title), "location": str(loc),
                        "posted": posted, "posted_label": "posted", "date_reliable": posted is not None,
                        "url": link if str(link).startswith("http") else f"https://{url_t.split('/')[2]}{link}"})
        time.sleep(1)
    return _dedupe(out)


def fetch_remotive(spec):
    """Remotive public API. spec = category1;category2"""
    out = []
    for cat in _kw(spec):
        r = requests.get("https://remotive.com/api/remote-jobs", params={"category": cat}, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        for j in r.json().get("jobs", []):
            out.append({"id": f"rmt:{j['id']}", "title": j.get("title", ""), "company": j.get("company_name", ""),
                        "location": "Remote · " + (j.get("candidate_required_location") or ""),
                        "posted": parse_iso(j.get("publication_date")), "posted_label": "published",
                        "date_reliable": bool(j.get("publication_date")), "url": j.get("url", ""),
                        "jd_text": j.get("description") or ""})
    return _dedupe(out)


def fetch_rss(url):
    """RSS job feed (WeWorkRemotely style: '<Company>: <Title>')."""
    import xml.etree.ElementTree as ET_
    from email.utils import parsedate_to_datetime
    r = requests.get(url, headers=BROWSER, timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for it in ET_.fromstring(r.content).iter("item"):
        raw = (it.findtext("title") or "").strip()
        company, _, title = raw.partition(":")
        if not title:
            company, title = "", raw
        try:
            posted = parsedate_to_datetime(it.findtext("pubDate") or "")
        except (TypeError, ValueError):
            posted = None
        link = it.findtext("link") or it.findtext("guid") or ""
        out.append({"id": f"rss:{link}", "title": title.strip(), "company": company.strip(),
                    "location": "Remote · " + (it.findtext("region") or ""), "posted": posted,
                    "posted_label": "published", "date_reliable": posted is not None, "url": link,
                    "jd_text": it.findtext("description") or ""})
    return out


def fetch_hn(_spec):
    """Hacker News 'Who is hiring?' — this month's thread, top-level comments, via the Algolia API."""
    r = requests.get("https://hn.algolia.com/api/v1/search_by_date",
                     params={"tags": "story,author_whoishiring", "hitsPerPage": 10}, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    hit = next((h for h in r.json().get("hits", []) if "who is hiring" in (h.get("title") or "").lower()), None)
    if not hit:
        raise RuntimeError("no current 'Who is hiring?' thread found")
    r = requests.get(f"https://hn.algolia.com/api/v1/items/{hit['objectID']}", headers=UA, timeout=60)
    r.raise_for_status()
    out = []
    for c in r.json().get("children", []):
        text = c.get("text") or ""
        if not text:
            continue
        header = html_to_text(text.split("<p>")[0]).split("\n")[0]
        parts = [p.strip() for p in header.split("|") if p.strip()]
        if not parts:
            continue
        role = next((p for p in parts[1:] if title_ok(p)), "")
        out.append({"id": f"hn:{c['id']}", "title": role or (parts[1] if len(parts) > 1 else header)[:120],
                    "company": parts[0][:80], "location": " | ".join(p for p in parts[1:] if p != role)[:160],
                    "posted": parse_iso(c.get("created_at")), "posted_label": "posted on HN",
                    "date_reliable": bool(c.get("created_at")) and bool(role),
                    "url": f"https://news.ycombinator.com/item?id={c['id']}", "jd_text": text})
    return out


def _anchors(html, base):
    import html as _h
    from urllib.parse import urljoin
    for m in re.finditer(r'<a\b([^>]*)>(.*?)</a>', html, re.S | re.I):
        attrs, inner = m.group(1), m.group(2)
        hm = re.search(r'href\s*=\s*["\']([^"\']+)["\']', attrs)
        if not hm:
            continue
        tm = re.search(r'title\s*=\s*["\']([^"\']+)["\']', attrs)
        text = _h.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", inner))).strip()
        yield urljoin(base, _h.unescape(hm.group(1))), text, (_h.unescape(tm.group(1)) if tm else "")


JOB_HREF = re.compile(r"/jobs?/|/postings?/|jobdetail|job_detail|/careers?/[^/]+/\d|/opportunit|requisition|/vacanc", re.I)


def fetch_links(spec):
    """Any HTML job list. spec = url1;url2. Collects job-like links; no dates, so first-seen mode."""
    out = []
    for url in _kw(spec):
        r = requests.get(url, headers=BROWSER, timeout=TIMEOUT)
        r.raise_for_status()
        for href, text, title_attr in _anchors(r.text, url):
            t = re.sub(r"^\d+\s*-\s*", "", title_attr or text).strip()
            if not JOB_HREF.search(href) or not (8 <= len(t) <= 140) or href.rstrip("/") == url.rstrip("/"):
                continue
            if re.search(r"^(apply|view|search|sign in|log in|next|previous|more|all jobs|see all)\b", t, re.I):
                continue
            jid = re.sub(r"[?#].*$", "", href)
            out.append({"id": f"lnk:{jid}", "title": t, "location": "", "posted": None,
                        "posted_label": "new on board since last run", "date_reliable": False, "url": href,
                        "jd_ref": ("url", href)})
        time.sleep(1)
    return _dedupe(out)


def fetch_sitemap(url):
    """Job-board sitemap (Columbia). Title from the URL slug; first-seen mode."""
    r = requests.get(url, headers=BROWSER, timeout=60)
    r.raise_for_status()
    out = []
    for loc in re.findall(r"<loc>\s*([^<]+?)\s*</loc>", r.text):
        if not re.search(r"/job", loc, re.I):
            continue
        slug = loc.rstrip("/").split("/")[-1]
        title = re.sub(r"[-_]+", " ", re.sub(r"^\d+[-_]?", "", slug)).strip().title()
        out.append({"id": f"sm:{loc}", "title": title, "location": "", "posted": None,
                    "posted_label": "new on board since last run", "date_reliable": False, "url": loc,
                    "jd_ref": ("url", loc)})
    return out


def html_to_text(h: str) -> str:
    import html as _h
    h = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>", "\n", h or "")
    h = re.sub(r"(?i)<li[^>]*>", "- ", h)
    t = _h.unescape(re.sub(r"<[^>]+>", " ", _h.unescape(h)))
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", t)).strip()


def fetch_jd(job) -> str:
    """Full job description text for one posting (only called for fresh roles)."""
    if job.get("jd_text"):
        return html_to_text(job["jd_text"])
    ref = job.get("jd_ref")
    if not ref:
        return ""
    kind = ref[0]
    if kind == "greenhouse":
        r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{ref[1]}/jobs/{ref[2]}", headers=UA, timeout=TIMEOUT)
        r.raise_for_status(); return html_to_text(r.json().get("content", ""))
    if kind == "workday":
        r = requests.get(ref[1], headers=UA, timeout=TIMEOUT)
        r.raise_for_status(); return html_to_text((r.json().get("jobPostingInfo") or {}).get("jobDescription", ""))
    if kind == "oracle":
        _, host, site, jid = ref
        url = (f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
               f"?expand=all&onlyData=true&finder=ById;Id=%22{jid}%22,siteNumber={site}")
        r = requests.get(url, headers=UA, timeout=TIMEOUT); r.raise_for_status()
        it = (r.json().get("items") or [{}])[0]
        return html_to_text("\n".join(str(it.get(k) or "") for k in
                                       ("ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr")))
    if kind == "url" and ref[1]:
        r = requests.get(ref[1], headers=BROWSER, timeout=TIMEOUT); r.raise_for_status()
        if "json" in r.headers.get("content-type", ""):
            js = r.json(); sec = (js.get("jobAd") or {}).get("sections") or {}
            return html_to_text("\n".join((v or {}).get("text", "") for v in sec.values()) or json.dumps(js)[:20000])
        body = re.sub(r"(?is)<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", r.text)
        return html_to_text(body)[:20000]
    return ""


FETCHERS = {"oracle": fetch_oracle, "greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby,
            "workday": fetch_workday, "jibe": fetch_jibe, "smartrecruiters": fetch_smartrecruiters,
            "amazon": fetch_amazon, "microsoft": fetch_microsoft, "jsonapi": fetch_jsonapi, "remotive": fetch_remotive,
            "rss": fetch_rss, "hn": fetch_hn, "links": fetch_links, "sitemap": fetch_sitemap}


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
    if "--reset-seen" in sys.argv:
        seen = set()

    base_path = DATA / "baselines.json"
    baselines = set(json.loads(base_path.read_text())) if base_path.exists() else set()
    fresh, probe_lines, errors, dupkeys = [], [], [], set()
    for group in ("verified", "feeds", "probe"):
        for entry in wl.get(group) or []:
            resolved = False
            for kind, spec in sources_for(entry):
                try:
                    jobs = FETCHERS[kind](spec)
                except Exception as e:  # noqa: BLE001 — report and keep going
                    if group in ("verified", "feeds"):
                        errors.append(f"- {entry['name']} ({kind}:{spec}): {type(e).__name__} {str(e)[:120]}")
                    continue
                if group == "probe" and not jobs:
                    continue
                resolved = True
                key = f"{kind}:{spec}"
                first_seen = bool(entry.get("first_seen"))
                note = ""
                if first_seen and key not in baselines:
                    # first run on an undated board: remember everything listed today, report nothing yet
                    seen.update(j["id"] for j in jobs); baselines.add(key)
                    note = f" — baseline of {len(jobs)} saved; new listings reported from the next run"
                    jobs = []
                elif first_seen:
                    for j in jobs:
                        if j["id"] not in seen:
                            j["posted"], j["date_reliable"] = today_et(), True
                dated = sum(1 for j in jobs if j.get("date_reliable"))
                probe_lines.append(f"- OK  {entry['name']} -> {kind}:{spec[:70]}" +
                                   (note if note else f" ({len(jobs)} listings, {dated} with a posting date)"))
                for j in jobs:
                    if first_seen and j["id"] in seen:
                        continue
                    if first_seen:
                        seen.add(j["id"])  # remember every new listing, matched or not
                    if not (is_fresh_date(j["posted"]) and j["date_reliable"]):
                        continue
                    if not (title_ok(j["title"]) and location_ok(j["location"])):
                        continue
                    company = j.get("company") or ("(see posting)" if entry.get("aggregator") else entry["name"])
                    dk = "dk:" + re.sub(r"\W+", "", company.lower())[:20] + "|" + re.sub(r"\W+", "", j["title"].lower())
                    if (j["id"] in seen and not first_seen) or dk in seen or dk in dupkeys:
                        continue  # same company + same title already reported (repost or cross-listed)
                    seen.add(j["id"]); dupkeys.add(dk)
                    if not company.startswith("("):
                        seen.add(dk)
                    jd_file = ""
                    try:
                        jd = fetch_jd(j)
                        if jd:
                            jd_file = f"data/jd/{re.sub(r'[^A-Za-z0-9]+', '_', j['id'])[-80:]}.txt"
                            (ROOT / jd_file).parent.mkdir(parents=True, exist_ok=True)
                            (ROOT / jd_file).write_text(f"{company} — {j['title']}\n{j['url']}\n\n{jd}\n")
                    except Exception as e:  # noqa: BLE001
                        errors.append(f"- JD fetch failed for {company} / {j['title']}: {type(e).__name__}")
                    fresh.append({"jd": jd_file, "company": company, "track": entry.get("track", ""),
                                  "via": entry["name"] if (j.get("company") or entry.get("aggregator")) else "",
                                  "title": j["title"], "location": j["location"],
                                  "postedDate": j["posted"].astimezone(ET).date().isoformat(),
                                  "postedLabel": j["posted_label"], "source": kind, "url": j["url"], "id": j["id"]})
                break
            if not resolved:
                probe_lines.append(f"- --  {entry['name']}: no source resolved")
            time.sleep(0.3)
        probe_lines.append("")

    run = today_et().strftime("%Y-%m-%d %H:%M ET")
    (DATA / "fresh.json").write_text(json.dumps({"run": run, "roles": fresh}, indent=1))
    md = [f"# Fresh roles — {run}", "", f"{len(fresh)} new finance roles posted today or yesterday.", ""]
    for f in sorted(fresh, key=lambda x: (x["track"], x["company"])):
        via = f" · via {f['via']}" if f.get("via") else ""
        md.append(f"- **{f['company']}** — [{f['title']}]({f['url']}) · {f['location']} · posted {f['postedDate']} · {f['track']}{via}")
    (DATA / "fresh.md").write_text("\n".join(md) + "\n")
    (DATA / "probe-report.md").write_text(f"# Source check — {run}\n\n" + "\n".join(probe_lines) +
                                          ("\n\n## Errors on verified sources\n" + "\n".join(errors) if errors else "") + "\n")
    seen_path.write_text(json.dumps(sorted(seen)))
    base_path.write_text(json.dumps(sorted(baselines)))
    print(f"{len(fresh)} fresh roles; {sum(l.startswith('- OK') for l in probe_lines)} sources resolved; {len(errors)} errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
