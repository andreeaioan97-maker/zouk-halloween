Review git status, staged and unstaged diffs, untracked file contents, and local
commits ahead of origin/main. Confirm main and the repository in publish.json.
If there are no pending changes or outgoing commits, report nothing to publish.
Do not publish secrets, local runtime state, unclear changes, or concurrent edits.

Run python3 scripts/publish.py. When application files have been introduced, add
appropriate project checks to automations/publish.json before publishing. Routine
script maintenance is authorized; validate any fix. Do not weaken checks or change
the remote target. Stop for unresolved check failures, authentication errors, branch
protection, or conflicts. Never force-push, discard changes, or automatically rebase.

After successful review and validation, run:
python3 scripts/publish.py --publish --message "<descriptive commit message>"
This stages ALL nonignored changes. The nightly schedule and Run now both authorize
publishing reviewed suitable changes; no routine confirmation is required.
A failed push may leave a local commit; inspect before retrying.
Report the commit link, validation, script repairs, and any blocker.
