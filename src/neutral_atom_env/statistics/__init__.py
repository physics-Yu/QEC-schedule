"""Read-only, per-atom accounting over committed physical execution events."""
from .atoms import AtomStatistics, summarize_atoms, write_atom_statistics

__all__ = ['AtomStatistics', 'summarize_atoms', 'write_atom_statistics']
