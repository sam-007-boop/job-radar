# job-radar

Every morning at about 6:30am ET, this checks the public job boards of Sam's target companies and saves the finance roles posted **today or yesterday** to `data/fresh.md`. Nothing older is ever reported.

- **What it reads:** public job listings on Greenhouse, Lever, Ashby and Workday. It never logs in or applies anywhere.
- **What to edit:** `watchlist.yaml`. Add a company under `verified` when you know its job-board link, or under `probe` with a few guesses and the next run reports which one worked (`data/probe-report.md`).
- **Run it now:** Actions tab → job-radar → Run workflow.
- **Results:** `data/fresh.md` (readable) and `data/fresh.json` (read by Claude's morning task, which checks sponsorship, scores each role and adds it to Sam's Job Pipeline).
