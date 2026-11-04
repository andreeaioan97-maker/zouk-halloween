#!/usr/bin/env python3
"""Validate this checkout; publish only with --publish and a commit message.

Alex's github-publish-automation script, unchanged except for one addition (Andreea's
setup): every --publish attempt writes its result to <git dir>/publish-last.json (never
committed, never served), which Personal App's dashboard reads for each repo."""
import argparse
from datetime import datetime
import fcntl
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(*args, capture=False):
    result = subprocess.run(args, cwd=ROOT, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else None


def publish(args):
    if run('git', 'branch', '--show-current', capture=True) != 'main':
        raise RuntimeError('Publish requires the main branch; no branch was changed.')
    for marker in ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-merge', 'rebase-apply'):
        path = Path(run('git', 'rev-parse', '--git-path', marker, capture=True))
        if (ROOT / path).exists():
            raise RuntimeError('Finish or resolve the active Git operation first.')
    if run('git', 'ls-files', '--unmerged', capture=True):
        raise RuntimeError('Resolve merge conflicts first.')
    config = json.loads((ROOT / 'automations/publish.json').read_text())
    owner_repo = config['repository']
    allowed = {f'https://github.com/{owner_repo}.git', f'https://github.com/{owner_repo}',
               f'git@github.com:{owner_repo}.git'}
    for mode in ([], ['--push']):
        urls = run('git', 'remote', 'get-url', *mode, '--all', 'origin', capture=True).splitlines()
        if len(urls) != 1 or urls[0] not in allowed:
            raise RuntimeError('origin does not match the configured GitHub repository.')
    run('git', 'status', '--short', '--branch')
    run('git', 'diff', '--check')
    run('git', 'diff', '--cached', '--check')
    checks = config.get('checks')
    if not isinstance(checks, list):
        raise RuntimeError('Configure checks as a list of command argument lists.')
    if not checks:
        scaffold = {'README.md', '.gitignore', 'AGENTS.md', 'automations/publish.json',
                    'automations/publish-main.md', 'scripts/publish.py'}
        files = set(run('git', 'ls-files', '--cached', '--others', '--exclude-standard', capture=True).splitlines())
        if files - scaffold:
            raise RuntimeError('Project files were added. Configure project checks in automations/publish.json first.')
    for command in checks:
        if not isinstance(command, list) or not command or not all(isinstance(x, str) and x for x in command):
            raise RuntimeError('Each check must be a nonempty list of command arguments.')
        run(*command)
    if not args.publish:
        print('Validation passed. No files staged, committed, or pushed.')
        return
    if not args.message or not args.message.strip():
        raise RuntimeError('--publish requires a nonempty --message.')
    # Fetch explicitly; never pull, merge, rebase, or force-push automatically.
    run('git', 'fetch', 'origin', 'refs/heads/main:refs/remotes/origin/main')
    ancestor = subprocess.run(['git', 'merge-base', '--is-ancestor', 'origin/main', 'HEAD'], cwd=ROOT)
    if ancestor.returncode:
        raise RuntimeError('Local main is behind or diverged from origin/main. Resolve before publishing.')
    # --publish means the caller has reviewed ALL nonignored pending changes.
    run('git', 'add', '--all')
    run('git', 'diff', '--cached', '--check')
    staged = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=ROOT)
    if staged.returncode == 1:
        run('git', 'commit', '-m', args.message)
    elif staged.returncode != 0:
        raise RuntimeError('Could not inspect staged changes.')
    if run('git', 'status', '--porcelain', capture=True):
        raise RuntimeError('Files changed during publishing; review and retry. Nothing pushed.')
    run('git', 'push', 'origin', 'HEAD:refs/heads/main')
    print('Published main:', run('git', 'rev-parse', 'HEAD', capture=True))
    record('ok', commit=run('git', 'rev-parse', '--short', 'HEAD', capture=True))


def record(result, commit=None, error=None):
    """Last --publish attempt, for the Personal App dashboard (GET /api/backup)."""
    try:
        git_dir = Path(run('git', 'rev-parse', '--absolute-git-dir', capture=True))
        (git_dir / 'publish-last.json').write_text(json.dumps({
            'at': datetime.now().astimezone().isoformat(timespec='seconds'),
            'result': result, 'commit': commit, 'error': error}, indent=2) + '\n')
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publish', action='store_true', help='Stage ALL reviewed changes, commit, and push main')
    parser.add_argument('--message', help='Commit message for reviewed changes')
    args = parser.parse_args()
    git_dir = Path(run('git', 'rev-parse', '--absolute-git-dir', capture=True))
    with (git_dir / 'orca-publish.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another publish script is running.')
        publish(args)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f'Publish stopped: {exc}', file=sys.stderr)
        if '--publish' in sys.argv:
            record('failed', error=str(exc))
        sys.exit(1)
