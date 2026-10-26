# Placement source

This package owns pure logical-block placement. It has no physical compilation,
probability sampling, atom state or resource-production policy.

- `model.py`: immutable requests, blocks, origins and result plans.
- `strategies.py`: explicit and vertical-factory strategies, shared validation,
  oriented bounds and stable geometry fingerprints.
- `__init__.py`: public `place`, `validate_plan`, `block_bounds` and record exports.

Code-owned geometry lives in
[codes/contracts/geometry.py](../../../codes/contracts/geometry.py) and
[rotated_surface/geometry.py](../../../codes/rotated_surface/geometry.py).
Factory role order is supplied by the caller's recipe. A plan describes
initial/return positions; temporary readout destinations and transport remain
downstream responsibilities.

See the [API and integration guide](../../docs/placement.md) and
[ADR 0056](../../../../docs/decisions/0056-logical-placement-and-calibration-context.md).
