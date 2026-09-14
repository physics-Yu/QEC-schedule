"""Current executable gate alphabet and pulse compatibility (user model)."""

SINGLE_QUBIT_GATES = ('H', 'X', 'Y', 'Z', 'T')
EXECUTABLE_GATES = (*SINGLE_QUBIT_GATES, 'CZ', 'MEASURE', 'MZ', 'RESET')


def compatible_gate_types(left, right):
    """Only identical named gates can share a physical pulse interval."""
    return left in EXECUTABLE_GATES and left == right
