# How to draft an application for Sam

Used by the "Morning fresh roles" scheduled task and by Claude in chat. The engine (`tailor.py`) enforces the hard rules; this guide covers the judgment.

## 1. Pick the base resume
| Role is mostly… | Variant |
|---|---|
| IB, PE, corp dev, asset management | `finance-core` |
| Infra / energy / data-center / project finance, AI-infra finance | `project-finance-solar` |
| Data analytics, BizOps, FP&A-analytics, fintech ops | `data-analytics` |
| Growth or marketing analytics, consumer/tech strategy | `finance-marketing` |

Run `python3 tailor.py --list <variant>` and copy "old" lines exactly from that output.

## 2. Write 3–6 edits
- Rewrite only experience/project bullets and the skills line. Never touch the header, education, titles, employers or dates.
- Each new bullet must be **no longer than the original** (check the char count from `--list`) so the page stays at one.
- Use the posting's vocabulary only where it truthfully describes the same work (e.g. "investment briefs" → "investment memos"). Never add a tool, deal, responsibility or result Sam didn't do.
- Numbers, credentials and employer names must already appear in his resumes. The claims gate stops the run otherwise. If it fails, remove the claim; never reword to sneak it past.
- Reordering items within the skills line is fine; adding new skills is not.
- Each edit needs a one-line `why` tied to a phrase in the posting.

## 3. Cover letter (3 paragraphs, under 330 words)
1. The role, who Sam is (Fordham Gabelli MBA Finance, STEM; JPMorgan AM, Lenovo, Thomson Reuters), and one specific reason for this company drawn from the posting or company description.
2. The two most relevant proofs from his real experience, with their real numbers.
3. How that maps to the team's work; a short close.
No invented numbers, no claims of years in banking/PE, no visa discussion, no relocation promises. Greeting: "Dear <Company> <Team> Team," when the team is clear.

## 4. Outreach note (under 600 characters)
To a team member or recruiter: who Sam is, that he applied (or is applying) for <role>, one relevant proof, and a request for a 15-minute chat. Leave "[Name]" for Sam to fill in.

## 5. Plan file
```json
{"company": "...", "role": "...", "variant": "...", "job_url": "...",
 "edits": [{"old": "...", "new": "...", "why": "..."}],
 "cover_letter": {"greeting": "...", "paragraphs": ["...", "...", "..."]}}
```
Run: `python3 tailor.py plan.json --out out/<Company>`. Exit 2 = claims gate, exit 3 = too long. Fix and rerun (at most twice); if it still fails, skip drafting and say why.
