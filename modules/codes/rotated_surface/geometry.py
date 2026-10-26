"""Pure initial/return geometry for the rotated surface-code reference grid."""

from nadit_physical_compiler.device import Region

from modules.codes.contracts.geometry import BlockGeometry

from .definition import definition

SITE_PITCH_UM = 10.0
GEOMETRY_VERSION = "rotated_surface.geometry/1"


def geometry(code_id: str, distance: int) -> BlockGeometry:
    """Return the declared local footprint; reject mismatched code identities.

    All odd distances supported by the family geometry are accepted. This does
    not register a logical compiler entry or qualify a new component distance.
    The current templates permit the standard orientation only. No extra gap is
    inferred: strategies and the actual Device provide their own spacing policy.
    """
    code = definition(distance)
    if code_id != f"rotated_surface_d{distance}":
        raise ValueError("GEOMETRY_CODE_MISMATCH: select the explicit code distance")
    coordinates = code.reference_coordinates
    xs, ys = zip(*coordinates, strict=True)
    return BlockGeometry(
        code_id,
        distance,
        Region(
            min(xs) * SITE_PITCH_UM,
            min(ys) * SITE_PITCH_UM,
            max(xs) * SITE_PITCH_UM,
            max(ys) * SITE_PITCH_UM,
        ),
        version=GEOMETRY_VERSION,
    )
