# Surface-code SMT experiments

There are two distinct studies:

- `run.py`: a timed whole-program comparison of zoned/nonzoned and flexible/rigid
  AODs, with fixed entry homes and a complete single extraction round. The saved
  first pilot established validated constructive upper bounds; every unrestricted
  improvement query was UNKNOWN. It does not rank architecture optima.
- `depth/`: free initial atom assignment and parallel MOVE count for four fixed
  N/Z layers in a finite horizontal double-trap bank. Open or per-atom cyclic
  paths are supported. Readout is excluded; elapsed time is not optimized.

Both reuse native DAGs, Device timing, Atom IR, independent validation and the
shared viewer. Run with the existing Python 3.12 environment, physical compiler
`src` and repository root on PYTHONPATH, the `smt` extra, and existing simulation
dependencies for the Clifford verification oracle.

## Revalidate the archived depth results

```text
python -m experiments.surface_smt.verify_evidence
python -m experiments.surface_smt.verify_evidence --output PATH_TO_NEW_REPLAY
```

This checks retained file hashes, input/model identities, Cartesian geometry,
actual CZ interactions, final per-atom homes, Clifford action and exact reproduced
Atom IR/metrics. It performs no new solver queries. The second form produces one
QEC-aware HTML viewer, trace JSON and reconstructed result documents.

| Case | Boundary | Minimum MOVE depth | Lower-bound evidence |
| --- | --- | ---: | --- |
| open5x5 | No return | 4 | Initially isolated four-stage bound; depth 3 UNSAT |
| cyclic7x7 | Per-atom return | 6 | Depths 4 and 5 UNSAT |
| cyclic6x6 | Per-atom return | 6 | Same-model subdomain of cyclic7x7 |
| cyclic5x5 | Per-atom return | 6 | Same-model subdomain of cyclic7x7 |
| cyclic4x5 | Per-atom return | 7 | Inherited depths 4/5 plus local depth 6 UNSAT |

`evidence/catalog.json` binds the compact source records and expected program
hashes. Original manifests, query responses and witnesses remain byte-preserved.
Historical frozen model sources are stored as text, not imported or executed.
Large archives, full historical source packages and animations remain outside
version control. Historical UNSAT responses are retained solver evidence; this
replay command does not provide an independent UNSAT proof checker.

## New studies

The uniform-rigid variant prepares a fresh 5×5 bank for the same four d3 CZ
matchings. Each MOVE chooses independent integer pitches for its columns and
rows. The complete grid translates as one unit, including lines with no atom.
Every atom must return to its initial SLM trap. Readout is excluded.

```console
python -m experiments.surface_smt.depth.uniform_run prepare NEW_DIRECTORY
python -m experiments.surface_smt.depth.uniform_run verify NEW_DIRECTORY
```

These commands freeze and verify source and input hashes without solving. The
separate POSIX-only `run NEW_DIRECTORY` command launches the depth campaign
only when explicitly requested. Flexible-grid evidence above applies to its
own model.

Use `python -m experiments.surface_smt.run --help` for the four-case workflow;
new timed runs use the process-bounded SMT worker and retain incumbents.
Use `python -m experiments.surface_smt.depth.run prepare OUT --columns 5 --rows 5
--cyclic`, then `run OUT`, for a fresh depth campaign. The depth runner's default
budget is two hours; do not launch it as an ordinary test. Completed campaigns
are read back without rerunning; interrupted runs require a new output directory.
Existing archived responses and their frozen manifests are never rewritten.

Do not compare these depth witnesses directly against fixed-home complete-SE
heuristic timings: boundary, geometry, gate synchronization and objective differ.
