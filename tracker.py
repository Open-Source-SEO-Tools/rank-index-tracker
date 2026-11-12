#!/usr/bin/env python3
"""Rank and Index Tracker: attendee edition. Python 3.10+, standard library only."""
import argparse
import base64
from contextlib import contextmanager
import copy
import csv
from datetime import datetime, timezone
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import secrets
import socket
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
MAX_BYTES = 20_000_000
IMPORT_BYTES = 250_000
MAX_PAGES = 2000
MAX_RECORDS = 20000
MARKETS = {"us": 2840, "uk": 2826, "au": 2036}
ENGINES = ("google", "bing")
PROVIDERS = {"dataforseo-google", "dataforseo-bing", "browser-import", "gsc", "synthetic"}
API = "https://api.dataforseo.com/v3/serp/{}/organic/live/advanced"
GSC_API = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
TOKEN_API = "https://oauth2.googleapis.com/token"
BING_WARNING = "Bing API ranks are unverified. In the authors' October 2026 tests, API results covered the wrong topic and site: returned nothing for large sites. Spot-check in a real browser."


class TrackerError(Exception):
    """An actionable message safe to show without credentials or response bodies."""


def require(condition, message):
    if not condition:
        raise TrackerError(message)


def text(value, maximum=2000, empty=True):
    return isinstance(value, str) and len(value) <= maximum and (empty or bool(value.strip())) and not any(ord(c) < 32 and c not in '\n\t' for c in value)


def http_url(value):
    if not text(value, 8192, False) or any(c.isspace() for c in value):
        return False
    try:
        u = urlsplit(value)
        return u.scheme in ("http", "https") and bool(u.hostname) and not (u.username or u.password) and u.port != 0
    except ValueError:
        return False


def url_identity(value):
    """Ignore scheme and trailing path slashes only; retain host, case, query, fragment."""
    require(http_url(value), "Expected an HTTP or HTTPS URL without credentials.")
    u = urlsplit(value)
    return u.netloc + u.path.rstrip('/') + ('?' + u.query if '?' in value.split('#')[0] else '') + ('#' + u.fragment if '#' in value else '')


def now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def valid_time(value):
    try:
        d = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return d.tzinfo is not None and d.utcoffset().total_seconds() == 0
    except (ValueError, TypeError, AttributeError, OverflowError):
        return False


def time_key(row):
    return datetime.fromisoformat(row['at'].replace('Z', '+00:00'))


def empty_data():
    return {"schema_version": 1, "pages": [], "queries": [], "rank_runs": [], "index_readings": []}


def validate_results(rows, limit=200):
    require(isinstance(rows, list) and len(rows) <= limit, "Invalid results list or too many results.")
    ranks = set()
    for r in rows:
        require(isinstance(r, dict) and type(r.get('rank')) is int and 1 <= r['rank'] <= 200 and r['rank'] not in ranks and http_url(r.get('url')) and text(r.get('title')), "Invalid result rank, URL or title.")
        ranks.add(r['rank'])


def _validate_dataset(data):
    require(isinstance(data, dict) and type(data.get('schema_version')) is int and data['schema_version'] == 1 and not (set(data) - {'schema_version', 'notice', 'pages', 'queries', 'rank_runs', 'index_readings'}), "Invalid data schema. Expected schema_version 1.")
    for key in ('pages', 'queries', 'rank_runs', 'index_readings'):
        require(isinstance(data.get(key), list), f"Invalid data: {key} must be a list.")
    require(len(data['pages']) <= MAX_PAGES and len(data['queries']) <= 200, "Limit is 2,000 pages and 200 queries.")
    seen = set()
    for p in data['pages']:
        require(isinstance(p, dict) and http_url(p.get('url')) and text(p.get('name')) and text(p.get('group'), 200) and type(p.get('mine')) is bool, "Invalid page. Expected url, name, group and mine.")
        key = url_identity(p['url'])
        require(key not in seen, "Duplicate page URL identity.")
        seen.add(key)
    seen = set()
    for q in data['queries']:
        require(isinstance(q, dict) and text(q.get('query'), 700, False) and isinstance(q.get('markets'), list) and bool(q['markets']) and all(m in MARKETS for m in q['markets']) and len(set(q['markets'])) == len(q['markets']), "Invalid query or markets. Use us, uk or au.")
        require(q['query'] not in seen, "Duplicate query.")
        seen.add(q['query'])
    ids = set()
    for kind in ('rank_runs', 'index_readings'):
        require(len(data[kind]) <= MAX_RECORDS, "History limit is 20,000 records per type. Archive older history.")
        for r in data[kind]:
            require(isinstance(r, dict), "Invalid history record.")
            require(text(r.get('id'), 100, False) and r['id'] not in ids and valid_time(r.get('at')) and r.get('engine') in ENGINES and r.get('provider') in PROVIDERS and text(r.get('note')), "Invalid history identity, UTC timestamp, engine, provider or note.")
            ids.add(r['id'])
            if kind == 'rank_runs':
                require(text(r.get('query'), 700, False) and r.get('market') in MARKETS, "Invalid rank query or market.")
                cost = r.get('provider_cost_usd')
                require(cost is None or (type(cost) in (int, float) and math.isfinite(cost) and cost >= 0), "Invalid provider charge.")
                validate_results(r.get('results'))
            else:
                require(http_url(r.get('url')) and (r.get('indexed') is None or type(r.get('indexed')) is bool) and text(r.get('status'), 2000, False) and isinstance(r.get('evidence'), dict), "Invalid index reading.")
                e = r['evidence']
                if 'snapshot' in e:
                    validate_snapshot(e['snapshot'])
                    require(text(e.get('title_query'), 700, False), "Invalid saved title query.")
    if 'notice' in data:
        require(text(data['notice']), "Invalid notice.")
    return data


