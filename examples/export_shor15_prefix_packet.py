"""Export a small reviewed source packet; the complete native suffix is omitted."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))


def export_packet(source, output):
    from neutral_atom_experiments.qec_pbc.parallel_prefix import load_native_parallel_prefix

    source, output = Path(source), Path(output)
    # Authenticate the entire selected initialization and first resource span
    # against the unchanged templates before exporting any reviewable packet.
    prefix = load_native_parallel_prefix(source, include_magic=True)
    with (source/'functions.jsonl').open('rb') as stream:
        functions = [stream.readline() for _ in range(25)]
    last = json.loads(functions[-1])
    contents = {'mother-manifest.json': (source/'manifest.json').read_bytes(),
                'roles.json': (source/'roles.json').read_bytes(),
                'functions.jsonl': b''.join(functions)}
    for name, end in [('native_gates.jsonl', last['gate_byte_end']),
                      ('native_projections.jsonl', last['projection_byte_end'])]:
        with (source/name).open('rb') as stream:
            contents[name] = stream.read(end)
        if len(contents[name]) != end:
            raise ValueError('Authenticated source span truncated during export')
    output.mkdir(parents=True, exist_ok=False)
    for name, content in contents.items():
        (output/name).write_bytes(content)
    manifest = {'schema': 'encoded-native-prefix-packet/1', 'complete_packet': True,
                'whole_native_stream_included': False,
                'physical_execution_claimed': False,
                'source_manifest_sha256': prefix.source['source_manifest_sha256'],
                'reviewed_scope': 'First 24 algorithm functions and complete first resource-preparation source span; execution stops before its first T',
                'source_function_count': 25,
                'source_native_gate_count': last['gate_end'],
                'source_projection_count': last['projection_start']+last['projection_count'],
                'files': {name: {'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
                          for name, content in contents.items()}}
    (output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    (output/'README.md').write_text(
        '# Saved Shor15 source prefix\n\n'
        'This packet contains reviewed raw source bytes, not physical execution results. '
        'The mother manifest identifies the complete ideal native run; its large suffix is omitted. '
        'Packet file hashes and unchanged protocol templates authenticate the bounded input. '
        'Only 2,988 algorithm gates plus the first resource 17 RESET / H gates are eligible for the physical run. '
        'The resource source span also contains T gates to authenticate the original complete function; '
        'they are never selected or executed by the bounded adapter.\n\n'
        'Rebuild with `python examples/export_shor15_prefix_packet.py --source <complete-run> --output <new-packet>`. '
        'Compile with `python examples/run_parallel_shor15_prefix.py --source <packet> --output <new-run> --patches 12`.\n',
        encoding='utf-8')
    load_native_parallel_prefix(output, include_magic=True)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(export_packet(args.source, args.output), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
