"""Portable reviewed source packet, including a hard stop before magic T."""
import json
from pathlib import Path
import shutil

import pytest

from neutral_atom_experiments.qec_pbc.parallel_prefix import load_native_parallel_prefix

PACKET = Path(__file__).resolve().parents[1]/'references/qec_pbc_validation/shor15_native_prefix_seed0_2026_10_04'


def test_portable_packet_preserves_known_source_and_stops_before_first_t():
    prefix = load_native_parallel_prefix(PACKET, include_magic=True)
    assert prefix.source['source_manifest_sha256'] == '16d12bb97b28d49c07b8a28d7a94ea81cf58d1c6fe7e3ee21f2a68fb350adac7'
    assert len(prefix.circuit.gates) == 3006
    assert len(prefix.source['original_native_projections']) == 413
    assert not any(g.gate_type == 'T' for g in prefix.circuit.gates)
    assert prefix.source['whole_source_suffix_execution_claimed'] is False
    packet = json.loads((PACKET/'manifest.json').read_text(encoding='utf-8'))
    assert packet['source_native_gate_count'] == 3245
    assert packet['whole_native_stream_included'] is False


@pytest.mark.parametrize('name', ['roles.json', 'functions.jsonl', 'native_gates.jsonl',
                                 'native_projections.jsonl', 'mother-manifest.json'])
def test_source_packet_tampering_is_rejected_before_compilation(tmp_path, name):
    packet = tmp_path/'packet'
    shutil.copytree(PACKET, packet)
    path = packet/name
    path.write_bytes(path.read_bytes()+b'\n')
    with pytest.raises(ValueError, match='packet bytes/hash changed'):
        load_native_parallel_prefix(packet, include_magic=True)
