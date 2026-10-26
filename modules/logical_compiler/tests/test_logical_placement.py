"""Independent geometry and coordinate regressions; no component execution."""

from dataclasses import replace

import pytest
from nadit_physical_compiler.device import Position, Region

from modules.codes.contracts.geometry import BlockGeometry
from modules.codes.rotated_surface.geometry import geometry
from modules.logical_compiler.src.placement import (
    BlockPlacement,
    BlockSpec,
    ExplicitPlacement,
    GridFactoryPlacement,
    PlacementPlan,
    PlacementRequest,
    VerticalFactoryPlacement,
    place,
    validate_plan,
)

ROLES = ("W1", "W2", "W3", "W4", "W5", "R")
EXPECTED_X = {
    3: (0, 100, 200, 300, 400, 500),
    5: (0, 140, 280, 420, 560, 700),
    7: (0, 180, 360, 540, 720, 900),
}
EXPECTED_Y = {
    3: (-60, -160, -260, -360),
    5: (-100, -240, -380, -520),
    7: (-140, -320, -500, -680),
}


def request(distance=3, count=1):
    code = f"rotated_surface_d{distance}"
    return PlacementRequest(
        tuple(
            BlockSpec(f"factory{i}/{role}", code, distance, f"factory{i}", role)
            for i in range(count)
            for role in ROLES
        ),
        {code: geometry(code, distance)},
    )


@pytest.mark.parametrize("distance", (3, 5, 7))
@pytest.mark.parametrize("count", (1, 2, 3, 4))
def test_vertical_strategy_exactly_preserves_standard_coordinates(distance, count):
    plan = place(request(distance, count), VerticalFactoryPlacement(ROLES))
    assert len(plan.placements) == 6 * count
    for factory in range(count):
        for column, role in enumerate(ROLES):
            assert plan.placements[f"factory{factory}/{role}"] == BlockPlacement(
                Position(EXPECTED_X[distance][column], EXPECTED_Y[distance][factory])
            )
    assert plan.occupied_bounds == Region(
        0, EXPECTED_Y[distance][count - 1], EXPECTED_X[distance][-1] + 20 * distance, 0
    )


def test_vertical_uses_request_factory_order_and_declared_role_order():
    original = request(count=3)
    blocks = tuple(
        block
        for factory in (2, 0, 1)
        for block in reversed(original.blocks)
        if block.factory_id == f"factory{factory}"
    )
    plan = place(replace(original, blocks=blocks), VerticalFactoryPlacement(ROLES))
    assert plan.placements["factory2/W1"].origin == Position(0, -60)
    assert plan.placements["factory0/R"].origin == Position(500, -160)
    assert plan.placements["factory1/W3"].origin == Position(200, -260)


def test_vertical_uses_each_factory_actual_height_and_configured_gaps():
    first, second = request(3), request(5)
    blocks = first.blocks + tuple(
        replace(
            block,
            block_id=block.block_id.replace("factory0", "factory1"),
            factory_id="factory1",
        )
        for block in second.blocks
    )
    plan = place(
        PlacementRequest(blocks, {**first.geometries, **second.geometries}),
        VerticalFactoryPlacement(ROLES, patch_gap_um=20, factory_gap_um=60),
    )
    assert plan.placements["factory0/R"].origin == Position(400, -60)
    assert plan.placements["factory1/R"].origin == Position(600, -220)
    assert plan.occupied_bounds == Region(0, -220, 700, 0)


