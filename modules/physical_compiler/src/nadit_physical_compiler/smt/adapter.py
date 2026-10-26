"""Registry boundary for the optional static finite-domain SMT compiler."""

from typing import Any

from ..compiler import CompilationResult
from ..compilers.contracts import CompilerContext, ProgramContext
from ..errors import SearchExhausted
from ..execution import MeasurementBackend
from ..job_fields import array_at, integer_at, keys_at, number_at, required
from ..state import SLMHolder
from ..support import UnsupportedJob

_NATIVE = {"rx", "ry", "rz", "u", "cz", "reset", "measure", "barrier", "global_phase"}


class SMTCompiler:
    """Compile a static program; keep the latest bounded-search evidence."""

    def __init__(self) -> None:
        self.last_evidence: dict[str, Any] | None = None

    def compile(
        self, context: ProgramContext, options: dict[str, Any], case: MeasurementBackend
    ) -> CompilationResult:
        """Solve lazily so other compilers do not require Z3 to be installed."""
        require_entry(context)
        from .solver import solve

        solved = solve(context, options, case)
        self.last_evidence = solved.evidence
        if solved.result is None:
            raise SearchExhausted(f"SMT search returned no schedule: {solved.evidence}")
        return solved.result


def require_entry(context: ProgramContext) -> None:
    """Require the explicit SLM-home boundary supported by this solver profile."""
    if any(
        not isinstance(atom.holder, SLMHolder) for atom in context.entry_state.atoms
    ) or any(grid.rows or grid.columns for grid in context.entry_state.aod_grids):
        raise UnsupportedJob(
            [
                {
                    "stage": "entry",
                    "kind": "smt",
                    "reason": "requires SLM-held entry atoms and no active AOD lines",
                }
            ]
        )


def admit(context: CompilerContext, options: dict[str, Any]) -> list[dict[str, str]]:
    """Static native circuits, one selected flexible/rigid AOD, retained readout."""
    keys_at(
        options, {"xs", "ys", "horizon", "timeout_s", "time_quantum_us"}, "strategy"
    )
    for axis in ("xs", "ys"):
        values = array_at(required(options, axis, "strategy"), f"strategy.{axis}")
        parsed = [number_at(value, f"strategy.{axis}") for value in values]
        if not parsed or parsed != sorted(set(parsed)):
            raise ValueError(
                f"strategy.{axis}: expected nonempty increasing coordinates."
            )
    if integer_at(required(options, "horizon", "strategy"), "strategy.horizon") < 1:
        raise ValueError("strategy.horizon: expected a positive integer.")
    for name in ("timeout_s", "time_quantum_us"):
        if number_at(options[name], f"strategy.{name}") <= 0:
            raise ValueError(f"strategy.{name}: expected a positive number.")
    reasons = []
    names = {node.name for node in context.dag.nodes}
    unsupported = names - _NATIVE
    if unsupported:
        reasons.append(f"unsupported native operations: {sorted(unsupported)}")
    if "cz" in names and (
        context.device.cz is None
        or not any("cz" in zone.operations for zone in context.device.zones)
    ):
        reasons.append("CZ operations require a channel and CZ operation zone")
    if names & {"rx", "ry", "rz", "u", "reset"} and context.device.local is None:
        reasons.append("addressed operations require local control")
    if "measure" in names and (
        context.device.readout is None or not context.device.readout.retain_atoms
    ):
        reasons.append("measurement requires retained-atom readout")
    return [
        {"stage": "strategy", "kind": "smt", "reason": reason} for reason in reasons
    ]


def build(
    context: CompilerContext, options: dict[str, Any]
) -> tuple[SMTCompiler, dict[str, Any]]:
    """Construct a compiler without solving or sampling measurements."""
    return SMTCompiler(), options


def schema() -> dict[str, Any]:
    """Describe the finite search domain and solver budget."""
    return {
        "type": "object",
        "properties": {
            "kind": {"const": "smt"},
            "xs": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 1,
                "uniqueItems": True,
            },
            "ys": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 1,
                "uniqueItems": True,
            },
            "horizon": {"type": "integer", "minimum": 1},
            "timeout_s": {"type": "number", "exclusiveMinimum": 0, "default": 60},
            "time_quantum_us": {
                "type": "number",
                "exclusiveMinimum": 0,
                "default": 0.001,
            },
        },
        "required": ["kind", "xs", "ys", "horizon"],
        "additionalProperties": False,
    }
