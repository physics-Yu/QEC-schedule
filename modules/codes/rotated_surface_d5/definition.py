"""Distance-five view of the shared odd-distance surface-code convention."""

from modules.codes.rotated_surface import definition

CODE = definition(5)
CHECKS = CODE.checks
DATA_COORDINATES = CODE.data_coordinates
CHECK_COORDINATES = CODE.check_coordinates
REFERENCE_COORDINATES = CODE.reference_coordinates
REFERENCE_HOMES = CODE.reference_homes
ROLES = CODE.roles
LOGICAL_X = CODE.logical_x
LOGICAL_Z = CODE.logical_z
