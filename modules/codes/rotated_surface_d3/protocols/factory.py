"""Frozen serial six-patch, 4+11 input, 15-to-1 factory recipe.

Four single-qubit rotations are absorbed into initial A states on W2..W5.
The remaining rotations have every triple support and the five-qubit support.
Their product prepares A-dagger on W1 and + on W2..W5 in the ideal case.
After four X checks accept, physical X on W1 establishes the A output convention.
References: Litinski, arXiv:1808.02892 Sec. 3.1 and arXiv:1905.06903 Sec. 1.
"""

from itertools import combinations

from ...contracts.factory_recipe import (
    ComponentCall,
    EventBranch,
    EventRequest,
    FactoryRecipe,
    ResourcePreparation,
    RotationRecipe,
    TConsumptionRecipe,
)

WORK_ROLES = ("W1", "W2", "W3", "W4", "W5")
MAGIC_KIND = "rotated_surface_d3/A"


def t_consumption_recipe(
    data_role: str, magic_role: str, *, key: str = "consume"
) -> TConsumptionRecipe:
    """Declare ideal T teleportation with actual conditional S before return.

    Args:
        data_role: Carrier of the input data, which may be entangled.
        magic_role: Distinct carrier of an independent canonical A resource.
        key: Unique prefix within its enclosing recipe.
    Returns:
        CX(data, magic), MZ(magic), then S(data) iff m=1. Both branches succeed.
    Raises:
        ValueError: A role/prefix is empty or both roles alias each other.
    """
    if not all(isinstance(v, str) and v.strip() for v in (data_role, magic_role, key)):
        raise ValueError("T consumption roles and key must be nonempty strings")
    if data_role == magic_role:
        raise ValueError("T consumption needs distinct data and magic roles")
    cx = ComponentCall(
        f"{key}/cx",
        "transversal_cnot",
        (data_role, magic_role),
        consumes_resource_role=magic_role,
    )
    mz = ComponentCall(f"{key}/mz", "logical_mz", (magic_role,))
    return TConsumptionRecipe(
        key,
        data_role,
        magic_role,
        cx,
        mz,
        EventRequest(
            f"{key}/event", "t_consumption", (mz.key,), (data_role, magic_role)
        ),
        (
            EventBranch("m0", ()),
            EventBranch("m1", (ComponentCall(f"{key}/s", "logical_s", (data_role,)),)),
        ),
    )


def _preparation(key: str, role: str, *, initial: bool = False) -> ResourcePreparation:
    component = "initialize_plus" if initial and role == "W1" else "raw_t_postselection"
    working = component == "initialize_plus"
    return ResourcePreparation(
        key,
        role,
        component,
        f"preparation:{component}",
        component,
        None if working else MAGIC_KIND,
        "working" if working else "adopt" if initial else "reserve",
    )


def factory_recipe() -> FactoryRecipe:
    """Return the code-owned immutable recipe; no device, sampling or execution.

    Raw rejection retries only its preparation role before any new interaction.
    Final rejection requires a fresh batch of all five work states. R is dirty
    and free after its last consumption; its next preparation performs reset.
    """
    rotations = []
    supports = (*combinations(WORK_ROLES, 3), WORK_ROLES)
    for index, support in enumerate(supports):
        key, pivot = f"rotation[{index}]", support[0]
        controls = support[1:]
        rotations.append(
            RotationRecipe(
                key,
                support,
                pivot,
                _preparation(f"{key}/raw", "R"),
                tuple(
                    ComponentCall(
                        f"{key}/compute[{i}]", "transversal_cnot", (control, pivot)
                    )
                    for i, control in enumerate(controls)
                ),
                t_consumption_recipe(pivot, "R", key=f"{key}/consume"),
                tuple(
                    ComponentCall(
                        f"{key}/uncompute[{i}]", "transversal_cnot", (control, pivot)
                    )
                    for i, control in enumerate(reversed(controls))
                ),
            )
        )
    measurements = tuple(
        ComponentCall(f"final/mx/{role}", "logical_mx", (role,))
        for role in WORK_ROLES[1:]
    )
    return FactoryRecipe(
        "rotated_surface_d3",
        "rotated_surface_d3.factory_15_to_1",
        "1",
        WORK_ROLES,
        "R",
        tuple(
            _preparation(f"initial/{role}", role, initial=True) for role in WORK_ROLES
        ),
        tuple(rotations),
        measurements,
        EventRequest(
            "final/event",
            "factory_mx",
            tuple(c.key for c in measurements),
            WORK_ROLES[1:],
        ),
        (ComponentCall("output/canonicalize", "logical_x", ("W1",)),),
        WORK_ROLES,
        (*WORK_ROLES[1:], "R"),
        "W1",
        MAGIC_KIND,
    )
