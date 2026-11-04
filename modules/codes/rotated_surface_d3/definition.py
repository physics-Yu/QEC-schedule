"""Distance-three rotated CSS code and the explicit local reference roles."""

CHECKS = (
    ("X", (0, 1)),
    ("X", (1, 2, 4, 5)),
    ("X", (3, 4, 6, 7)),
    ("X", (7, 8)),
    ("Z", (3, 6)),
    ("Z", (0, 1, 3, 4)),
    ("Z", (4, 5, 7, 8)),
    ("Z", (2, 5)),
)
CHECK_COORDINATES = ((2, 0), (4, 2), (2, 4), (4, 6), (0, 4), (2, 2), (4, 4), (6, 2))
DATA_COORDINATES = tuple((2 * (q % 3) + 1, 2 * (q // 3) + 1) for q in range(9))
REFERENCE_COORDINATES = DATA_COORDINATES + CHECK_COORDINATES
REFERENCE_HOMES = tuple(f"home_r{y}_c{x}" for x, y in REFERENCE_COORDINATES)
ROLES = tuple(f"data[{q}]" for q in range(9)) + tuple(
    f"{b}{i % 4}" for i, (b, _) in enumerate(CHECKS)
)
LOGICAL_X = (0, 3, 6)
LOGICAL_Z = (0, 1, 2)
