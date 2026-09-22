"""Fetch the immutable ZAC AE input and pinned GitHub reference, with hashes."""
from hashlib import md5, sha256
from io import BytesIO
from pathlib import Path
import argparse
import json
import urllib.request
import zipfile

COMMIT = 'e5083362f99e6915f20c2bd0eaa88b6d1cdcecac'
AE_MD5 = 'c1252777c660fc93153e3ae5a38f5c7b'


def fetch(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    entries = []
    for name, url, folder in (
        ('ZAC_AE.zip', 'https://zenodo.org/records/14219336/files/ZAC_AE.zip?download=1', 'zenodo'),
        ('ZAC-github.zip', f'https://codeload.github.com/UCLA-VAST/ZAC/zip/{COMMIT}', 'github'),
    ):
        path = directory / name
        data = path.read_bytes() if path.exists() else urllib.request.urlopen(url, timeout=90).read()
        if name == 'ZAC_AE.zip' and md5(data).hexdigest() != AE_MD5:
            raise ValueError('Zenodo archive MD5 differs from record 14219336')
        path.write_bytes(data)
        with zipfile.ZipFile(BytesIO(data)) as archive:
            root = (directory / folder).resolve()
            for member in archive.namelist():
                if not (root / member).resolve().is_relative_to(root):
                    raise ValueError('Unsafe archive member')
            archive.extractall(root)
        entries.append(dict(file=name, url=url, md5=md5(data).hexdigest(), sha256=sha256(data).hexdigest()))
    manifest = dict(github_commit=COMMIT, zenodo_record='14219336', sources=entries)
    (directory / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('artifacts/zac-reuse/sources'))
    print(json.dumps(fetch(parser.parse_args().output), indent=2))
