"""Launch the editable standalone parking experiment."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from neutral_atom_app.visualization.parking_server import main
if __name__=='__main__':main()