def validate_dataset(data):
    try:
        return _validate_dataset(data)
    except (TypeError, KeyError, AttributeError, RecursionError, OverflowError):
        raise TrackerError('Invalid data structure. Restore a schema-valid backup.') from None


def decode_json(raw):
    try:
        return json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError):
        raise TrackerError("Invalid JSON. Check the file or paste a complete snippet result.") from None


def read_dataset(path):
    try:
        with path.open('rb') as f:
            raw = f.read(MAX_BYTES + 1)
        require(len(raw) <= MAX_BYTES, "Data file exceeds 20 MB. Archive older history.")
        return validate_dataset(decode_json(raw))
    except OSError:
        raise TrackerError("Cannot read data file. Check permissions or restore a valid backup.") from None


def load_mine(data_dir):
    path = data_dir / 'tracker.json'
    return read_dataset(path) if path.exists() else empty_data()


def save_dataset(path, data):
    validate_dataset(data)
    raw = (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()
    require(len(raw) <= MAX_BYTES, "Data would exceed 20 MB. Archive older history.")
    fd, temp = tempfile.mkstemp(prefix='.tracker-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


@contextmanager
def writer(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = data_dir / '.tracker.lock'
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise TrackerError("Writer lock exists. Check for a running writer before removing a stale .tracker.lock.") from None
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        path.unlink(missing_ok=True)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def request_bytes(url, data=None, headers=None, limit=MAX_BYTES):
    require(urlsplit(url).scheme == 'https', "External requests require HTTPS.")
    opener = build_opener(ProxyHandler({}), HTTPSHandler(), NoRedirect())
    req = Request(url, data=data, headers=headers or {}, method='POST' if data is not None else 'GET')
    try:
        with opener.open(req, timeout=60) as response:
            raw = response.read(limit + 1)
        require(len(raw) <= limit, "Response exceeds the size limit. Check provider history before retrying.")
        return raw
    except HTTPError as e:
        raise TrackerError(f"Provider HTTP {e.code}. Check access, quota, balance and task history before retrying.") from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise TrackerError("Connection failed or timed out. A paid request may have been billed. Check provider history before retrying.") from None


def json_request(url, body, headers=None):
    h = {'Content-Type': 'application/json'}
    h.update(headers or {})
    return decode_json(request_bytes(url, json.dumps(body).encode(), h))


def plain_query(q):
    require(text(q, 700, False) and '\n' not in q and '\t' not in q, "Query must be 1 to 700 printable characters.")
    # Reject all operator-shaped tokens, including unknown future paid operators.
    require(not re.search(r'(?i)\b[a-z][a-z0-9_-]*\s*:', q), "Search operators are disabled for paid ranks. Use a plain query.")
    return q.strip()


def parse_serp(payload, engine, query, market, depth=10):
    require(isinstance(payload, dict) and payload.get('status_code') == 20000, "Provider rejected the rank request. Check task history.")
    tasks = payload.get('tasks')
    require(isinstance(tasks, list) and len(tasks) == 1 and isinstance(tasks[0], dict) and tasks[0].get('status_code') == 20000, "Rank task failed. Check task history; existing data is unchanged.")
    task = tasks[0]
    result = task.get('result')
    require(isinstance(result, list) and len(result) == 1 and isinstance(result[0], dict), "Rank response has no usable result.")
    result = result[0]
    items = result.get('items')
    require(items is None or isinstance(items, list), "Malformed provider result items.")
    rows = []
    for item in items or []:
        if isinstance(item, dict) and item.get('type') == 'organic':
            require(type(item.get('rank_group')) is int and http_url(item.get('url')), "Malformed organic rank or URL.")
            if 1 <= item['rank_group'] <= depth:
                rows.append({'rank': item['rank_group'], 'url': item['url'], 'title': str(item.get('title') or item['url'])})
    note = 'suspect' if engine == 'bing' and (result.get('keyword') != query or len(rows) < 3) else ''
    if engine == 'google':
        require(result.get('keyword') == query, "Provider keyword mismatch. Check task history; no rank saved.")
    run = {'id': uuid.uuid4().hex, 'at': now(), 'engine': engine, 'query': query, 'market': market, 'provider': 'dataforseo-' + engine, 'provider_cost_usd': task.get('cost', payload.get('cost')), 'results': sorted(rows, key=lambda r: r['rank']), 'note': note}
    d = empty_data()
    d['rank_runs'].append(run)
    validate_dataset(d)
    return run


def fetch_rank(engine, query, market, depth):
    login, password = os.getenv('DATAFORSEO_LOGIN'), os.getenv('DATAFORSEO_PASSWORD')
    require(bool(login and password), "Set DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD in your shell.")
    auth = base64.b64encode((login + ':' + password).encode()).decode()
    # Provider decodes plus and percent escapes in keyword values.
    body = [{'keyword': query.replace('%', '%25').replace('+', '%2B'), 'location_code': MARKETS[market], 'language_code': 'en', 'device': 'desktop', 'depth': depth}]
    return parse_serp(json_request(API.format(engine), body, {'Authorization': 'Basic ' + auth}), engine, query, market, depth)


def gsc_token():
    token = os.getenv('GSC_ACCESS_TOKEN')
    if token:
        return token
    names = ('GSC_CLIENT_ID', 'GSC_CLIENT_SECRET', 'GSC_REFRESH_TOKEN')
    require(all(os.getenv(n) for n in names), "Set GSC_ACCESS_TOKEN or GSC_CLIENT_ID, GSC_CLIENT_SECRET and GSC_REFRESH_TOKEN.")
    body = urlencode({'client_id': os.environ[names[0]], 'client_secret': os.environ[names[1]], 'refresh_token': os.environ[names[2]], 'grant_type': 'refresh_token'}).encode()
    payload = decode_json(request_bytes(TOKEN_API, body, {'Content-Type': 'application/x-www-form-urlencoded'}))
    require(isinstance(payload, dict) and text(payload.get('access_token'), 10000, False), "Google token exchange returned no access token.")
    return payload['access_token']


def gsc_reading(payload, url):
    reading = {'id': uuid.uuid4().hex, 'at': now(), 'engine': 'google', 'url': url, 'indexed': None, 'status': 'Unknown', 'provider': 'gsc', 'evidence': {}, 'note': ''}
    result = payload.get('inspectionResult', {}).get('indexStatusResult') if isinstance(payload, dict) and isinstance(payload.get('inspectionResult'), dict) else None
    if not isinstance(result, dict) or not isinstance(result.get('verdict'), str):
        reading['note'] = 'Inspection error or missing verdict. Check property access and quota.'
    else:
        reading['indexed'] = result['verdict'] == 'PASS'
        reading['status'] = str(result.get('coverageState') or result['verdict'])[:2000]
        reading['evidence'] = {'verdict': result['verdict'], 'coverageState': reading['status']}
    return reading


def property_contains(site, url):
    u = urlsplit(url)
    if site.startswith('sc-domain:'):
        host = site[len('sc-domain:'):].lower()
        return bool(host and '/' not in host and (u.hostname == host or u.hostname.endswith('.' + host)))
    if not http_url(site) or not site.endswith('/'):
        return False
    s = urlsplit(site)
    return u.scheme == s.scheme and u.netloc == s.netloc and u.path.startswith(s.path)


def decode_bing_url(url):
    require(http_url(url), "Invalid browser result URL.")
    u = urlsplit(url)
    if u.hostname in ('bing.com', 'www.bing.com') and u.path == '/ck/a':
        value = parse_qs(u.query).get('u', [''])[0]
        require(value.startswith('a1') and len(value) > 2, "Unsupported Bing click wrapper. Open the result and use its real address.")
        try:
            raw = value[2:]
            decoded = base64.b64decode(raw + '=' * (-len(raw) % 4), altchars=b'-_', validate=True).decode('utf-8')
        except (ValueError, UnicodeError):
            raise TrackerError("Cannot decode Bing click wrapper.") from None
        require(http_url(decoded), "Bing wrapper did not contain an HTTP URL.")
        return decoded
    return url


def title_query(page):
    if page['name'].strip():
        return page['name'].strip()[:700]
    u = urlsplit(page['url'])
    return (u.netloc + ' ' + re.sub(r'[-_/]+', ' ', u.path)).strip()[:700]


def query_key(value):
    return ' '.join(value.split()).casefold()


def validate_snapshot(s):
    require(isinstance(s, dict) and s.get('engine') == 'bing' and text(s.get('query'), 700, s.get('challenge') is True) and valid_time(s.get('at')) and isinstance(s.get('market'), str) and s['market'] in MARKETS, "Invalid browser import. Expected engine, query, UTC at and market.")
    require(type(s.get('next_page')) is bool and type(s.get('no_results')) is bool and type(s.get('challenge')) is bool, "Browser import needs next_page, no_results and challenge booleans.")
    validate_results(s.get('results'), 100)
    require(not s['no_results'] or not s['results'], "Contradictory browser import: no results and results together.")
    return s


def normalize_snapshot(raw):
    require(isinstance(raw, dict), 'Paste the JSON from the Bing snippet.')
    s = {k: copy.deepcopy(raw.get(k)) for k in ('engine', 'query', 'market', 'at', 'results', 'next_page', 'no_results', 'challenge')}
    require(isinstance(s.get('results'), list), "Paste the JSON from the Bing snippet.")
    for row in s['results']:
        require(isinstance(row, dict), "Invalid browser result.")
        row['url'] = decode_bing_url(row.get('url'))
    validate_snapshot(s)
    return s


def classify_bing(page, title, title_snapshot=None, url_snapshot=None):
    """Only a positive match or the specified complete negative pair is conclusive."""
    expected = {'title': title, 'url': 'url:' + page['url']}
    snapshots = {'title': title_snapshot, 'url': url_snapshot}
    for kind, s in snapshots.items():
        if s is not None:
            if s['challenge']:
                return None, 'Unknown', 'Challenge page', {}
            if query_key(s['query']) != query_key(expected[kind]):
                return None, 'Unknown', 'Query mismatch', {}
    for s in snapshots.values():
        if s:
            for row in s['results']:
                if url_identity(row['url']) == url_identity(page['url']):
                    return True, 'Indexed', '', {'match': row}
    if title_snapshot is None or url_snapshot is None:
        return None, 'Unknown', 'One of the two searches is missing', {}
    if title_snapshot['market'] != url_snapshot['market']:
        return None, 'Unknown', 'The searches use different markets', {}
    if len(title_snapshot['results']) < 3:
        return None, 'Unknown', 'Title search returned fewer than 3 organic results', {}
    if not url_snapshot['no_results']:
        return None, 'Unknown', 'URL search did not explicitly say no results; unrelated results prove nothing', {}
    if url_snapshot['next_page'] or title_snapshot['next_page']:
        return None, 'Unknown', 'More results exist; check the next page by hand', {}
    return False, 'Not found', '', {'negative_pair': True}


def import_reading(data, raw, target_url=None, edited_title=None):
    s = normalize_snapshot(raw)
    target_url = target_url or raw.get('target_url')
    edited_title = edited_title or raw.get('title_query')
    candidates = []
    for p in data['pages']:
        title = (edited_title or title_query(p)) if target_url and url_identity(p['url']) == url_identity(target_url) else title_query(p)
        require(text(title, 700, False), "Title search must contain 1 to 700 characters.")
        if target_url and url_identity(p['url']) != url_identity(target_url):
            continue
        if target_url or query_key(s['query']) in (query_key(title), query_key('url:' + p['url'])):
            candidates.append((p, title))
    if raw.get('kind') == 'rank':
        candidates = []
    if len(candidates) > 1:
        raise TrackerError("Query matches several pages. Choose the target page in the Bing queue.")
    if candidates:
        page, title = candidates[0]
        pair = {'title': None, 'url': None}
        for r in sorted(data['index_readings'], key=time_key):
            e = r['evidence']
            if r['engine'] == 'bing' and r['provider'] == 'browser-import' and url_identity(r['url']) == url_identity(page['url']) and e.get('title_query') == title and 'snapshot' in e:
                old = e['snapshot']
                # Pair only same-day, same-market searches to avoid stale negative conclusions.
                if old['at'][:10] == s['at'][:10] and old['market'] == s['market']:
                    kind = 'url' if query_key(old['query']) == query_key('url:' + page['url']) else 'title'
                    pair[kind] = old
        kind = 'url' if query_key(s['query']) == query_key('url:' + page['url']) else 'title'
        pair[kind] = s
        indexed, status, note, evidence = classify_bing(page, title, pair['title'], pair['url'])
        evidence.update({'snapshot': s, 'title_query': title})
        r = {'id': uuid.uuid4().hex, 'at': s['at'], 'engine': 'bing', 'url': page['url'], 'indexed': indexed, 'status': status, 'provider': 'browser-import', 'evidence': evidence, 'note': note}
        data['index_readings'].append(r)
        validate_dataset(data)
        return {'message': status + (': ' + note if note else ''), 'url': page['url'], 'indexed': indexed}
    require(not target_url, "Target page is not tracked. Add it first.")
    queries = [q for q in data['queries'] if query_key(q['query']) == query_key(s['query']) and s['market'] in q['markets']]
    require(len(queries) == 1 and not s['challenge'], "Query mismatch or challenge page. Use a queue search or a tracked query and market.")
    data['rank_runs'].append({'id': uuid.uuid4().hex, 'at': s['at'], 'engine': 'bing', 'market': s['market'], 'query': queries[0]['query'], 'provider': 'browser-import', 'provider_cost_usd': None, 'results': s['results'], 'note': 'Visible browser results only; not a complete search index.'})
    validate_dataset(data)
    return {'message': 'Bing rank run imported', 'url': None}


def derive(data):
    mine = {url_identity(p['url']) for p in data['pages'] if p['mine']}
    events = {}
    for r in data['index_readings']:
        events.setdefault((url_identity(r['url']), r['engine']), []).append(r)
    histories = {}
    for run in sorted(data['rank_runs'], key=time_key):
        owned = [r['rank'] for r in run['results'] if url_identity(r['url']) in mine]
        top = {url_identity(r['url']) for r in run['results'] if r['rank'] <= 10 and url_identity(r['url']) in mine}
        h = {**run, 'best_rank': min(owned) if owned else None, 'top10_yours': len(top)}
        histories.setdefault((run['query'], run['market'], run['engine']), []).append(h)
        # A suspect API run is retained in history but cannot confirm indexation.
        if run['note'] == 'suspect':
            continue
        for row in run['results']:
            key = (url_identity(row['url']), run['engine'])
            events.setdefault(key, []).append({'id': run['id'], 'at': run['at'], 'engine': run['engine'], 'url': row['url'], 'indexed': True, 'status': f"Indexed (seen ranking #{row['rank']})", 'provider': 'rank-run', 'evidence': {'match': row, 'run_provider': run['provider']}, 'note': BING_WARNING if run['provider'] == 'dataforseo-bing' else ''})
    pages = []
    counts = {e: {'indexed': 0, 'not_indexed': 0, 'unknown': 0, 'total': len(data['pages'])} for e in ENGINES}
    for p in data['pages']:
        row = {**p, 'engines': {}}
        for engine in ENGINES:
            saved = sorted(events.get((url_identity(p['url']), engine), []), key=time_key)
            latest = saved[-1] if saved else {'indexed': None, 'status': 'Unknown', 'provider': 'none', 'at': None, 'note': 'No evidence. Google inspection requires your own verified property.' if engine == 'google' else 'No Bing evidence. Use the browser check queue.', 'evidence': {}}
            first = next((r['at'] for r in saved if r['indexed'] is True), None)
            row['engines'][engine] = {**latest, 'first_indexed': first}
            counts[engine]['indexed' if latest['indexed'] is True else 'not_indexed' if latest['indexed'] is False else 'unknown'] += 1
        pages.append(row)
    history = [{'query': k[0], 'market': k[1], 'engine': k[2], 'runs': v} for k, v in histories.items()]
    queue = []
    for p in pages:
        b = p['engines']['bing']
        if b['indexed'] is True:
            continue
        title = title_query(p)
        queue.append({'url': p['url'], 'name': p['name'], 'title_query': title, 'title_link': 'https://www.bing.com/search?' + urlencode({'q': title}), 'url_link': 'https://www.bing.com/search?' + urlencode({'q': 'url:' + p['url']}), 'checked': b['provider'] == 'browser-import', 'status': b['status'], 'note': b['note'], 'provider': b['provider'], 'at': b['at'], 'indexed': b['indexed'], 'evidence': b['evidence']})
    return {'pages': pages, 'counts': counts, 'rank_history': history, 'bing_queue': queue, 'bing_warning': BING_WARNING}


def parse_sitemap(raw):
    require(len(raw) <= 2_000_000, "Sitemap exceeds 2 MB.")
    # Expat expands internal entities. Reject declarations before parsing, including UTF-16/32.
    require(not any(x in raw.replace(b'\x00', b'').upper() for x in (b'<!DOCTYPE', b'<!ENTITY')), "Sitemap entities and document types are disabled.")
    try:
        root = ET.fromstring(raw)
    except (ET.ParseError, ValueError, LookupError):
        raise TrackerError("Invalid sitemap XML.") from None
    require(root.tag.split('}')[-1] == 'urlset', "Use a URL sitemap, not a sitemap index. Child sitemaps are never fetched automatically.")
    urls = []
    for entry in root:
        if entry.tag.split('}')[-1] != 'url':
            continue
        for child in entry:
            if child.tag.split('}')[-1] == 'loc':
                url = (child.text or '').strip()
                require(http_url(url), "Invalid URL in sitemap.")
                urls.append(url)
                require(len(urls) <= MAX_PAGES, "Sitemap exceeds the 2,000 URL cap. Use a smaller sitemap.")
    return urls


def fetch_sitemap(url):
    require(http_url(url) and urlsplit(url).scheme == 'https', "Sitemap URL must use HTTPS.")
    host = urlsplit(url).hostname
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        require(bool(addresses) and all(ipaddress.ip_address(a[4][0]).is_global for a in addresses), "Sitemap must be on a public host.")
    except OSError:
        raise TrackerError("Cannot resolve sitemap host.") from None
    return parse_sitemap(request_bytes(url, limit=2_000_000))


def export_data(data, format):
    if format == 'json':
        return (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode(), 'application/json; charset=utf-8'
    stream = io.StringIO(newline='')
    out = csv.writer(stream)
    out.writerow(['type', 'at_utc', 'engine', 'query', 'market', 'url', 'rank', 'indexed', 'status', 'provider', 'cost_usd', 'note'])
    def safe(value):
        v = str(value) if value is not None else ''
        return "'" + v if v.startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else v
    for run in data['rank_runs']:
        for row in run['results'] or [{}]:
            out.writerow(map(safe, ['rank', run['at'], run['engine'], run['query'], run['market'], row.get('url'), row.get('rank'), '', '', run['provider'], run['provider_cost_usd'], run['note']]))
    for p in derive(data)['pages']:
        for e, r in p['engines'].items():
            out.writerow(map(safe, ['latest-index', r['at'], e, '', '', p['url'], '', 'unknown' if r['indexed'] is None else str(r['indexed']).lower(), r['status'], r['provider'], '', r['note']]))
    for r in data['index_readings']:
        out.writerow(map(safe, ['index-history', r['at'], r['engine'], '', '', r['url'], '', 'unknown' if r['indexed'] is None else str(r['indexed']).lower(), r['status'], r['provider'], '', r['note']]))
    return stream.getvalue().encode(), 'text/csv; charset=utf-8'


class Handler(BaseHTTPRequestHandler):
    server_version = 'RankIndexTracker'

    def __init__(self, *args, data_dir, token, **kwargs):
        self.data_dir, self.token = data_dir, token
        super().__init__(*args, **kwargs)

    def log_message(self, *args):
        pass

    def reply(self, status, body, mime='application/json; charset=utf-8', download=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        for key, value in {'Content-Type': mime, 'Content-Length': str(len(body)), 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer', 'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"}.items():
            self.send_header(key, value)
        if download:
            self.send_header('Content-Disposition', 'attachment; filename="' + download + '"')
        self.end_headers()
        self.wfile.write(body)

    def send_error(self, code, message=None, explain=None):
        self.reply(code, {'error': 'Unsupported request or method.'})

    def host_ok(self):
        hosts = (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')
        return len(self.headers.get_all('Host', [])) == 1 and self.headers.get('Host') in hosts

    def source_data(self):
        params = parse_qs(urlsplit(self.path).query)
        source = params.get('source', ['demo'])
        require(source in (['mine'], ['demo']), "Choose source=demo or source=mine.")
        return read_dataset(ROOT / 'demo.json') if source == ['demo'] else load_mine(self.data_dir)

    def do_GET(self):
        if not self.host_ok():
            return self.reply(403, {'error': 'Use the printed localhost address.'})
        try:
            path = urlsplit(self.path).path
            if path == '/api/data':
                data = self.source_data()
                return self.reply(200, {**data, 'derived': derive(data)})
            if path == '/api/export':
                data = self.source_data()
                fmt = parse_qs(urlsplit(self.path).query).get('format', ['json'])[0]
                require(fmt in ('json', 'csv'), "Export format must be json or csv.")
                body, mime = export_data(data, fmt)
                return self.reply(200, body, mime, 'rank-index-tracker.' + fmt)
            assets = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8'), '/bing-snippet.js': ('bing-snippet.js', 'text/javascript; charset=utf-8'), '/favicon.svg': ('favicon.svg', 'image/svg+xml')}
            if path in assets:
                name, mime = assets[path]
                body = (ROOT / 'web' / name).read_bytes()
                if path == '/':
                    body = body.replace(b'__IMPORT_TOKEN__', self.token.encode())
                return self.reply(200, body, mime)
            self.reply(404, {'error': 'Not found'})
        except (TrackerError, OSError) as e:
            self.reply(422, {'error': str(e) if isinstance(e, TrackerError) else 'Cannot read local files. Check permissions.'})

    def do_POST(self):
        if not self.host_ok():
            return self.reply(403, {'error': 'Invalid Host'})
        origins = (f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}')
        if self.headers.get('Origin') is not None and self.headers['Origin'] not in origins:
            return self.reply(403, {'error': 'Invalid Origin'})
        if not secrets.compare_digest(self.headers.get('X-Import-Token', '').encode('utf-8'), self.token.encode('utf-8')):
            return self.reply(403, {'error': 'Missing or invalid import token. Reload this page.'})
        if urlsplit(self.path).path != '/api/import-reading':
            return self.reply(404, {'error': 'Not found'})
        if parse_qs(urlsplit(self.path).query).get('source') != ['mine']:
            return self.reply(403, {'error': 'Synthetic demo is read-only. Choose My data.'})
        if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
            return self.reply(415, {'error': 'Use application/json'})
        try:
            require(not self.headers.get('Transfer-Encoding') and len(self.headers.get_all('Content-Length', [])) == 1, 'A single Content-Length is required.')
            size = int(self.headers.get('Content-Length', '-1'))
            if size > IMPORT_BYTES:
                return self.reply(413, {'error': 'Import exceeds 250 KB'})
            require(size >= 0, 'Invalid Content-Length')
            self.connection.settimeout(5)
            raw = self.rfile.read(size)
            require(len(raw) == size, 'Incomplete import body')
            snapshot = decode_json(raw)
            with writer(self.data_dir):
                data = load_mine(self.data_dir)
                result = import_reading(data, snapshot)
                save_dataset(self.data_dir / 'tracker.json', data)
            return self.reply(200, result)
        except (TrackerError, ValueError, OSError):
            return self.reply(422, {'error': 'Import rejected. Check query, market, target page, JSON and the writer lock. Existing data was preserved.'})


def make_server(data_dir, port=5064):
    return ThreadingHTTPServer(('127.0.0.1', port), partial(Handler, data_dir=data_dir, token=secrets.token_urlsafe(32)))


def rank_command(args):
    data = load_mine(args.data_dir)
    queries = [{'query': args.query, 'markets': [args.market or 'us']}] if args.query else data['queries']
    jobs = [(plain_query(q['query']), m) for q in queries for m in ([args.market] if args.market else q['markets'])]
    require(bool(jobs), 'Add a query first or pass --query.')
    estimated = len(jobs) * .002 * args.depth / 10
    print(f'{len(jobs)} paid requests, depth {args.depth}, desktop English. Estimated USD {estimated:.6f} (checked 2026-11-12).')
    if not args.spend:
        print('Preview only. No requests or writes. Add --spend to run. No retries.')
        return
    require(bool(os.getenv('DATAFORSEO_LOGIN') and os.getenv('DATAFORSEO_PASSWORD')), 'Set DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD in your shell.')
    with writer(args.data_dir):
        data = load_mine(args.data_dir)
        require(len(data['rank_runs']) + len(jobs) <= MAX_RECORDS, 'History limit reached. Archive before spending.')
        require(len(json.dumps(data).encode()) + len(jobs) * 40000 <= MAX_BYTES, 'Storage is too near the limit. Archive before spending.')
        runs = []
        try:
            for q, m in jobs:
                runs.append(fetch_rank(args.engine, q, m, args.depth))
            data['rank_runs'].extend(runs)
            save_dataset(args.data_dir / 'tracker.json', data)
        except (TrackerError, OSError):
            if runs:
                recovery = empty_data()
                recovery['rank_runs'] = runs
                save_dataset(args.data_dir / ('recovery-' + uuid.uuid4().hex + '.json'), recovery)
            raise
        print(f"Saved {len(runs)} runs. Reported USD {sum(r['provider_cost_usd'] or 0 for r in runs):.6f}.")


def index_command(args):
    data = load_mine(args.data_dir)
    site = args.site_url or os.getenv('GSC_SITE_URL', '')
    pages = [p for p in data['pages'] if p['mine'] and (not args.url or url_identity(p['url']) == url_identity(args.url)) and property_contains(site, p['url'])][:args.limit]
    print(f'{len(pages)} inspection requests, estimated USD 0. Verified owned pages only; limit {args.limit}.')
    if not args.run:
        print('Preview only. No requests or writes. Set GSC_SITE_URL or --site-url and add --run. Non-owned pages stay Unknown unless seen ranking.')
        return
    require(bool(os.getenv('GSC_ACCESS_TOKEN') or all(os.getenv(k) for k in ('GSC_CLIENT_ID', 'GSC_CLIENT_SECRET', 'GSC_REFRESH_TOKEN'))), 'Set GSC_ACCESS_TOKEN or the three GSC OAuth environment variables.')
    require(bool(site and pages), 'No owned tracked URLs match this property. Set GSC_SITE_URL or --site-url.')
    with writer(args.data_dir):
        data = load_mine(args.data_dir)
        require(len(data['index_readings']) + len(pages) <= MAX_RECORDS, 'Inspection history limit reached.')
        token = gsc_token()
        readings = []
        for p in pages:
            try:
                payload = json_request(GSC_API, {'inspectionUrl': p['url'], 'siteUrl': site}, {'Authorization': 'Bearer ' + token})
                reading = gsc_reading(payload, p['url'])
            except TrackerError as e:
                reading = gsc_reading({}, p['url'])
                reading['note'] = str(e)
            readings.append(reading)
        data['index_readings'].extend(readings)
        save_dataset(args.data_dir / 'tracker.json', data)
        print(f'Saved {len(readings)} inspections. Errors are Unknown, never Not indexed.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path.home() / '.rank-index-tracker', help='Private data directory, before the subcommand')
    sub = parser.add_subparsers(dest='command')
    serve = sub.add_parser('serve')
    serve.add_argument('--port', type=int, default=5064)
    p = sub.add_parser('add-page')
    p.add_argument('url')
    p.add_argument('--name', default='')
    p.add_argument('--group', default='Ungrouped')
    p.add_argument('--not-mine', action='store_true')
    p = sub.add_parser('add-pages')
    p.add_argument('--sitemap', required=True)
    p = sub.add_parser('add-query')
    p.add_argument('query')
    p.add_argument('--market', default='us')
    sub.add_parser('remove-page').add_argument('url')
    sub.add_parser('remove-query').add_argument('query')
    sub.add_parser('list')
    p = sub.add_parser('rank')
    p.add_argument('--engine', choices=ENGINES, required=True)
    p.add_argument('--query')
    p.add_argument('--market', choices=MARKETS)
    p.add_argument('--depth', type=int, choices=(10, 20, 30), default=10)
    p.add_argument('--spend', action='store_true')
    p = sub.add_parser('index')
    p.add_argument('--engine', choices=['google'], required=True)
    p.add_argument('--url')
    p.add_argument('--limit', type=int, default=20)
    p.add_argument('--site-url')
    p.add_argument('--run', action='store_true')
    sub.add_parser('bing-queue')
    p = sub.add_parser('import-reading')
    p.add_argument('file')
    p = sub.add_parser('export')
    p.add_argument('--format', choices=['json', 'csv'], default='json')
    p.add_argument('--out', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command in (None, 'serve'):
            port = getattr(args, 'port', 5064)
            require(1024 <= port <= 65535, 'Port must be 1024 to 65535.')
            server = make_server(args.data_dir, port)
            print(f'Rank and Index Tracker: http://127.0.0.1:{port}/\nOpen this address yourself. Ctrl+C to stop. Synthetic demo spends nothing.', flush=True)
            try:
                server.serve_forever()
            finally:
                server.server_close()
        elif args.command == 'rank':
            rank_command(args)
        elif args.command == 'index':
            require(1 <= args.limit <= MAX_PAGES, 'Limit must be 1 to 2,000.')
            index_command(args)
        elif args.command == 'list':
            d = load_mine(args.data_dir)
            print(json.dumps({'pages': d['pages'], 'queries': d['queries']}, indent=2))
        elif args.command == 'bing-queue':
            d = derive(load_mine(args.data_dir))
            for p in d['bing_queue']:
                print(f"{p['name'] or p['url']}\n  Title: {p['title_link']}\n  URL:   {p['url_link']}")
            print(f"{len(d['bing_queue'])} pages without current positive Bing evidence. Unknown does not mean Not found.")
        elif args.command == 'export':
            body, _ = export_data(load_mine(args.data_dir), args.format)
            if args.out:
                # Explicit user-chosen export path; replace atomically.
                fd, name = tempfile.mkstemp(prefix='.export-', dir=args.out.resolve().parent)
                try:
                    with os.fdopen(fd, 'wb') as f:
                        f.write(body)
                    os.replace(name, args.out)
                finally:
                    Path(name).unlink(missing_ok=True)
            else:
                sys.stdout.write(body.decode())
        else:
            # Fetch a sitemap and read import files before locking, but never use stale data for writes.
            urls = fetch_sitemap(args.sitemap) if args.command == 'add-pages' else None
            raw = None
            if args.command == 'import-reading':
                if args.file == '-':
                    raw = sys.stdin.buffer.read(IMPORT_BYTES + 1)
                else:
                    with Path(args.file).open('rb') as f:
                        raw = f.read(IMPORT_BYTES + 1)
                require(len(raw) <= IMPORT_BYTES, 'Import exceeds 250 KB.')
                raw = decode_json(raw)
            with writer(args.data_dir):
                d = load_mine(args.data_dir)
                if args.command in ('add-page', 'add-pages'):
                    for url in urls if urls is not None else [args.url]:
                        key = url_identity(url)
                        if not any(url_identity(p['url']) == key for p in d['pages']):
                            d['pages'].append({'url': url, 'name': getattr(args, 'name', ''), 'group': getattr(args, 'group', 'Sitemap'), 'mine': not getattr(args, 'not_mine', False)})
                elif args.command == 'add-query':
                    q = plain_query(args.query)
                    markets = list(dict.fromkeys(args.market.lower().split(',')))
                    require(bool(markets) and all(m in MARKETS for m in markets), 'Markets must be us,uk,au.')
                    d['queries'] = [r for r in d['queries'] if r['query'] != q] + [{'query': q, 'markets': markets}]
                elif args.command == 'remove-page':
                    d['pages'] = [p for p in d['pages'] if url_identity(p['url']) != url_identity(args.url)]
                elif args.command == 'remove-query':
                    d['queries'] = [q for q in d['queries'] if q['query'] != args.query]
                elif args.command == 'import-reading':
                    print(import_reading(d, raw)['message'])
                save_dataset(args.data_dir / 'tracker.json', d)
            print('Saved. Choose My data and Reload data in the dashboard.')
        return 0
    except (TrackerError, OSError) as e:
        print('Error: ' + (str(e) if isinstance(e, TrackerError) else 'Local file or server operation failed. Check permissions and port.'), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    sys.exit(main())
