---
name: github-publish-automation
description: Set up an Orca scheduled GitHub publishing automation with validation and routine publishing-script repair for an existing repository.
---

# GitHub publishing automation

Use when the user requests scheduled publishing in Orca. Installing this skill alone
is not authorization to enable publishing. Operate in the target project's Orca
workspace, follow its instructions, and preserve existing files and automations.
The bundled assets are relative to this SKILL.md; resolve them before changing context.

## Set up

1. Inspect the checkout, AGENTS.md, Git status, branch, origin fetch/push URLs, and
   existing automation configuration. Require a GitHub repository with main and
   origin/main already established; do not silently switch branches or remotes.
   Verify Git identity and GitHub authentication. This helper requires Python 3,
   Git, and a Unix-like environment (it uses fcntl).
2. Establish the intended repository, time and timezone. Propose daily 01:00 in
   the user's timezone when unspecified, and resolve the timezone before enabling.
   Explain that the scheduled agent may commit and push ALL reviewed nonignored
   changes, and repair routine publishing-script problems. The scheduler host
   needs to be awake; use a five-minute missed-run grace period.
3. Copy assets/publish.py to scripts/publish.py and assets/publish-main.md to
   automations/publish-main.md. If those files exist, inspect and reconcile them
   instead of overwriting. Create or merge automations/publish.json with:

   {"repository": "OWNER/REPO", "checks": [["python3", "-m", "unittest", "discover", "-s", "tests", "-v"]]}

   Replace the example checks with the project's actual meaningful validation
   commands, each an argument array. Never use no-op checks. Empty checks are
   supported only for the script's minimal empty-project scaffold.
4. Add a short publishing section to the target AGENTS.md preserving all existing
   instructions: follow automations/publish-main.md, review all pending files and
   outgoing commits, maintain meaningful checks, and use scripts/publish.py.
   Record the authorized schedule and routine repair scope.
5. Run python3 scripts/publish.py (validation only). Resolve routine setup issues
   and validate repairs; stop on unresolved checks or ambiguous changes. Setting
   up the schedule does not require an immediate commit or push.
6. Resolve the installed Orca CLI (ORCA_CLI_COMMAND if set; commonly orca-ide on
   Linux or orca elsewhere). Load its version-matched guide with
   `<cli> skills get orca-cli`; follow that guide for the actual command syntax.
   Inspect automations list before creating anything. Reuse an exact matching
   project automation; resolve ambiguous matches rather than duplicating them.
   Create an enabled daily Codex automation in the existing target checkout with
   a fresh session and the agreed schedule, using this pointer prompt:

   Read AGENTS.md and automations/publish-main.md in this workspace. Follow the
   publishing workflow, including project checks and routine script maintenance.
   This scheduled run or Run now authorizes publishing reviewed suitable changes
   to origin/main. Stop if instructions are missing. Report the commit link or blocker.

7. Read the automation back and verify its workspace, enabled state, provider,
   schedule, timezone, grace period and prompt. Report files, validation, automation
   ID and schedule. Do not claim success if registration or validation failed.

## Repair boundaries

Self-healing is agent-guided routine script maintenance followed by meaningful
validation. It does not authorize arbitrary application changes to pass checks.
Never weaken checks, change the target, force-push, discard changes, automatically
merge/rebase, or publish during concurrent edits. Stop for authentication errors,
branch protection, conflicts, unclear changes, or unresolved test failures. Inspect
any local commit left by a failed push before retrying. Keep the automation prompt
as a pointer so future versioned workflow fixes take effect on the next run.
