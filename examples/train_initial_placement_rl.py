"""Headless entry point; use .venv-rl-stage-b/Scripts/python.exe."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from neutral_atom_experiments.rl_initial_placement import main

if __name__ == '__main__':
    main()
