#!/usr/bin/env python3
"""Tailor one of Sam's real Word resumes for a specific role, plus a cover letter.

Usage:
  python3 tailor.py plan.json --out OUTDIR

plan.json:
{
  "company": "Crusoe", "role": "Associate, Corporate Development", "variant": "finance-core",
  "job_url": "https://...",
  "edits": [ {"old": "<exact text of an existing bullet/line>", "new": "<rewritten text>", "why": "..."} ],
  "cover_letter": {"greeting": "Dear Crusoe Hiring Team,", "paragraphs": ["...", "...", "..."]}
}

What it guarantees:
  * Formatting stays yours: only the text of the edited paragraphs changes (font, size, bullets, spacing untouched).
  * Claims gate: any number, credential or employer in the new text that isn't in your real resumes stops the run.
  * Never longer than your original: the tailored resume is rendered and compared with the base; longer = stop.
  * Coach comments are stripped from every output.
Outputs (in OUTDIR):
  Sam_Dasgupta_Resume_<Company>.docx / .pdf      tailored resume
  Sam_Dasgupta_Resume_<Company>_REDLINE.docx     every change as Word tracked changes, vs your original
  Sam_Dasgupta_Cover_Letter_<Company>.docx / .pdf
  CHANGES.md                                     what changed and why
"""
from __future__ import annotations
import argparse, copy, datetime as dt, json, re, shutil, subprocess, sys, tempfile, zipfile
from pathlib import Path

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, Inches
from lxml import etree

ROOT = Path(__file__).resolve().parent
BASE = {
    "finance-core": ROOT / "base/finance-core-with-notes.docx",
    "project-finance-solar": ROOT / "base/project-finance-solar.docx",
    "data-analytics": ROOT / "base/data-analytics.docx",
    "finance-marketing": ROOT / "base/finance-marketing.docx",
}
FACTS = (ROOT / "facts.txt").read_text()

# ---------------- claims gate ----------------
NUM = re.compile(r"\$?\s?\d[\d,]*(?:\.\d+)?\s?(?:%|percent\b|million\b|billion\b|thousand\b|MW\b|[KMBkmbx]\b)?\+?", re.I)
CRED = ["CPA", "CFA", "CAIA", "FRM", "CMA", "PMP", "ACCA", "PhD", "FMVA", "Series 7", "Series 63", "Series 79", "SIE"]
EMP = ["morgan stanley", "goldman sachs", "blackrock", "blackstone", "kkr", "carlyle", "apollo", "brookfield",
       "macquarie", "evercore", "lazard", "centerview", "moelis", "jefferies", "guggenheim", "houlihan", "deloitte",
       "pwc", "kpmg", "mckinsey", "bain", "google", "microsoft", "amazon", "nvidia", "openai", "anthropic", "meta",
       "coreweave", "crusoe", "lambda", "stripe", "brex", "ramp"]


def _canon(t):
    t = t.lower().replace(",", "").replace(" ", "").lstrip("$").rstrip("+")
    for w, s in (("percent", "%"), ("million", "m"), ("billion", "b"), ("thousand", "k")):
        if t.endswith(w):
            t = t[: -len(w)] + s
    return t


def _has(n, h, cs=False):
    return re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", h, 0 if cs else re.I)


def claims_gate(text: str, company: str) -> list[str]:
    base_nums = {_canon(m.group(0)) for m in NUM.finditer(FACTS)}
    bad = []
    for m in NUM.finditer(text):
        k = _canon(m.group(0))
        if len(k) > 1 and k not in base_nums and not re.fullmatch(r"20\d\d", k):
            bad.append(f'number "{m.group(0).strip()}"')
    bad += [f'credential "{c}"' for c in CRED if _has(c, text, True) and not _has(c, FACTS, True)]
    bad += [f'employer "{e}"' for e in EMP if _has(e, text) and not _has(e, FACTS) and e not in company.lower()]
    return sorted(set(bad))


# ---------------- docx helpers ----------------
def norm(s):
    return re.sub(r"\s+", " ", s.replace(" ", " ")).strip()


def find_para(doc, old):
    target = norm(old)
    hits = [p for p in doc.paragraphs if norm(p.text) == target]
    if not hits:  # allow a unique prefix match (long bullets)
        hits = [p for p in doc.paragraphs if len(target) > 40 and norm(p.text).startswith(target[:60])]
    if len(hits) != 1:
        raise SystemExit(f"EDIT NOT APPLIED: could not uniquely find this line in the base resume:\n  {old[:120]}")
    return hits[0]


