"""Read-only HTTPS checks: python scripts/staging_smoke.py https://platform.example https://tenant.example"""
import argparse
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import requests


class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'link' and attrs.get('rel') == 'stylesheet':
            self.urls.append(attrs.get('href', ''))
        if tag == 'script' and attrs.get('src'):
            self.urls.append(attrs['src'])


def check(base):
    parsed = urlsplit(base)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'', '/'}:
        raise ValueError('Supply an HTTPS origin without credentials, query or fragment.')
    base = base.rstrip('/')
    session = requests.Session()
    for path in ['/health/', '/', '/login/']:
        response = session.get(base + path, timeout=20, allow_redirects=False)
        response.raise_for_status()
        if response.status_code != 200:
            raise RuntimeError(f'{path}: expected 200, received {response.status_code}')
        if path == '/health/' and response.json() != {'status': 'ok'}:
            raise RuntimeError('Unexpected database health response')
        if path == '/login/' and 'csrfmiddlewaretoken' not in response.text:
            raise RuntimeError('Login form is missing CSRF protection')
        if path != '/health/':
            if 'max-age=' not in response.headers.get('Strict-Transport-Security', ''):
                raise RuntimeError('HSTS header missing')
            assets = Assets()
            assets.feed(response.text)
            for asset in assets.urls:
                target = urljoin(base + path, asset)
                if urlsplit(target).netloc != parsed.netloc:
                    raise RuntimeError('Unexpected third-party asset dependency')
                result = session.get(target, timeout=20, allow_redirects=False)
                result.raise_for_status()
                if result.status_code != 200 or 'text/html' in result.headers.get('Content-Type', ''):
                    raise RuntimeError('Static asset is unavailable or returns HTML')
        print(f'PASS {base}{path}')
    for cookie in session.cookies:
        if cookie.name in {'csrftoken', 'sessionid'} and not cookie.secure:
            raise RuntimeError('Authentication/CSRF cookie is not secure')
    print('Authenticated login, worker jobs, uploads and backup restoration require the runbook checks.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('origins', nargs='+')
    args = parser.parse_args()
    for origin in args.origins:
        check(origin)
