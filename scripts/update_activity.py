"""Refresh the auto-generated sections of the profile README.

Reads public GitHub activity and rewrites the blocks delimited by
<!-- ACTIVITY:START --> / <!-- ACTIVITY:END --> and
<!-- STATS:START --> / <!-- STATS:END -->.

Runs from CI with GITHUB_TOKEN, and locally with a PAT in GITHUB_TOKEN.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

USER = os.environ.get('PROFILE_USER', 'v-2841')
README = Path(__file__).resolve().parent.parent / 'README.md'
API = 'https://api.github.com'
MAX_ROWS = 5

# Repositories that should never show up in the public activity feed.
HIDDEN = {'v-2841'}

# Markup counted by GitHub as a language. Templates and vendored assets would
# otherwise outweigh the code they wrap.
MARKUP = {'HTML', 'CSS', 'SCSS', 'Jinja', 'Smarty', 'Batchfile'}


def api(path, params=None):
    url = f'{API}{path}'
    if params:
        url += '?' + '&'.join(f'{k}={v}' for k, v in params.items())
    req = urllib.request.Request(url)
    req.add_header('Accept', 'application/vnd.github+json')
    req.add_header('User-Agent', f'{USER}-profile-readme')
    token = os.environ.get('GITHUB_TOKEN')
    if token:
        req.add_header('Authorization', f'Bearer {token}')
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        print(f'! {path} -> HTTP {exc.code}', file=sys.stderr)
        return []
    except urllib.error.URLError as exc:
        print(f'! {path} -> {exc.reason}', file=sys.stderr)
        return []


def ago(iso):
    moment = datetime.fromisoformat(iso.replace('Z', '+00:00'))
    delta = datetime.now(timezone.utc) - moment
    if delta < timedelta(hours=1):
        return f'{max(delta.seconds // 60, 1)}m ago'
    if delta < timedelta(days=1):
        return f'{delta.seconds // 3600}h ago'
    if delta < timedelta(days=30):
        return f'{delta.days}d ago'
    return moment.strftime('%b %Y')


def escape(text):
    """Neutralise anything a commit subject could do to the table around it."""
    for char in ('\\', '`', '*', '_', '[', ']', '|'):
        text = text.replace(char, '\\' + char)
    return text.replace('<', '&lt;').replace('>', '&gt;')


def collect_activity():
    """Latest public commit per recently touched repository."""
    events = api(f'/users/{USER}/events/public', {'per_page': 100})
    latest = {}

    for event in events:
        repo = event.get('repo', {}).get('name', '')
        if not repo or repo.split('/')[-1] in HIDDEN:
            continue
        latest.setdefault(repo, event.get('created_at'))

    rows = []
    recent = sorted(latest, key=lambda r: latest[r], reverse=True)
    for repo in recent[:MAX_ROWS]:
        params = {'per_page': 1, 'author': USER}
        commits = api(f'/repos/{repo}/commits', params)
        if not commits:
            continue
        commit = commits[0]['commit']
        subject = escape(commit['message'].split('\n')[0])
        if len(subject) > 72:
            subject = subject[:69].rstrip() + '…'
        name = repo.split('/')[-1]
        rows.append(
            f'| [{name}](https://github.com/{repo}) | {subject} '
            f'| {ago(commit["author"]["date"])} |'
        )

    if not rows:
        return '_No public activity in the last few days._'

    head = '| repository | latest commit | |\n|---|---|---|'
    return f'{head}\n' + '\n'.join(rows)


def collect_stats():
    """Language mix across my own public repositories, by bytes of code."""
    repos = api(f'/users/{USER}/repos', {'per_page': 100, 'type': 'owner'})
    langs = Counter()
    pushed = []

    for repo in repos:
        if repo.get('fork') or repo.get('archived'):
            continue
        pushed.append(repo.get('pushed_at', ''))
        measured = api(f'/repos/{repo["full_name"]}/languages') or {}
        for lang, size in measured.items():
            if lang in MARKUP:
                continue
            langs[lang] += size

    if not langs:
        return '_Language stats unavailable._'

    total = sum(langs.values())
    bars = []
    for lang, size in langs.most_common(6):
        share = size / total
        filled = round(share * 24)
        bar = '█' * filled + '░' * (24 - filled)
        bars.append(f'{lang:<12} {bar} {share * 100:4.1f}%')

    updated = max(pushed) if pushed else ''
    footer = f'\nlast public push  {ago(updated)}' if updated else ''
    return '```text\n' + '\n'.join(bars) + footer + '\n```'


def replace(text, marker, body):
    pattern = re.compile(
        rf'(<!-- {marker}:START -->).*?(<!-- {marker}:END -->)', re.S
    )
    if not pattern.search(text):
        print(f'! marker {marker} not found in README', file=sys.stderr)
        return text
    return pattern.sub(lambda m: f'{m.group(1)}\n{body}\n{m.group(2)}', text)


def main():
    text = README.read_text(encoding='utf-8')
    updated = replace(text, 'ACTIVITY', collect_activity())
    updated = replace(updated, 'STATS', collect_stats())

    if updated == text:
        print('README unchanged')
        return 0

    README.write_text(updated, encoding='utf-8')
    print('README updated')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