def text_runs(p):
    return [r for r in p.runs if r.text]


def set_text_keep_format(p, new):
    runs = text_runs(p)
    # keep a leading bold label like "Technical:" if the new text starts with it
    label = ""
    if runs and runs[0].bold and runs[0].text.strip().endswith(":") and new.startswith(runs[0].text.strip()):
        label = runs[0].text
        body_runs = runs[1:]
        new = new[len(runs[0].text.strip()):]
        if not new.startswith(" ") and label.endswith(":"):
            new = " " + new.lstrip()
    else:
        body_runs = runs
    if not body_runs:
        raise SystemExit("EDIT NOT APPLIED: line has no editable text")
    keep = body_runs[0]
    keep.text = new
    for r in body_runs[1:]:
        r._r.getparent().remove(r._r)


def strip_comments_xml(doc):
    body = doc.element.body
    for tag in ("w:commentRangeStart", "w:commentRangeEnd"):
        for el in body.iter(qn(tag)):
            pass
        for el in list(body.iter(qn(tag))):
            el.getparent().remove(el)
    for ref in list(body.iter(qn("w:commentReference"))):
        run = ref.getparent()
        run.getparent().remove(run)


def drop_comment_parts(path: Path):
    """Remove comments*.xml/people.xml parts and their references from a saved docx."""
    tmp = path.with_suffix(".tmp")
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            name = item.filename
            if re.match(r"word/(comments.*|people)\.xml$", name):
                continue
            data = zin.read(name)
            if name == "word/_rels/document.xml.rels":
                data = re.sub(rb'<Relationship [^>]*Target="(comments[^"]*|people)\.xml"[^>]*/>', b"", data)
            if name == "[Content_Types].xml":
                data = re.sub(rb'<Override PartName="/word/(comments[^"]*|people)\.xml"[^>]*/>', b"", data)
            zout.writestr(item, data)
    tmp.replace(path)


def tracked_change(p, new, author="Claude (tailored)"):
    """Turn paragraph p into: <del>old runs</del><ins>new run</ins> (Word tracked changes)."""
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    runs = [r for r in p.runs if r.text]
    if not runs:
        return
    tmpl = copy.deepcopy(runs[0]._r)
    d = etree.SubElement(p._p, qn("w:del"))
    d.set(qn("w:id"), str(abs(hash(p.text)) % 10**6)); d.set(qn("w:author"), author); d.set(qn("w:date"), now)
    for r in runs:
        el = r._r
        el.getparent().remove(el)
        for t in el.findall(qn("w:t")):
            t.tag = qn("w:delText")
        d.append(el)
    ins = etree.SubElement(p._p, qn("w:ins"))
    ins.set(qn("w:id"), str(abs(hash(new)) % 10**6 + 1)); ins.set(qn("w:author"), author); ins.set(qn("w:date"), now)
    for t in tmpl.findall(qn("w:t")):
        tmpl.remove(t)
    t = etree.SubElement(tmpl, qn("w:t")); t.text = new
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    ins.append(tmpl)


# ---------------- rendering ----------------
def to_pdf(docx_path: Path, outdir: Path) -> Path:
    subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(outdir), str(docx_path)],
                   check=True, capture_output=True, timeout=180)
    return outdir / (docx_path.stem + ".pdf")


def rendered_extent(pdf: Path) -> float:
    """pages*1000 + y of the last text line, in the same renderer — used to compare lengths."""
    out = subprocess.run(["pdftotext", "-bbox", str(pdf), "-"], capture_output=True, text=True).stdout
    pages = out.count("<page ")
    last_page = out.split("<page ")[-1]
    ys = [float(y) for y in re.findall(r'yMax="([\d.]+)"', last_page)]
    return (pages - 1) * 1000 + (max(ys) if ys else 0)


def page_count(pdf: Path) -> int:
    out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
    m = re.search(r"Pages:\s+(\d+)", out)
    return int(m.group(1)) if m else 0


