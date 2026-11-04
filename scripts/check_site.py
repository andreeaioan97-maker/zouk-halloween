#!/usr/bin/env python3
"""Site check for the GitHub Pages site served from the repo root of main.

For every HTML file that would be published (tracked or untracked, not ignored):
- it parses, and its non-void elements open/close in a balanced way;
- every local reference (src, href, srcset, poster, data, CSS url()) points to a
  file that exists and would be published (i.e. is not git-ignored);
- every same-page "#fragment" link points to an existing id.
Every published image (png/jpg/gif/webp/ico) has a valid file signature and
every SVG parses as XML. Also requires index.html and .nojekyll at the root. Read-only: never writes files.
Run with: python3 -I scripts/check_site.py
"""
from html.parser import HTMLParser
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
        'meta', 'param', 'source', 'track', 'wbr'}
# Elements whose end tag HTML allows to be omitted; skip them in balance checks.
OPTIONAL_END = {'p', 'li', 'dt', 'dd', 'tr', 'td', 'th', 'thead', 'tbody', 'tfoot',
                'option', 'optgroup', 'rt', 'rp', 'colgroup', 'caption'}
REF_ATTRS = {'src', 'href', 'poster', 'data', 'action'}
CSS_URL = re.compile(r'url\(\s*([\'"]?)(.*?)\1\s*\)')


def published_files():
    out = subprocess.run(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
                         cwd=ROOT, check=True, capture_output=True, text=True).stdout
    return {p for p in out.split('\0') if p and (ROOT / p).is_file()}


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.refs, self.ids, self.errors, self.stack = [], set(), [], []
        self.in_style = False

    def handle_starttag(self, tag, attrs):
        self._attrs(tag, attrs)
        if tag not in VOID and tag not in OPTIONAL_END:
            self.stack.append((tag, self.getpos()[0]))
        self.in_style = tag == 'style'

    def handle_startendtag(self, tag, attrs):
        self._attrs(tag, attrs)

    def handle_endtag(self, tag):
        self.in_style = False
        if tag in VOID or tag in OPTIONAL_END:
            return
        if not self.stack or self.stack[-1][0] != tag:
            open_tag = self.stack[-1] if self.stack else None
            self.errors.append(f'line {self.getpos()[0]}: </{tag}> does not close '
                               + (f'<{open_tag[0]}> from line {open_tag[1]}' if open_tag else 'any open element'))
            if any(t == tag for t, _ in self.stack):
                while self.stack and self.stack.pop()[0] != tag:
                    pass
            return
        self.stack.pop()

    def handle_data(self, data):
        if self.in_style:
            for m in CSS_URL.finditer(data):
                self.refs.append((self.getpos()[0], m.group(2)))

    def _attrs(self, tag, attrs):
        line = self.getpos()[0]
        for name, value in attrs:
            if value is None:
                continue
            if name in ('id', 'name') and (name == 'id' or tag == 'a'):
                self.ids.add(value)
            if name in REF_ATTRS:
                self.refs.append((line, value))
            elif name == 'srcset':
                for part in value.split(','):
                    if part.strip():
                        self.refs.append((line, part.strip().split()[0]))
            elif name == 'style':
                for m in CSS_URL.finditer(value):
                    self.refs.append((line, m.group(2)))


def check_page(rel, files):
    errors = []
    page = Page()
    try:
        page.feed((ROOT / rel).read_text(encoding='utf-8'))
        page.close()
    except Exception as exc:  # unreadable / undecodable file
        return [f'{rel}: cannot parse: {exc}']
    errors += [f'{rel}: {e}' for e in page.errors]
    errors += [f'{rel}: line {line}: <{tag}> is never closed' for tag, line in page.stack]
    for line, ref in page.refs:
        ref = ref.strip()
        parts = urlsplit(ref)
        if parts.scheme or ref.startswith('//') or not ref or ref.startswith(('mailto:', 'tel:', 'data:', 'javascript:')):
            continue
        if not parts.path:
            frag = unquote(parts.fragment)
            if frag and frag not in page.ids:
                errors.append(f'{rel}: line {line}: link #{frag} has no matching id')
            continue
        path = unquote(parts.path)
        base = Path('.') if path.startswith('/') else Path(rel).parent
        target = (base / path.lstrip('/')).as_posix()
        target = Path(target)
        norm = []
        for piece in target.parts:
            if piece == '..':
                if not norm:
                    errors.append(f'{rel}: line {line}: {ref} points outside the site')
                    break
                norm.pop()
            elif piece != '.':
                norm.append(piece)
        else:
            candidate = '/'.join(norm)
            if path.endswith('/') or (candidate and (ROOT / candidate).is_dir()) or not candidate:
                candidate = (candidate + '/index.html').lstrip('/')
            if candidate not in files:
                exists = (ROOT / candidate).exists()
                why = 'is git-ignored, so it would not be published' if exists else 'does not exist'
                errors.append(f'{rel}: line {line}: {ref} -> {candidate} {why}')
    return errors


SIGNATURES = {'.png': (b'\x89PNG\r\n\x1a\n',), '.jpg': (b'\xff\xd8\xff',), '.jpeg': (b'\xff\xd8\xff',),
              '.gif': (b'GIF87a', b'GIF89a'), '.webp': (b'RIFF',), '.ico': (b'\x00\x00\x01\x00',)}


def check_image(rel):
    suffix = Path(rel).suffix.lower()
    data = (ROOT / rel).read_bytes()
    if suffix == '.svg':
        import xml.etree.ElementTree as ET
        try:
            root = ET.fromstring(data)
        except ET.ParseError as exc:
            return [f'{rel}: SVG does not parse: {exc}']
        return [] if root.tag.endswith('svg') else [f'{rel}: root element is not <svg>']
    if suffix in SIGNATURES and not data.startswith(SIGNATURES[suffix]):
        return [f'{rel}: not a valid {suffix[1:].upper()} file']
    return []


def main():
    files = published_files()
    errors = [f'missing {name} at the repo root' for name in ('index.html', '.nojekyll') if name not in files]
    pages = sorted(f for f in files if f.lower().endswith(('.html', '.htm'))
                   and not f.startswith(('.agents/', '.claude/')))
    for rel in pages:
        errors += check_page(rel, files)
    for rel in sorted(files):
        if Path(rel).suffix.lower() in set(SIGNATURES) | {'.svg'} and not rel.startswith(('.agents/', '.claude/')):
            errors += check_image(rel)
    if errors:
        print('Site check failed:', *errors, sep='\n  ', file=sys.stderr)
        return 1
    print(f'Site check passed: {len(pages)} HTML file(s), all local references resolve; images valid.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
