"""IF-01 public device boundary; see knowledge/roles/R1/interface.md."""

from .model import (
    DeviceModelError,
    broadcast_pairs,
    move_duration_us,
    position_in_zone,
    validate_aod_transition,
)
from .spec import DEVICE_VERSION, SCHEMA_VERSION, default_device, validate_device
from .groups import (capture_closure, group_layout, grouped_device,
                     validate_group_transfer, validate_readout_batch)
from .initial import (build_preinitialized_state, patch_geometry,
                      preinitialized_device, validate_preinitialized_state)
from .rigid_readout import rigid_readout_device
from .canonical import canonical_surface17_device

__all__ = [
    "DEVICE_VERSION", "SCHEMA_VERSION", "DeviceModelError", "default_device",
    "validate_device", "move_duration_us", "position_in_zone", "broadcast_pairs",
    "validate_aod_transition",
    "grouped_device", "group_layout", "capture_closure",
    "validate_group_transfer", "validate_readout_batch",
    "preinitialized_device", "patch_geometry", "build_preinitialized_state",
    "validate_preinitialized_state",
    "rigid_readout_device",
    "canonical_surface17_device",
]
