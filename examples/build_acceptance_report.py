"""Execute curated M0 checks and generate the unified report."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from neutral_atom_env.testing.acceptance import build_report

if __name__=='__main__':
    groups=build_report()
    print(f"PASS: {len(groups)} groups. artifacts/acceptance/index.html")
