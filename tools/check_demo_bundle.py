"""Validate portable bundle integrity and public entry links without a browser."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
demo = ROOT / 'demo'
manifest = json.loads((demo / 'manifest.json').read_text(encoding='utf-8'))
for name, entry in manifest['files'].items():
    data = (demo / name).read_bytes()
    assert len(data) == entry['bytes'], name
    assert hashlib.sha256(data).hexdigest() == entry['sha256'], name
for path in (ROOT / 'README.md', demo / 'README.md'):
    for link in re.findall(r'\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
        if '://' not in link:
            assert (path.parent / link.split('#')[0]).exists(), (path, link)
for path in demo.rglob('*.html'):
    text = path.read_text(encoding='utf-8')
    assert not re.search(r'https?://(?:127\.0\.0\.1|localhost):\d+', text), path
    for link in re.findall(r'(?:href|src)="([^"{}]+)"', text):
        if link.startswith(('#', '/', 'http:', 'https:', 'data:', '${')) or '\\' in link:
            continue
        if '<' in link or '?' in link or "'" in link:
            continue  # JavaScript templates inside embedded viewer payloads.
        assert (path.parent / link.split('#')[0]).exists(), (path, link)
delivery = json.loads((demo / 'ghz4/delivery.json').read_text())
assert hashlib.sha256((demo / 'ghz4/animation.html').read_bytes()).hexdigest() == delivery['animation_sha256']
print(json.dumps({'status': 'passed', 'manifest_files': len(manifest['files']), 'checks': 'hashes, sizes, local links, no fixed localhost HTML links, GHZ delivery hash'}))
