from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from neutral_atom_env.testing.motion_report import build_report

if __name__=='__main__':
    print(build_report())
    print(Path('artifacts/motion-planner/index.html').resolve())
