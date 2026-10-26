"""Export code-owned event ports for the logical compiler, without sampling."""

import argparse
import json
from pathlib import Path
from typing import Any

from nadit_physical_compiler.architectures import generate
from nadit_physical_compiler.device import Position, loads_device
from nadit_physical_compiler.state import AtomLayout, AtomState, SLMHolder

from modules.codes.contracts.component import ComponentBinding, InvocationContext
from modules.codes.contracts.event_probability import ProbabilityPort
from modules.codes.rotated_surface_d3.definition import REFERENCE_HOMES
from modules.codes.rotated_surface_d3.probabilities.raw_t import (
    raw_t_ideal_port,
    raw_t_pauli_port,
)
from modules.codes.rotated_surface_d3.probabilities.t_injection import t_injection_port
from modules.codes.rotated_surface_d3.protocols.raw_t_postselection import (
    RawTPostselection,
)


def _reference_pauli_port(
    extra_rounds: int, noise_params: dict[str, Any]
) -> ProbabilityPort:
    """Compile the illustrative reference device with an explicit noise input."""
    config = Path(__file__).parents[1] / "configs/nonzoned_reference.json"
    spec = json.loads(config.read_text(encoding="utf-8"))
    device = loads_device(json.dumps(generate(spec["family"], spec["params"])))
    atoms = tuple(range(17))
    entry = AtomLayout(
        tuple(
            AtomState(atom, device.site(site).position, SLMHolder(site))
            for atom, site in zip(atoms, REFERENCE_HOMES, strict=True)
        ),
        qubit_to_atom=atoms,
    )
    template = RawTPostselection(extra_rounds=extra_rounds).compile(
        device, home_sites=REFERENCE_HOMES, origin=Position(0, 0), aod_id="transport"
    )
    binding = ComponentBinding(
        "probability-reference", Position(0, 0), atoms, "transport"
    )
    sequence = template.bind(binding).expand(
        InvocationContext("probability-reference", 0, 0, device, entry)
    )
    return raw_t_pauli_port(sequence, device, noise_params=noise_params)


def main() -> None:
    """Write two validated ports and print their canonical content fingerprints.

    The default is ideal probabilities. An explicitly supplied raw noise model
    runs the offline Pauli/readout estimator on the illustrative reference
    device; it does not change the ideal T-consumption instrument model.
    Existing output directories are rejected to preserve previous artifacts.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--extra-rounds", type=int, default=1)
    parser.add_argument(
        "--raw-noise-params",
        type=Path,
        help="Explicit noise/v1 Pauli parameter JSON; omission means ideal raw T.",
    )
    args = parser.parse_args()
    raw = raw_t_ideal_port(args.extra_rounds)
    if args.raw_noise_params is not None:
        parameters = json.loads(args.raw_noise_params.read_text(encoding="utf-8"))
        if not isinstance(parameters, dict):
            parser.error("--raw-noise-params must contain a JSON object.")
        raw = _reference_pauli_port(args.extra_rounds, parameters)
    ports = {"raw_t_postselection.json": raw, "t_injection.json": t_injection_port()}
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    for filename, port in ports.items():
        path = output / filename
        path.write_text(
            json.dumps(port.to_dict(), indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print(f"{path}: {port.content_sha256}")


if __name__ == "__main__":
    main()
