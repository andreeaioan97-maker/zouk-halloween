# zouk-halloween

Static site, public on GitHub Pages (main, repo root).

## Instruction files need Andreea's approval
Never write rules or add anything to this file (or any agent instruction file) without telling Andreea and getting her approval first. Keep this file small: important decisions only.

## Publishing
- Only the Orca automation "Publish zouk-halloween" (daily 01:20 Romania time) commits and pushes, following `automations/publish-main.md`. Agents never commit or push by hand.
- Keep the checks in `automations/publish.json` (`scripts/check_site.py`); never weaken them. Allowed repairs: the publishing script only.
