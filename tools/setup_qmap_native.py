"""Install author dependencies in isolation, including their release-date cutoff."""
import os
import argparse
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]
args = argparse.ArgumentParser(description=__doc__)
args.add_argument('--index-url', default='https://pypi.org/simple')
args = args.parse_args()
target = ROOT/'artifacts/qmap-native/venv'
python = target/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
if not python.is_file():
    venv.create(target, with_pip=True)
subprocess.run([str(python), '-m', 'pip', 'install', 'uv==0.12.17', '--index-url',
                args.index_url], check=True)
requirements = (['-r',str(ROOT/'third_party/qmap/requirements-windows-py312.lock')]
    if os.name=='nt' and sys.version_info[:2]==(3,12) else
    ['--exclude-newer','2025-12-16T12:59:59Z','mqt.qmap==3.5.0','mqt.bench==2.1.0'])
subprocess.run([str(python), '-m', 'uv', '--cache-dir', str(ROOT/'artifacts/qmap-native/uv-cache'),
    'pip', 'install', '--python', str(python),
    '--index-url', args.index_url, *requirements], check=True)
lock = subprocess.check_output([str(python), '-m', 'pip', 'freeze'], text=True)
(ROOT/'artifacts/qmap-native/installed.txt').write_text(lock, encoding='utf-8')
print(python)
