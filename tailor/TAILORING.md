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

## Accuracy guardrails (Sam's standing rules — these override the posting's vocabulary)
- **JPMorgan:** the work was marketing-channel budget allocation, not securities investing or deal diligence. Never call it investing, deal work or "investment memos"; keep "investment briefs" only as he wrote it. In cover letters, describe it as budget/capital allocation across marketing channels.
- **Lenovo automation:** he owned the mapping, QA and problem identification, not the coding or bot build.
- **Thomson Reuters:** an operational execution role. Don't turn it into a process-improvement or transformation story beyond his own bullets.
- **Music sponsorship:** he negotiated and managed a sponsorship deal end to end. He did not found a record label.
- **Research paper:** the sample was about 466 (convenience sample) and the findings are associations, not causation. Never write "1,000+".
- **No deal experience:** SJM and Nautilus Solar are MBA coursework/projects. Never imply live deals, closed transactions or a deal team.
- He did not work at De Anda.
- Honest bridge: forecasting, budgeting and analytics are the truthful route into FP&A and post-close portfolio work.
`tailor.py` hard-blocks the most common violations, but these rules apply to every sentence. If he couldn't defend a line under follow-up questions, don't write it.

## 2. Write 3–6 edits
- Rewrite only experience/project bullets and the skills line. Never touch the header, education, titles, employers or dates.
- Each new bullet must be **no longer than the original** (check the char count from `--list`) so the page stays at one.
- Use the posting's vocabulary only where it truthfully describes the same work (e.g. "budget reallocation" → "capital allocation" for his Lenovo planning work). Never add a tool, deal, responsibility or result Sam didn't do.
- Numbers, credentials and employer names must already appear in his resumes. The claims gate stops the run otherwise. If it fails, remove the claim; never reword to sneak it past.
- Reordering items within the skills line is fine; adding new skills is not.
- Each edit needs a one-line `why` tied to a phrase in the posting.

## 3. Cover letter (3 paragraphs, under 330 words)
1. The role, who Sam is (Fordham Gabelli MBA Finance, STEM; JPMorgan AM, Lenovo, Thomson Reuters), and one specific reason for this company drawn from the posting or company description.
2. The two most relevant proofs from his real experience, with their real numbers.
3. How that maps to the team's work; a short close.
No invented numbers, no claims of years in banking/PE, no visa discussion, no relocation promises.
Write like Sam: plain, conversational, no em dashes, no AI-sounding phrases ("I am thrilled", "passionate", "leverage", "synergy"). Greeting: "Dear <Company> <Team> Team," when the team is clear.

## 4. Outreach note (under 600 characters)
To a team member or recruiter: who Sam is, that he applied (or is applying) for <role>, one relevant proof, and a request for a 15-minute chat. Leave "[Name]" for Sam to fill in.

## 5. Plan file
```json
{"company": "...", "role": "...", "variant": "...", "job_url": "...",
 "edits": [{"old": "...", "new": "...", "why": "..."}],
 "cover_letter": {"greeting": "...", "paragraphs": ["...", "...", "..."]}}
```
Run: `python3 tailor.py plan.json --out out/<Company>`. Exit 2 = claims gate, exit 3 = too long. Fix and rerun (at most twice); if it still fails, skip drafting and say why.
