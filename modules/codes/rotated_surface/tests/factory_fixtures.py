"""Generic factory admission, code identity and accepted-only growth regression."""

from modules.codes.rotated_surface.fast_factory import (
    SurfaceFactoryProfile,
)


def fixture_profile(distance=5, count=1):
    """Synthetic timings for control tests only; never experimental evidence."""
    from modules.codes.rotated_surface.fast_factory import (
        ROLES,
        SCHEMA,
        acceptance_port,
        entry_key,
        required_variants,
    )

    patches, entries, ports = [], {}, {}
    for i in range(count):
        for slot, role in enumerate(ROLES):
            block = f"factory{i}/{role}"
            patches.append(
                {
                    "block_id": block,
                    "factory_id": f"factory{i}",
                    "role": role,
                    "slot": slot,
                    "origin": [100 * slot, -100 * i],
                }
            )
            ports[block] = acceptance_port(
                1,
                preparation="raw_t_postselection",
                evidence={"test_fixture": True},
                kind="test_fixture",
            ).to_dict()
        for component, roles in required_variants(distance):
            blocks = tuple(f"factory{i}/{r}" for r in roles)
            measured = (
                4
                if component == "raw_t_postselection"
                else 1
                if component in ("initialize_plus", "logical_mx", "logical_mz")
                else 0
            )
            duration = 1 if component.endswith("/canonicalize") else 10 + i
            entries[entry_key(component, blocks)] = {
                "component_id": component,
                "phase_durations_us": [duration],
                "measurement_phases": [[0, 0]] * measured,
                "uses_aod": not component.endswith("/canonicalize"),
                "cost_segments": [
                    {
                        "start_offset_us": 0,
                        "end_offset_us": duration,
                        "category": "movement",
                        "resource": "aod",
                    }
                ],
                "primitive_counts": {},
            }
    return SurfaceFactoryProfile(
        {
            "schema": SCHEMA,
            "distance": distance,
            "factory_count": count,
            "noise_params": {},
            "patches": patches,
            "entries": entries,
            "raw_ports": ports,
        }
    )
