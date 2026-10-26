"""Build selected production components and export their actual action traces."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from nadit_physical_compiler.architectures import generate
from nadit_physical_compiler.device import Position, loads_device
from nadit_physical_compiler.serialization import (
    encode_dag,
    encode_device,
    encode_layout,
    encode_program,
)
from nadit_physical_compiler.state import AtomLayout, AtomState, SLMHolder
from nadit_physical_compiler.visualization.export import write_html
from nadit_physical_compiler.visualization.trace import build_trace

from modules.codes.contracts.component import (
    ComponentBinding,
    InvocationContext,
    validate_sequence,
)
from modules.codes.rotated_surface_d3.components import (
    SINGLE_BLOCK_NAMES,
    get_component,
)
from modules.codes.rotated_surface_d3.components.hadamard import H_REFERENCE_HOMES
from modules.codes.rotated_surface_d3.components.transversal import (
    CONTROL_ORIGIN,
    CONTROL_REFERENCE_HOMES,
    TARGET_ORIGIN,
    TARGET_REFERENCE_HOMES,
    TransversalCNOTComponent,
)
from modules.codes.rotated_surface_d3.definition import REFERENCE_HOMES
from modules.codes.rotated_surface_d3.examples.raw_t_postselection_export import (
    export_raw_t_postselection,
)


def main() -> None:
    """Write source, relative templates, concrete actions and pending-result data."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--raw-t-extra-rounds",
        type=int,
        default=1,
        help="Required additional SE rounds for raw-T use (at least one).",
    )
    parser.add_argument(
        "--operations",
        nargs="+",
        default=["initialize_0", "initialize_plus", "se_round"],
        choices=(*SINGLE_BLOCK_NAMES, "transversal_cnot"),
    )
    args = parser.parse_args()
    if args.raw_t_extra_rounds < 1:
        parser.error("Raw-T use requires at least one additional SE round.")
    if len(set(args.operations)) != len(args.operations):
        parser.error("Each requested component must occur once.")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    config = Path(__file__).parents[1] / "configs/nonzoned_reference.json"
    spec = json.loads(config.read_text(encoding="utf-8"))
    device = loads_device(json.dumps(generate(spec["family"], spec["params"])))
    atoms = tuple(range(100, 117))
    world = AtomLayout(
        tuple(
            AtomState(a, device.site(s).position, SLMHolder(s))
            for a, s in zip(atoms, REFERENCE_HOMES, strict=True)
        ),
        qubit_to_atom=atoms,
    )
    binding = ComponentBinding("block-A", Position(0, 0), atoms, "transport")
    templates, expansions, traces = {}, {}, []
    report = {
        "scope": "Selected d3 components; frame management reserved",
        "device_parameters": "Illustrative, not calibrated",
        "operations": {},
        "measurement_values": "Pending; never sampled by expansion",
    }

    def save(name, value):
        (output / name).write_text(
            json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )

    save("device.json", encode_device(device))
    next_result = 1000
    for name in args.operations:
        selected_device, selected_world, homes = device, world, REFERENCE_HOMES
        if name in ("logical_h", "transversal_cnot"):
            h_config = config.with_name(
                "nonzoned_h_reference.json"
                if name == "logical_h"
                else "nonzoned_cnot_reference.json"
            )
            h_spec = json.loads(h_config.read_text(encoding="utf-8"))
            selected_device = loads_device(
                json.dumps(generate(h_spec["family"], h_spec["params"]))
            )
            homes = (
                H_REFERENCE_HOMES
                if name == "logical_h"
                else CONTROL_REFERENCE_HOMES + TARGET_REFERENCE_HOMES
            )
            selected_atoms = tuple(range(100, 100 + len(homes)))
            selected_world = AtomLayout(
                tuple(
                    AtomState(a, selected_device.site(s).position, SLMHolder(s))
                    for a, s in zip(selected_atoms, homes, strict=True)
                ),
                qubit_to_atom=selected_atoms,
            )
        context = InvocationContext(
            name, 0, next_result, selected_device, selected_world
        )
        if name == "transversal_cnot":
            definition = TransversalCNOTComponent()
            joint = definition.compile(
                selected_device,
                control_home_sites=CONTROL_REFERENCE_HOMES,
                target_home_sites=TARGET_REFERENCE_HOMES,
                control_origin=CONTROL_ORIGIN,
                target_origin=TARGET_ORIGIN,
                aod_id="transport",
            )
            template = joint.atomic
            expansion = joint.bind(
                ComponentBinding(
                    "control", CONTROL_ORIGIN, tuple(range(100, 117)), "transport"
                ),
                ComponentBinding(
                    "target", TARGET_ORIGIN, tuple(range(117, 134)), "transport"
                ),
            ).expand(context)
        else:
            definition = get_component(name)
            template = definition.compile(
                selected_device,
                home_sites=homes,
                origin=Position(0, 0),
                aod_id="transport",
            )
            expansion = template.bind(binding).expand(context)
        next_result += len(expansion.measurements)
        templates[name], expansions[name] = template, expansion
        save(f"{name}.device.json", encode_device(selected_device))
        (output / f"{name}.qasm3").write_text(definition.source_qasm, encoding="utf-8")
        (output / f"{name}.atom.txt").write_text(
            expansion.program.to_text(), encoding="utf-8"
        )
        save(
            f"{name}.relative.json",
            {
                "description": asdict(template.description),
                "relative_program": encode_program(template.relative_program),
                "site_offsets": {
                    key: asdict(point) for key, point in template.relative_sites
                },
                "home_site_keys": template.home_sites,
                "measurement_offsets_us": template.measurement_offsets,
                "expected_ideal_values": template.expected_ideal_values,
                "correction_terms": [asdict(t) for t in template.correction_terms],
                "acceptance_ports": template.acceptance_ports,
                "exit_home_site_keys": template.exit_home_sites or template.home_sites,
                "exit_role_permutation": template.exit_role_permutation,
                "output_syndrome_parities": template.output_syndrome_parities,
                "source_sha256": template.source_sha256,
                "reference_device_sha256": template.reference_device_sha256,
                "compiler_source_sha256": template.compiler_source_sha256,
                "template_content_sha256": template.content_sha256,
            },
        )
        save(
            f"{name}.expansion.json",
            {
                "invocation_id": expansion.invocation_id,
                "template_content_sha256": expansion.template_content_sha256,
                "block_id": expansion.block_id,
                "start_us": expansion.start_us,
                "action_end_us": expansion.action_end_us,
                "results_ready_us": expansion.results_ready_us,
                "wire_atoms": expansion.wire_atoms,
                "program": encode_program(expansion.program),
                "dag": encode_dag(expansion.dag),
                "entry_state": encode_layout(expansion.entry_state),
                "exit_state": encode_layout(expansion.exit_state),
                "measurements": [asdict(m) for m in expansion.measurements],
                "correction_relations": [
                    asdict(r) for r in expansion.correction_relations
                ],
                "validation_checks": expansion.validation_checks,
                "exit_binding": (
                    asdict(expansion.exit_binding) if expansion.exit_binding else None
                ),
                "participant_bindings": [
                    asdict(b) for b in expansion.participant_bindings
                ],
                "exit_participant_bindings": [
                    asdict(b) for b in expansion.exit_participant_bindings
                ],
                "acceptance_conditions": [
                    [asdict(ref), value]
                    for ref, value in expansion.acceptance_conditions
                ],
                "acceptance_status": expansion.acceptance_status,
                "output_syndrome_parities": expansion.output_syndrome_parities,
            },
        )
        report["operations"][name] = {
            "action_end_us": expansion.action_end_us,
            "results_ready_us": expansion.results_ready_us,
            "measurements": len(expansion.measurements),
            "correction_relations": len(expansion.correction_relations),
            "source_cx": definition.source_qasm.count("cx "),
            "source_cz": definition.source_qasm.count("cz "),
            "acceptance_status": expansion.acceptance_status,
            "validated": True,
        }
        if name == "raw_t":
            report["operations"][name].update(
                {
                    "scope": "one-round primitive; boundary acceptance only",
                    "ready_for_use": False,
                    "required_use_protocol": "raw_t_postselection",
                }
            )
        traces.append(
            build_trace(
                expansion.program,
                expansion.entry_state,
                selected_device,
                title=name,
                description=(
                    (
                        "One-round primitive only; use raw_t_postselection for resource acceptance. "
                        if name == "raw_t"
                        else ""
                    )
                    + "Actual compiled atom actions. Any measurement values remain "
                    "pending. No frame manager."
                ),
                operations=expansion.operations,
            )
        )
        if name == "raw_t":
            trace, summary, count = export_raw_t_postselection(
                output,
                selected_device,
                binding,
                template,
                InvocationContext(
                    "raw_t_postselection",
                    0,
                    next_result,
                    selected_device,
                    selected_world,
                ),
                extra_rounds=args.raw_t_extra_rounds,
            )
            next_result += count
            traces.append(trace)
            report["operations"]["raw_t_postselection"] = summary
    report["sequence_validated"] = None
    if "initialize_0" in expansions and "se_round" in templates:
        initial = expansions["initialize_0"]
        following = (
            templates["se_round"]
            .bind(binding)
            .expand(
                InvocationContext(
                    "after_initialize_0",
                    initial.action_end_us,
                    next_result,
                    device,
                    initial.exit_state,
                )
            )
        )
        validate_sequence((initial, following))
        save(
            "sequence.json",
            {
                "invocations": [initial.invocation_id, following.invocation_id],
                "second_start_us": following.start_us,
                "first_results_ready_us": initial.results_ready_us,
                "second_action_end_us": following.action_end_us,
                "second_results_ready_us": following.results_ready_us,
                "second_program": encode_program(following.program),
                "second_measurements": [asdict(m) for m in following.measurements],
                "uses_previous_result_values": False,
                "frame_manager": False,
            },
        )
        report["sequence_validated"] = True
    save("report.json", report)
    write_html(traces, output / "index.html", title="d3 component actions")
    lines = [
        "# d3 component action examples",
        "",
        "Protocols are selected explicitly; no gate realization is substituted.",
        "Physical Pauli components have no measurement or implicit SE round.",
        "Raw-T resource use requires raw_t_postselection; the raw_t trace is only its primitive.",
        "",
        "| Component | Action end (us) | Results ready (us) | Correction terms |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, entry in report["operations"].items():
        lines.append(
            f"| {name} | {entry['action_end_us']:.6f} | "
            f"{entry['results_ready_us']:.6f} | {entry['correction_relations']} |"
        )
    lines += [
        "",
        "A sequence example is included when initialization and SE are both selected.",
        "Results remain pending; separate quantum tests verify the actions.",
        "The HTML viewer shows actions; result-ready times are recorded separately.",
        "No optimality, noisy logical-failure or full fault-tolerance claim.",
        "",
    ]
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
