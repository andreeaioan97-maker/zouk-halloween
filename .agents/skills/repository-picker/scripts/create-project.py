#!/usr/bin/env python3
"""Create a private GitHub project and daily 01:00 Orca publishing; preview by default."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / '.agents/skills/project-creator/assets/project'
VINEXT_ASSETS = ROOT / '.agents/skills/project-creator/assets/vinext'
STATE = ROOT / 'local/project-creator'


def command(*args, cwd=None, check=True):
    result = subprocess.run(args, cwd=cwd or ROOT, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=180,
                            env={**os.environ, 'GH_HOST': 'github.com'} if args[0] == 'gh' else None)
    if check and result.returncode:
        raise RuntimeError(f'{args[0]} {args[1]} failed: {result.stderr.strip() or result.stdout.strip()}')
    return result


def output(*args, **kwargs):
    return command(*args, **kwargs).stdout.strip()


def orca_command():
    return os.environ.get('ORCA_CLI_COMMAND') or ('orca-dev' if os.environ.get('ORCA_DEV_REPO_ROOT') else 'orca-ide' if sys.platform.startswith('linux') else 'orca')


def orca(executable, *args):
    data = json.loads(output(executable, *args, '--json'))
    if data.get('ok') is False or data.get('isError'):
        raise RuntimeError(f'Orca refused {args[0]}: {data}')
    return data.get('result', data)


def save(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)


def plan(name, owner=None, parent=None, description='', template='vinext'):
    if template not in ('vinext', 'empty'):
        raise ValueError('Template must be vinext or empty.')
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', name) or name.endswith('.git'):
        raise ValueError('Use a repository name of 1–100 letters, numbers, dots, underscores or hyphens, starting with a letter/number; omit .git.')
    if not isinstance(description, str) or len(description) > 350 or '\x00' in description:
        raise ValueError('Description must contain at most 350 characters.')
    for tool in ('git', 'gh', orca_command()):
        if not shutil.which(tool):
            raise RuntimeError(f'Required executable is missing: {tool}')
    owner = owner or output('gh', 'api', '--hostname', 'github.com', 'user', '--jq', '.login')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}', owner):
        raise ValueError('Invalid GitHub owner.')
    parent = Path(parent or Path.home() / 'projects').expanduser().resolve()
    if parent == ROOT or ROOT in parent.parents:
        raise ValueError('Choose a projects folder outside this repository.')
    return {'name': name, 'owner': owner, 'description': description,
            'repository': f'{owner}/{name}', 'path': str(parent / name),
            'url': f'https://github.com/{owner}/{name}', 'private': True,
            'schedule': '01:00 Europe/Bucharest', 'provider': 'codex',
            'missed_run_grace_minutes': 5, **({'template': template} if template == 'vinext' else {})}


def remote_info(repository):
    result = command('gh', 'api', '--hostname', 'github.com', f'repos/{repository}', check=False)
    if result.returncode:
        if 'HTTP 404' in result.stderr:
            return None
        raise RuntimeError(result.stderr.strip() or 'Unable to inspect GitHub repository.')
    return json.loads(result.stdout)


def verify_private(info, repository):
    if not info or info.get('full_name', '').lower() != repository.lower() or not info.get('private'):
        raise RuntimeError('GitHub repository identity or private visibility could not be verified.')


def seed(path, spec):
    for source in ASSETS.rglob('*'):
        if source.is_file() and '__pycache__' not in source.parts:
            dest = path / source.relative_to(ASSETS)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(source.read_bytes())
    (path / 'README.md').write_text(f"# {spec['name']}\n\n{spec['description']}\n\nNightly publishing runs in Orca at 01:00 Europe/Bucharest using Codex.\nSee `automations/publish-main.md`. Configure application checks in\n`automations/publish.json` when adding code. Keep the scheduler host awake;\nmissed runs have a five-minute grace period.\n")
    (path / 'automations/publish.json').write_text(json.dumps({'repository': spec['repository'], 'checks': []}, indent=2) + '\n')

    if spec.get('template') == 'vinext':
        for source in VINEXT_ASSETS.rglob('*'):
            if source.is_file() and not {'node_modules', 'dist', '.vinext', '.next', 'local', '__pycache__'}.intersection(source.relative_to(VINEXT_ASSETS).parts):
                dest = path / source.relative_to(VINEXT_ASSETS)
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.name == '.gitignore' and dest.exists():
                    dest.write_text(dest.read_text() + source.read_text())
                else:
                    dest.write_bytes(source.read_bytes())
        (path / '.gitignore').write_text((path / '.gitignore').read_text() + '\ndist/\n.vinext/\n*.tsbuildinfo\n')
        (path / 'README.md').write_text(f"# {spec['name']}\n\n{spec['description']}\n\nVinext + React application. See APP.md for startup, shared UI, checks, and agent tools.\n")
        checks = [['npm', 'ci'], ['npm', 'run', 'check'], ['npm', 'run', 'test:browser']]
        (path / 'automations/publish.json').write_text(json.dumps({'repository': spec['repository'], 'checks': checks}, indent=2) + '\n')
        with (path / 'AGENTS.md').open('a') as file:
            file.write('\nThis custom app uses vinext. Read APP.md for commands and shared agent tooling.\n')


def seed_matches(path, spec):
    """Resume only an exact scaffold, including its staged contents."""
    with tempfile.TemporaryDirectory() as directory:
        expected = Path(directory)
        seed(expected, spec)
        files = {str(p.relative_to(expected)): p.read_bytes()
                 for p in expected.rglob('*') if p.is_file()}
        actual = {str(p.relative_to(path)) for p in path.rglob('*')
                  if '.git' not in p.relative_to(path).parts and (p.is_file() or p.is_symlink())}
        if actual != set(files):
            return False
        for name, contents in files.items():
            target = path / name
            if target.is_symlink() or target.read_bytes() != contents:
                return False
        # The original seed stages every file before committing. Reject any
        # index/worktree difference rather than overwriting partial user work.
        staged = output('git', 'diff', '--cached', '--name-only', cwd=path).splitlines()
        return set(staged) == set(files) and command('git', 'diff', '--quiet', cwd=path, check=False).returncode == 0


def create(spec, resume_remote=False):
    STATE.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(spec['repository'].lower().encode()).hexdigest()[:24]
    receipt = STATE / f'{key}.json'
    with (STATE / f'{key}.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('This project is already being created.')
        state = json.loads(receipt.read_text()) if receipt.exists() else {'spec': spec}
        if state['spec'] != spec:
            raise RuntimeError(f'A creation receipt already exists with different details: {receipt}')
        path = Path(spec['path'])
        exe = orca_command()
        # Confirm CLI availability before creating any GitHub resource.
        orca(exe, 'skills', 'get', 'orca-cli')
        orca(exe, 'automations', 'list')
        output('git', 'var', 'GIT_AUTHOR_IDENT')
        output('git', 'var', 'GIT_COMMITTER_IDENT')
        info = remote_info(spec['repository'])
        if not state.get('remote'):
            if info:
                if not (state.get('remote_attempted') and resume_remote):
                    raise RuntimeError('Repository already exists. If a previous creation response was lost, inspect it before retrying with --resume-remote.')
                verify_private(info, spec['repository'])
                if info.get('size', 0) != 0:
                    raise RuntimeError('Refusing to adopt a nonempty repository after an uncertain creation.')
            else:
                if path.exists():
                    raise RuntimeError(f'Destination already exists: {path}')
                state['remote_attempted'] = True
                save(receipt, state)
                output('gh', 'repo', 'create', spec['repository'], '--private', '--description', spec['description'])
                info = remote_info(spec['repository'])
            verify_private(info, spec['repository'])
            state['remote'] = True
            save(receipt, state)
        verify_private(info, spec['repository'])
        if not state.get('local'):
            # An interrupted clone is left intact for inspection; never overwrite it.
            if path.exists():
                raise RuntimeError(f'Incomplete checkout exists at {path}; inspect it before recovery. Nothing deleted.')
            path.parent.mkdir(parents=True, exist_ok=True)
            output('gh', 'repo', 'clone', spec['repository'], str(path))
            state['local'] = True
            save(receipt, state)
        if not (path / '.git').exists():
            raise RuntimeError('Recorded checkout is missing its .git directory.')
        remote = output('git', 'remote', 'get-url', 'origin', cwd=path)
        if remote not in (spec['url'], spec['url'] + '.git', f"git@github.com:{spec['repository']}.git"):
            raise RuntimeError('Recorded checkout has an unexpected origin.')
        if not state.get('seeded'):
            if command('git', 'rev-parse', '--verify', 'HEAD', cwd=path, check=False).returncode == 0:
                raise RuntimeError('Checkout is no longer empty; inspect partial initialization before recovery.')
            dirty = bool(output('git', 'status', '--porcelain', cwd=path))
            if dirty and not seed_matches(path, spec):
                raise RuntimeError('Checkout differs from the starter scaffold; inspect partial initialization before recovery.')
            # Source-repository identity can be local rather than global. Copy
            # only missing values into this newly created checkout, never global config.
            for key in ('user.name', 'user.email'):
                if not command('git', 'config', '--get', key, cwd=path, check=False).stdout.strip():
                    value = command('git', 'config', '--get', key, check=False).stdout.strip()
                    if value:
                        output('git', 'config', '--local', key, value, cwd=path)
            output('git', 'var', 'GIT_AUTHOR_IDENT', cwd=path)
            output('git', 'var', 'GIT_COMMITTER_IDENT', cwd=path)
            output('git', 'symbolic-ref', 'HEAD', 'refs/heads/main', cwd=path)
            if not dirty:
                seed(path, spec)
            output('git', 'add', '--all', cwd=path)
            output('git', 'diff', '--cached', '--check', cwd=path)
            output('git', 'commit', '-m', 'Initialize project and nightly publishing workflow', cwd=path)
            state['seeded'] = True
            save(receipt, state)
        if not state.get('pushed'):
            output('git', 'push', '-u', 'origin', 'main', cwd=path)
            state['pushed'] = True
            save(receipt, state)
        if not state.get('registered'):
            orca(exe, 'repo', 'add', '--path', str(path))
            state['registered'] = True
            save(receipt, state)
        name = f"Publish {spec['repository']} nightly"
        result = orca(exe, 'automations', 'list')
        rows = result.get('automations', result.get('items', []))
        matches = [row for row in rows if row.get('name') == name]
        if len(matches) > 1:
            raise RuntimeError('Multiple matching automations exist; inspect them before continuing.')
        if matches:
            existing = matches[0]
            if existing.get('runContext', {}).get('path') != str(path) or existing.get('workspaceMode') != 'existing':
                raise RuntimeError('Matching automation points to a different workspace.')
            state['automation_id'] = existing['id']
        elif not state.get('automation_id'):
            result = orca(exe, 'automations', 'create', '--name', name,
                          '--trigger', 'daily', '--time', '01:00', '--timezone', 'Europe/Bucharest',
                          '--enabled', '--missed-run-grace-minutes', '5', '--provider', 'codex',
                          '--workspace', 'path:' + str(path), '--fresh-session',
                          '--prompt', 'Read AGENTS.md and automations/publish-main.md in this workspace. Follow the publishing workflow, including project checks and routine script maintenance. This scheduled run or Run now authorizes publishing reviewed suitable changes to origin/main. Stop if instructions are missing. Report the commit link or blocker.')
            state['automation_id'] = result['automation']['id']
        else:
            raise RuntimeError('The recorded automation was removed. Inspect before recreating it.')
        save(receipt, state)
        automation = orca(exe, 'automations', 'show', state['automation_id']).get('automation', {})
        if not (automation.get('enabled') and automation.get('agentId') == 'codex'
                and automation.get('timezone') == 'Europe/Bucharest'
                and automation.get('rrule') == 'FREQ=DAILY;BYHOUR=1;BYMINUTE=0'
                and automation.get('missedRunGraceMinutes') == 5):
            raise RuntimeError('Automation exists but its schedule/provider differs from the requested setup; inspect it.')
        return {**spec, 'automation_id': state['automation_id'], 'receipt': str(receipt)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', required=True)
    parser.add_argument('--owner')
    parser.add_argument('--parent')
    parser.add_argument('--description', default='')
    parser.add_argument('--template', choices=['vinext', 'empty'], default='vinext')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--resume-remote', action='store_true')
    args = parser.parse_args()
    spec = plan(args.name, args.owner, args.parent, args.description, args.template)
    print(json.dumps(create(spec, args.resume_remote) if args.apply else {'preview': True, **spec}, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f'Project creation stopped: {exc}', file=sys.stderr)
        sys.exit(1)
