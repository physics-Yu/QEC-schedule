"""Shared surface-code policy, explicitly selected by concrete code entries."""

CLIFFORD_T = ("x", "y", "z", "h", "s", "sdg", "t", "tdg", "cx")

# Each concrete entry explicitly chooses this shared surface-code scheme.
SURFACE_COMPONENTS = tuple(
    (gate, "trans_cnot" if gate == "cx" else gate) for gate in CLIFFORD_T
) + (
    ("initialize_0", "initialize_0"),
    ("initialize_plus", "initialize_plus"),
    ("measure", "measure_z"),
)