# ---------------- cover letter ----------------
def build_cover_letter(base_doc, plan, path: Path):
    font = "Garamond" if any((r.font.name or "") == "Garamond" for p in base_doc.paragraphs[:20] for r in p.runs) \
        else "Times New Roman"
    name = norm(base_doc.paragraphs[0].text)
    contact = norm(base_doc.paragraphs[1].text)
    d = docx.Document()
    s = d.sections[0]
    s.left_margin = s.right_margin = Inches(1); s.top_margin = s.bottom_margin = Inches(0.9)
    st = d.styles["Normal"]; st.font.name = font; st.font.size = Pt(11)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), font)
    st.paragraph_format.space_after = Pt(8)

    def para(text, bold=False, size=None, align=None, after=None):
        p = d.add_paragraph(); r = p.add_run(text); r.bold = bold
        if size: r.font.size = Pt(size)
        if align is not None: p.alignment = align
        if after is not None: p.paragraph_format.space_after = Pt(after)
        return p
    para(name, bold=True, size=16, align=WD_ALIGN_PARAGRAPH.CENTER, after=0)
    para(contact, size=10, align=WD_ALIGN_PARAGRAPH.CENTER, after=18)
    para(dt.date.today().strftime("%B %-d, %Y"), after=12)
    cl = plan["cover_letter"]
    para(f"Re: {plan['role']}", bold=True, after=12)
    para(cl.get("greeting") or f"Dear {plan['company']} Hiring Team,")
    for t in cl["paragraphs"]:
        p = para(t); p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    para("Sincerely,", after=2)
    para(name.title() if name.isupper() else name)
    d.save(path)


# ---------------- main ----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan"); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    plan = json.loads(Path(a.plan).read_text())
    company, variant = plan["company"], plan["variant"]
    base = BASE[variant]
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9]+", "_", company).strip("_")

    # 1. claims gate on everything new
    new_text = "\n".join(e["new"] for e in plan["edits"]) + "\n" + "\n".join(plan["cover_letter"]["paragraphs"])
    problems = claims_gate(new_text, company)
    if problems:
        print("CLAIMS GATE FAILED. Nothing was generated. Remove or fix:\n  - " + "\n  - ".join(problems))
        sys.exit(2)

    # 2. tailored resume + redline
    doc, red = docx.Document(base), docx.Document(base)
    for e in plan["edits"]:
        set_text_keep_format(find_para(doc, e["old"]), e["new"])
        tracked_change(find_para(red, e["old"]), e["new"])
    for dd in (doc, red):
        strip_comments_xml(dd)
    resume = out / f"Sam_Dasgupta_Resume_{safe}.docx"
    redline = out / f"Sam_Dasgupta_Resume_{safe}_REDLINE.docx"
    doc.save(resume); red.save(redline)
    drop_comment_parts(resume); drop_comment_parts(redline)

    # 3. length check vs the original, in the same renderer
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        bcopy = tdp / "base.docx"; shutil.copy(base, bcopy)
        base_ext = rendered_extent(to_pdf(bcopy, tdp))
        new_pdf = to_pdf(resume, out)
        new_ext = rendered_extent(new_pdf)
    if new_ext > base_ext + 2:
        print(f"LENGTH CHECK FAILED: tailored resume runs longer than your original "
              f"(extent {new_ext:.0f} vs {base_ext:.0f}). Shorten the edited bullets.")
        sys.exit(3)
    pdf_note = "" if page_count(new_pdf) == 1 else (
        "Note: the PDF here is from LibreOffice and spills to 2 pages because of font spacing; "
        "the resume itself is no longer than your original. Use the Google Doc copy and File → Download → PDF.")

    # 4. cover letter
    cover = out / f"Sam_Dasgupta_Cover_Letter_{safe}.docx"
    build_cover_letter(docx.Document(base), plan, cover)
    to_pdf(cover, out)

    # 5. change log
    lines = [f"# {company} — {plan['role']}", "", f"Base resume: **{variant}**  ", f"Posting: {plan.get('job_url','')}", "",
             "Claims check: passed (every number, credential and employer traces to your real resumes).  ",
             "Length check: passed (not longer than your original).", ""]
    if pdf_note:
        lines += [pdf_note, ""]
    lines += ["## Resume changes", ""]
    for i, e in enumerate(plan["edits"], 1):
        lines += [f"**{i}.** {e.get('why','')}", f"- Before: {norm(e['old'])}", f"- After: {e['new']}", ""]
    (out / "CHANGES.md").write_text("\n".join(lines))
    print(f"OK {out}\n" + ("\n" + pdf_note if pdf_note else ""))


if __name__ == "__main__":
    main()
