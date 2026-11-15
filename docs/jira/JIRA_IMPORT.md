# Import Datachain user stories into Jira (one go)

This folder contains a CSV with **10 epics** and **78 user stories** generated from `ROADMAP.md`.

## Files

| File | Purpose |
| ---- | ------- |
| `datachain-jira-import.csv` | Ready for Jira **CSV import** (88 issues total) |
| `generate_jira_import.py` | Regenerates the CSV after `ROADMAP.md` changes |

Regenerate:

```bash
python docs/jira/generate_jira_import.py
```

## Jira Cloud — CSV import (recommended)

1. In Jira, open your project (or create one, e.g. **DC** / **DATACHAIN**).
2. Go to **Project settings** → **Import** (or use the global **Settings → System → External System Import → CSV** on some plans).
3. Upload `datachain-jira-import.csv`.
4. Map columns:

   | CSV column | Jira field |
   | ---------- | ---------- |
   | Issue Type | Issue Type |
   | Summary | Summary |
   | Description | Description |
   | Epic Name | Epic Name (or Epic Link, depending on project type) |
   | Status | Status |
   | Labels | Labels |
   | Priority | Priority |

5. **Import epics first** if Jira asks to split by issue type. The CSV lists all 10 epics before the 77 stories so epic names exist when stories are linked.
6. Map statuses:
   - `Done` → your project’s Done column (for completed repo work)
   - `To Do` → backlog / to do
7. Run the import and review the backlog board.

### Company-managed vs team-managed projects

- **Company-managed (classic):** use **Epic Name** on Story rows. Epics use issue type **Epic**.
- **Team-managed:** if **Epic Name** is not offered, import epics first, then re-export or use **Parent** with the epic issue key. Alternatively create epics manually and import only the Story rows with **Parent** set to each epic’s key.

### If import fails on Issue Type

Ensure your project scheme includes **Epic** and **Story** (or **User Story**) types. Rename in the CSV if your project uses `User Story` instead of `Story`.

## Optional — REST API bulk upload

If you prefer API upload instead of CSV, use `upload_to_jira.py` (requires a Jira API token):

```bash
set JIRA_BASE_URL=https://your-team.atlassian.net
set JIRA_EMAIL=you@university.edu
set JIRA_API_TOKEN=your-api-token
set JIRA_PROJECT_KEY=DC

python docs/jira/upload_to_jira.py
```

Create an API token: Atlassian account → **Security** → **API tokens**.

The script creates epics first, then stories linked to each epic. It skips issues that already exist (matched by `Roadmap ID` in the description).

## Labels applied

- All issues: `datachain`
- Stories also: milestone labels such as `M1Foundation`, `M3Pipeline`, etc.

## Notes

- **Summary** is shortened to fit Jira; the full user story text is in **Description**.
- Repo implementation notes from `ROADMAP.md` are not duplicated in the CSV (only story text + roadmap ID).
- After import, you can add **Sprint** assignments in Jira using the milestone groupings in `ROADMAP.md` (M1–M6).
