from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from neutral_atom_env.testing.milestone2_report import build_report


if __name__=='__main__':
    results=build_report()
    print('PASS:',len(results),'M2 acceptance scenarios')
    print(Path('artifacts/milestone2/index.html').resolve())