def test_explicit_plan_is_immutable_and_fingerprint_ignores_mapping_order():
    original = request()
    positions = {
        block.block_id: BlockPlacement(Position(100 * i, -60))
        for i, block in enumerate(original.blocks)
    }
    specified = replace(original, positions=positions, region=Region(0, -60, 560, 0))
    first = place(specified, ExplicitPlacement())
    second = place(
        replace(
            specified,
            blocks=tuple(reversed(specified.blocks)),
            positions=dict(reversed(tuple(positions.items()))),
        ),
        ExplicitPlacement(),
    )
    assert first.geometry_fingerprint == second.geometry_fingerprint
    positions.clear()
    assert len(first.placements) == len(specified.positions) == 6
    with pytest.raises(TypeError):
        first.placements["factory0/W1"] = BlockPlacement(Position(7, 8))
    with pytest.raises(TypeError):
        first.geometries["rotated_surface_d3"] = geometry("rotated_surface_d3", 3)
    document = first.to_dict()
    document["placements"]["factory0/W1"]["origin"]["x"] = 999
    assert first.placements["factory0/W1"].origin.x == 0
    changed = dict(first.placements)
    changed["factory0/W1"] = BlockPlacement(Position(-100, -60))
    shifted = place(replace(original, positions=changed), ExplicitPlacement())
    assert shifted.geometry_fingerprint != first.geometry_fingerprint


@pytest.mark.parametrize(
    "problem", ("missing", "extra", "overlap", "touch", "outside", "orientation")
)
def test_explicit_rejects_incomplete_or_geometrically_invalid_layout(problem):
    original = request()
    positions = {
        block.block_id: BlockPlacement(Position(i * 100, -60))
        for i, block in enumerate(original.blocks)
    }
    region = Region(0, -60, 560, 0)
    if problem == "missing":
        positions.pop("factory0/W1")
    elif problem == "extra":
        positions["unrequested"] = BlockPlacement(Position(900, -60))
    elif problem == "overlap":
        positions["factory0/W2"] = BlockPlacement(Position(50, -60))
    elif problem == "touch":
        positions["factory0/W2"] = BlockPlacement(Position(60, -60))
    elif problem == "outside":
        positions["factory0/W1"] = BlockPlacement(Position(-1, -60))
    else:
        positions["factory0/W1"] = BlockPlacement(Position(0, -60), "rot90")
    with pytest.raises(ValueError):
        place(
            replace(original, positions=positions, region=region), ExplicitPlacement()
        )


def test_declared_spacing_is_checked_without_inventing_a_component_rule():
    original = request()
    positions = {
        block.block_id: BlockPlacement(Position(100 * i, -60))
        for i, block in enumerate(original.blocks)
    }
    constrained = replace(
        original.geometries["rotated_surface_d3"], minimum_spacing_um=41
    )
    with pytest.raises(ValueError, match="SPACING"):
        place(
            replace(
                original,
                positions=positions,
                geometries={constrained.code_id: constrained},
            ),
            ExplicitPlacement(),
        )
    permitted = replace(constrained, minimum_spacing_um=40)
    assert (
        place(
            replace(
                original, positions=positions, geometries={permitted.code_id: permitted}
            ),
            ExplicitPlacement(),
        ).placements
        == positions
    )


@pytest.mark.parametrize(
    "problem", ("duplicate", "unknown_geometry", "distance_mismatch", "empty")
)
def test_request_rejects_identity_and_geometry_mismatches(problem):
    original = request()
    changes = {
        "duplicate": {"blocks": original.blocks + (original.blocks[0],)},
        "unknown_geometry": {"geometries": {}},
        "distance_mismatch": {
            "blocks": (replace(original.blocks[0], distance=5), *original.blocks[1:])
        },
        "empty": {"blocks": ()},
    }
    with pytest.raises(ValueError):
        replace(original, **changes[problem])


@pytest.mark.parametrize("distance", (2, 4, 0, True))
def test_surface_geometry_rejects_unsupported_distance_or_code(distance):
    with pytest.raises(ValueError):
        geometry(f"rotated_surface_d{distance}", distance)


def test_surface_geometry_is_code_owned_and_distance_specific():
    for distance in (3, 5, 7):
        item = geometry(f"rotated_surface_d{distance}", distance)
        assert item.relative_bounds == Region(0, 0, 20 * distance, 20 * distance)
        assert item.allowed_orientations == ("standard",)
        assert item.minimum_spacing_um == 0
    with pytest.raises(ValueError, match="CODE"):
        geometry("rotated_surface_d5", 3)


@pytest.mark.parametrize("value", (float("inf"), float("nan"), -1, True))
def test_invalid_strategy_spacing_rejected(value):
    with pytest.raises(ValueError):
        VerticalFactoryPlacement(ROLES, patch_gap_um=value)


