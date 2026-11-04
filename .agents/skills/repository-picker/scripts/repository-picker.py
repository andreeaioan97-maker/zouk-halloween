#!/usr/bin/env python3
"""List GitHub repositories and clone/register a selected repository in Orca."""
import argparse
import fcntl
import importlib.util
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('project_creator_helpers', ROOT / 'scripts/create-project.py')
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)
STATE = ROOT / 'local/repository-picker'


def identity(url):
    if not isinstance(url, str):
        return None
    match = re.fullmatch(r'(?:https://github\.com/|ssh://git@github\.com/|git@github\.com:|github\.com/)([^/\s]+/[^/\s]+?)(?:\.git)?/?', url, flags=re.I)
    return match.group(1).lower() if match else None


def validate_repository(repository):
    if not isinstance(repository, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}', repository):
        raise ValueError('Choose a GitHub repository in OWNER/NAME format.')
    if repository.split('/')[1] in ('.', '..'):
        raise ValueError('Invalid repository name.')
    return repository


def registrations():
    exe = helpers.orca_command()
    helpers.orca(exe, 'skills', 'get', 'orca-cli')
    result = helpers.orca(exe, 'repo', 'list')
    if not isinstance(result.get('repos'), list):
        raise RuntimeError('Orca returned an unsupported project list; nothing imported.')
    registered = {}
    for row in result['repos']:
        remote = row.get('gitRemoteIdentity') or {}
        key = identity(remote.get('canonicalKey')) or identity(remote.get('remoteUrl'))
        if not key and row.get('path') and Path(row['path']).is_dir():
            probe = helpers.command('git', 'remote', 'get-url', 'origin', cwd=row['path'], check=False)
            if probe.returncode == 0:
                key = identity(probe.stdout.strip())
        if key:
            registered.setdefault(key, []).append({'id': row['id'], 'path': row.get('path'), 'name': row.get('displayName')})
    return registered


def list_repositories(scope='owned'):
    if scope not in ('owned', 'accessible'):
        raise ValueError('Scope must be owned or accessible.')
    affiliation = 'owner' if scope == 'owned' else 'owner,collaborator,organization_member'
    pages = json.loads(helpers.output('gh', 'api', '--hostname', 'github.com', '--paginate', '--slurp',
                                     f'user/repos?affiliation={affiliation}&per_page=100&sort=full_name'))
    registered = registrations()
    rows = {}
    for page in pages:
        if not isinstance(page, list):
            raise RuntimeError('GitHub returned an unexpected repository list.')
        for repo in page:
            name = validate_repository(repo['full_name'])
            rows[name.lower()] = {'repository': name, 'description': repo.get('description') or '',
                                 'url': 'https://github.com/' + name, 'private': bool(repo['private']),
                                 'archived': bool(repo.get('archived')), 'fork': bool(repo.get('fork')),
                                 'added': name.lower() in registered,
                                 'orca_projects': registered.get(name.lower(), [])}
    return {'scope': scope, 'repositories': sorted(rows.values(), key=lambda row: row['repository'].lower())}


def verify_checkout(path, repository):
    if path.is_symlink() or not path.is_dir() or not (path / '.git').exists():
        raise RuntimeError(f'Destination exists but is not a Git checkout: {path}')
    root = Path(helpers.output('git', 'rev-parse', '--show-toplevel', cwd=path)).resolve()
    if root != path.resolve():
        raise RuntimeError('Destination is not the root of its Git checkout.')
    remote = helpers.output('git', 'remote', 'get-url', 'origin', cwd=path)
    if identity(remote) != repository.lower():
        raise RuntimeError(f'Destination belongs to another repository: {path}')


def add_repository(repository, parent=None, path=None):
    repository = validate_repository(repository)
    if parent and path:
        raise ValueError('Choose a parent folder or an existing clone path, not both.')
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / 'import.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another repository is being added; wait for it to finish.')
        existing = registrations().get(repository.lower())
        if existing:
            return {'repository': repository, 'status': 'already_added', 'orca_projects': existing}
        info = helpers.remote_info(repository)
        if not info or info.get('full_name', '').lower() != repository.lower():
            raise RuntimeError('GitHub repository not found or not accessible with the current login.')
        repository = info['full_name']
        # owner/name avoids collisions between repositories from different owners.
        target = Path(path).expanduser() if path else Path(parent or Path.home() / 'projects').expanduser() / repository
        if target.is_symlink():
            raise RuntimeError('Choose the real checkout path rather than a symlink.')
        target = target.resolve()
        if target == ROOT or ROOT in target.parents:
            raise ValueError('Choose a destination outside this environment repository.')
        cloned = False
        if target.exists():
            verify_checkout(target, repository)
        else:
            if path:
                raise ValueError('--path must name an existing checkout; use --parent for a new clone.')
            target.parent.mkdir(parents=True, exist_ok=True)
            helpers.output('gh', 'repo', 'clone', repository, str(target))
            cloned = True
            verify_checkout(target, repository)
        helpers.orca(helpers.orca_command(), 'repo', 'add', '--path', str(target))
        found = registrations().get(repository.lower(), [])
        if not any(row.get('path') and Path(row['path']).resolve() == target for row in found):
            raise RuntimeError(f'Clone is available at {target}, but Orca registration could not be verified. Retry after inspecting Orca.')
        return {'repository': repository, 'url': 'https://github.com/' + repository,
                'status': 'added', 'path': str(target), 'cloned': cloned, 'orca_projects': found}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    listing = sub.add_parser('list')
    listing.add_argument('--scope', choices=['owned', 'accessible'], default='owned')
    adding = sub.add_parser('add')
    adding.add_argument('--repository', required=True)
    dest = adding.add_mutually_exclusive_group()
    dest.add_argument('--parent')
    dest.add_argument('--path')
    form = sub.add_parser('form')
    form.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if args.action == 'form':
        form_spec = importlib.util.spec_from_file_location('repository_picker_form', ROOT / 'scripts/repository-picker-form.py')
        module = importlib.util.module_from_spec(form_spec)
        form_spec.loader.exec_module(module)
        module.serve(no_browser=args.no_browser)
        return
    result = list_repositories(args.scope) if args.action == 'list' else add_repository(args.repository, args.parent, args.path)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Repository picker stopped: {exc}', file=sys.stderr)
        sys.exit(1)
