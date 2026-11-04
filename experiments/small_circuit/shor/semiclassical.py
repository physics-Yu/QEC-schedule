"""Convert the supplied Small Shor inverse-QFT suffix to semiclassical readout."""

import re


def semiclassical_source(source: str) -> str:
    """Replace only the identified terminal inverse QFT, preserving bit wiring.

    The first readout occurs immediately before its first outgoing CP. In N15
    the initial and QFT Hadamards on q11 were already cancelled in the supplied
    source; no Hadamard is added. Existing terminal readout and its barrier are
    replaced by adaptive readouts. A boundary barrier completes the supplied
    prefix before the first adaptive measurement.
    """
    statements = [
        line.strip()
        for line in source.splitlines()
        if line.strip() and not line.strip().startswith("//")
    ]
    first_cp = next(i for i, line in enumerate(statements) if line.startswith("cp("))
    measurement = re.compile(r"b\[(\d+)\] = measure q\[(\d+)\];")
    wiring = {}
    for line in statements:
        if match := measurement.fullmatch(line):
            bit, qubit = map(int, match.groups())
            wiring[qubit] = bit
    if sorted(wiring.values()) != list(range(len(wiring))):
        raise ValueError("Expected one terminal readout per output bit.")
    if any(
        "measure" in line or line.startswith("if") for line in statements[:first_cp]
    ):
        raise ValueError("Input prefix must be a static unitary with leading resets.")
    cp = re.compile(r"cp\((.+)\) q\[(\d+)\], q\[(\d+)\];")
    h = re.compile(r"h q\[(\d+)\];")
    output = [
        "// Derived from the supplied simplified circuit; C-marginal only.",
        "// Terminal inverse QFT uses measurement-conditioned Phase gates.",
        "// Original prefix and b[0] output-LSB wiring are preserved.",
        "// N15 has no added H on q11: that pair was cancelled in the input.",
        *statements[:first_cp],
        "barrier q;",
    ]
    measured = set()
    pairs = set()
    readout_started = False
    for line in statements[first_cp:]:
        if line == "barrier q;" or measurement.fullmatch(line):
            readout_started = True
            continue
        if readout_started:
            raise ValueError("Only terminal measurements may follow the readout fence.")
        if match := cp.fullmatch(line):
            angle, control, target = match.groups()
            control, target = int(control), int(target)
            if control not in wiring or target not in wiring:
                raise ValueError("QFT CP must connect output-register qubits.")
            if wiring[control] >= wiring[target] or target in measured:
                raise ValueError(
                    "QFT CP ordering is incompatible with adaptive readout."
                )
            if (control, target) in pairs:
                raise ValueError("Duplicate QFT phase pair.")
            pairs.add((control, target))
            if control not in measured:
                output.append(f"b[{wiring[control]}] = measure q[{control}];")
                measured.add(control)
            output.append(
                f"if (b[{wiring[control]}] == true) {{ p({angle}) q[{target}]; }}"
            )
        elif match := h.fullmatch(line):
            if int(match.group(1)) in measured:
                raise ValueError("Measured QFT control is reused by a unitary.")
            output.append(line)
        else:
            raise ValueError(f"Unexpected terminal QFT statement: {line}")
    expected = {(a, b) for a in wiring for b in wiring if wiring[a] < wiring[b]}
    if pairs != expected:
        raise ValueError(
            "Terminal suffix is not the expected full inverse-QFT triangle."
        )
    for qubit, bit in sorted(wiring.items(), key=lambda pair: pair[1]):
        if qubit not in measured:
            output.append(f"b[{bit}] = measure q[{qubit}];")
    return "\n".join(output) + "\n"