def test_vertical_requires_complete_factory_roles_and_matching_geometry():
    original = request()
    with pytest.raises(ValueError, match="ROLES"):
        place(
            replace(original, blocks=original.blocks[:-1]),
            VerticalFactoryPlacement(ROLES),
        )
    with pytest.raises(ValueError, match="FACTORY"):
        place(
            replace(
                original,
                blocks=(
                    replace(original.blocks[0], factory_id=None),
                    *original.blocks[1:],
                ),
            ),
            VerticalFactoryPlacement(ROLES),
        )
    mixed = replace(original.blocks[0], code="rotated_surface_d5", distance=5)
    with pytest.raises(ValueError, match="GEOMETRY"):
        place(
            replace(
                original,
                blocks=(mixed, *original.blocks[1:]),
                geometries={
                    **original.geometries,
                    "rotated_surface_d5": geometry("rotated_surface_d5", 5),
                },
            ),
            VerticalFactoryPlacement(ROLES),
        )


def test_custom_strategy_cannot_bypass_shared_validation():
    class Custom:
        def place(self, req):
            return {
                block.block_id: BlockPlacement(Position(0, 0)) for block in req.blocks
            }

    with pytest.raises(ValueError, match="OVERLAP"):
        place(request(), Custom())


def test_explicit_orientation_is_allowed_only_by_code_and_rotates_its_bounds():
    declared = BlockGeometry(
        "rectangle", 1, Region(0, 0, 20, 10), ("standard", "rot90")
    )
    req = PlacementRequest(
        (BlockSpec("A", "rectangle", 1),),
        {"rectangle": declared},
        positions={"A": BlockPlacement(Position(100, 50), "rot90")},
    )
    assert place(req, ExplicitPlacement()).occupied_bounds == Region(90, 50, 100, 70)


def test_placement_never_invokes_physical_compilation_or_probability_sampling(
    monkeypatch,
):
    import random

    from nadit_physical_compiler import compiler

    def forbidden(*args, **kwargs):
        raise AssertionError("Placement must remain pure geometry")

    monkeypatch.setattr(compiler, "compile_physical", forbidden)
    monkeypatch.setattr(random.Random, "random", forbidden)
    monkeypatch.setattr(random, "random", forbidden)
    plan = place(request(7, 3), VerticalFactoryPlacement(ROLES))
    assert len(plan.placements) == 18


def test_nonfinite_coordinates_rejected_by_the_public_geometry_records():
    with pytest.raises(ValueError):
        BlockPlacement(Position(float("nan"), 0))
    with pytest.raises(ValueError):
        BlockGeometry("test", 3, Region(0, 0, float("inf"), 3))


@pytest.mark.parametrize(
    "tamper", ("missing", "overlap", "bounds", "fingerprint", "version", "distance")
)
def test_external_plan_cannot_bypass_geometry_or_fingerprint_validation(tamper):
    plan = place(request(), VerticalFactoryPlacement(ROLES))
    assert validate_plan(plan) is plan
    positions = dict(plan.placements)
    changes = {}
    if tamper == "missing":
        positions.pop("factory0/W1")
        changes["placements"] = positions
    elif tamper == "overlap":
        positions["factory0/W1"] = positions["factory0/W2"]
        changes["placements"] = positions
    elif tamper == "bounds":
        changes["occupied_bounds"] = Region(0, 0, 1, 1)
    elif tamper == "fingerprint":
        changes["geometry_fingerprint"] = "unverified"
    elif tamper == "version":
        changes["geometries"] = {
            key: replace(item, version="changed")
            for key, item in plan.geometries.items()
        }
    else:
        changes["blocks"] = (replace(plan.blocks[0], distance=5), *plan.blocks[1:])
    with pytest.raises(ValueError):
        validate_plan(replace(plan, **changes))


