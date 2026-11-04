#!/usr/bin/env python3
"""Local-only picker for GitHub repositories. Stop with Ctrl+C when finished."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import secrets
from urllib.parse import parse_qs, urlsplit
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('repository_picker', ROOT / 'scripts/repository-picker.py')
picker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(picker)


def make_server(port=0):
    token = secrets.token_urlsafe(32)
    template = (ROOT / 'assets/form.html').read_text()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Do not log the URL's session token.

        def reply(self, code, body, content_type='application/json'):
            data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(data)

        def valid_host(self):
            return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'

        def do_GET(self):
            url = urlsplit(self.path)
            if not self.valid_host() or url.path != '/' or parse_qs(url.query).get('token') != [token]:
                return self.reply(403, {'error': 'Open the URL printed by repository-picker.py form.'})
            self.reply(200, template.replace('__TOKEN__', token), 'text/html; charset=utf-8')

        def do_POST(self):
            origin = f'http://127.0.0.1:{self.server.server_port}'
            if (not self.valid_host() or self.path != '/action'
                    or self.headers.get('Origin') != origin
                    or not secrets.compare_digest(self.headers.get('X-Project-Token', ''), token)):
                return self.reply(403, {'error': 'Invalid local form session.'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 8192 or self.headers.get('Content-Type') != 'application/json':
                    raise ValueError('Invalid form request.')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('Invalid request.')
                if data.get('action') == 'list':
                    result = picker.list_repositories(data.get('scope', 'owned'))
                elif data.get('action') == 'add':
                    for field in ('repository', 'parent', 'path'):
                        if not isinstance(data.get(field, ''), str):
                            raise ValueError('Form fields must be text.')
                    result = picker.add_repository(data.get('repository', ''),
                                                   data.get('parent') or None, data.get('path') or None)
                else:
                    raise ValueError('Unknown action.')
                self.reply(200, result)
            except Exception as exc:
                self.reply(400, {'error': str(exc)})

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    return server, f'http://127.0.0.1:{server.server_port}/?token={token}'


def serve(no_browser=False):
    server, url = make_server()
    print(f'Repository picker: {url}\nKeep this process running while using the picker. Ctrl+C stops it.', flush=True)
    if not no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    serve()