def test_random_rectangle_admission_matches_independent_brute_force():
    from itertools import combinations
    from random import Random

    rng = Random(1703)
    decisions = set()
    for sample in range(80):
        span = 25 if sample % 2 else 120
        rectangles = [
            (
                rng.randrange(span),
                rng.randrange(span),
                rng.randrange(7),
                rng.randrange(7),
                rng.randrange(8),
            )
            for _ in range(9)
        ]
        valid = True
        for a, b in combinations(rectangles, 2):
            ax, ay, aw, ah, a_spacing = a
            bx, by, bw, bh, b_spacing = b
            x_overlap = ax <= bx + bw and bx <= ax + aw
            y_overlap = ay <= by + bh and by <= ay + ah
            dx = 0 if x_overlap else min(abs(ax - bx - bw), abs(bx - ax - aw))
            dy = 0 if y_overlap else min(abs(ay - by - bh), abs(by - ay - ah))
            if (x_overlap and y_overlap) or dx * dx + dy * dy < max(
                a_spacing, b_spacing
            ) ** 2:
                valid = False
                break
        blocks, geometries, positions = [], {}, {}
        for index, (x, y, width, height, spacing) in enumerate(rectangles):
            code = f"rectangle{index}"
            blocks.append(BlockSpec(code, code, 1))
            geometries[code] = BlockGeometry(
                code, 1, Region(0, 0, width, height), minimum_spacing_um=spacing
            )
            positions[code] = BlockPlacement(Position(x, y))
        req = PlacementRequest(tuple(blocks), geometries, positions=positions)
        decisions.add(valid)
        if valid:
            plan = place(req, ExplicitPlacement())
            assert validate_plan(plan) is plan
        else:
            with pytest.raises(ValueError, match="PLACEMENT_OVERLAP|PLACEMENT_SPACING"):
                place(req, ExplicitPlacement())
    assert decisions == {False, True}


@pytest.mark.parametrize("axis", ("vertical", "horizontal"))
def test_large_regular_layout_prunes_unrelated_pairs_without_a_time_threshold(
    monkeypatch, axis
):
    from modules.logical_compiler.src.placement import strategies

    count = 128
    req = request(count=count)
    code = "rotated_surface_d3"
    req = replace(
        req, geometries={code: replace(req.geometries[code], minimum_spacing_um=5)}
    )
    original = strategies.hypot
    checks = []

    def counted_distance(dx, dy):
        checks.append((dx, dy))
        return original(dx, dy)

    monkeypatch.setattr(strategies, "hypot", counted_distance)
    if axis == "vertical":
        plan = place(req, VerticalFactoryPlacement(ROLES))
        assert plan.placements["factory127/R"].origin == Position(500, -12760)
    else:
        positions = {
            block.block_id: BlockPlacement(Position(index * 100, -60))
            for index, block in enumerate(req.blocks)
        }
        plan = place(replace(req, positions=positions), ExplicitPlacement())
    assert len(plan.placements) == 6 * count
    # This measures exact pair work, not machine speed. An all-pairs scan performs
    # 294,528 distances here, despite every unrelated row/column being far apart.
    assert len(checks) < 6 * count


@pytest.mark.parametrize("distance", (3, 5, 7))
@pytest.mark.parametrize("columns", (1, 2, 5))
def test_grid_coordinates_preserve_internal_roles_and_pack_complete_factories(
    distance, columns
):
    plan = place(
        request(distance, 5),
        GridFactoryPlacement(
            ROLES,
            columns=columns,
            patch_gap_um=20,
            factory_gap_x_um=70,
            factory_gap_y_um=30,
        ),
    )
    size = 20 * distance
    width = 6 * size + 5 * 20
    for index in range(5):
        row, column = divmod(index, columns)
        for slot, role in enumerate(ROLES):
            assert plan.placements[f"factory{index}/{role}"].origin == Position(
                column * (width + 70) + slot * (size + 20),
                -size - row * (size + 30),
            )
    assert plan.occupied_bounds.y_max == 0
    assert validate_plan(plan) is plan


@pytest.mark.parametrize("distance", (3, 5, 7))
def test_one_column_grid_is_exactly_the_existing_vertical_plan(distance):
    req = request(distance, 4)
    vertical = place(
        req, VerticalFactoryPlacement(ROLES, patch_gap_um=20.1, factory_gap_um=30.3)
    )
    grid = place(
        req,
        GridFactoryPlacement(
            ROLES, columns=1, patch_gap_um=20.1, factory_gap_y_um=30.3
        ),
    )
    assert grid.to_dict() == vertical.to_dict()


def test_grid_uses_code_footprints_and_request_factory_order():
    geometries = {
        "small": BlockGeometry("small", 1, Region(-5, 2, 15, 12)),
        "large": BlockGeometry("large", 2, Region(3, -6, 43, 24)),
    }
    blocks = tuple(
        BlockSpec(f"{factory}/{role}", code, distance, factory, role)
        for factory, code, distance in (
            ("second", "small", 1),
            ("first", "large", 2),
            ("third", "large", 2),
        )
        for role in ("B", "A")
    )
    plan = place(
        PlacementRequest(blocks, geometries),
        GridFactoryPlacement(
            ("A", "B"),
            columns=2,
            patch_gap_um=10,
            factory_gap_x_um=20,
            factory_gap_y_um=15,
        ),
    )
    # Column 0 fits the wider third factory; the first row fits the taller first.
    assert plan.placements["second/A"].origin == Position(5, -12)
    assert plan.placements["second/B"].origin == Position(35, -12)
    assert plan.placements["first/A"].origin == Position(107, -24)
    assert plan.placements["third/A"].origin == Position(-3, -69)
    assert plan.occupied_bounds == Region(0, -75, 200, 0)


@pytest.mark.parametrize("columns", (0, -1, True, 1.5, float("inf")))
def test_grid_rejects_invalid_column_counts(columns):
    with pytest.raises(ValueError, match="COLUMNS"):
        GridFactoryPlacement(ROLES, columns=columns)


@pytest.mark.parametrize(
    "parameter", ("patch_gap_um", "factory_gap_x_um", "factory_gap_y_um")
)
@pytest.mark.parametrize("value", (0, -1, True, float("nan"), float("inf")))
def test_grid_rejects_invalid_spacing(parameter, value):
    with pytest.raises(ValueError, match="GAP"):
        GridFactoryPlacement(ROLES, columns=2, **{parameter: value})


@pytest.mark.parametrize("problem", ("missing_role", "mixed_code", "positions"))
def test_grid_retains_factory_and_explicit_placement_constraints(problem):
    req = request()
    if problem == "missing_role":
        req = replace(req, blocks=req.blocks[:-1])
    elif problem == "mixed_code":
        req = replace(
            req,
            blocks=(
                replace(req.blocks[0], code="rotated_surface_d5", distance=5),
                *req.blocks[1:],
            ),
            geometries={
                **req.geometries,
                "rotated_surface_d5": geometry("rotated_surface_d5", 5),
            },
        )
    else:
        req = replace(req, positions={"factory0/W1": BlockPlacement(Position(0, -60))})
    with pytest.raises(ValueError):
        place(req, GridFactoryPlacement(ROLES, columns=2))


def test_plan_serialization_roundtrip_revalidates_and_retains_identity():
    import json

    original = place(request(5, 3), GridFactoryPlacement(ROLES, columns=2))
    document = json.loads(json.dumps(original.to_dict()))
    restored = PlacementPlan.from_dict(document)
    assert restored.to_dict() == original.to_dict()
    document["placements"]["factory0/W1"]["origin"]["x"] = 999
    assert restored.placements["factory0/W1"].origin.x == 0


@pytest.mark.parametrize(
    "tamper", ("schema", "fingerprint", "bounds", "geometry", "missing")
)
def test_plan_deserialization_rejects_tampered_saved_evidence(tamper):
    document = place(request(), VerticalFactoryPlacement(ROLES)).to_dict()
    if tamper == "schema":
        document["schema"] = "unknown"
    elif tamper == "fingerprint":
        document["geometry_fingerprint"] = "forged"
    elif tamper == "bounds":
        document["occupied_bounds"]["x_max"] += 10
    elif tamper == "geometry":
        document["geometries"]["rotated_surface_d3"]["version"] = "other"
    else:
        document["placements"].pop("factory0/W1")
    with pytest.raises(ValueError):
        PlacementPlan.from_dict(document)
