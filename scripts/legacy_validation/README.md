# Historical validation scripts

These 18 scripts were moved from `tests/validation/` during P0-2. They are
historical evidence-generation, artifact-validation, and job-preparation tools,
not test modules. They depend on external `knowledge/`, `artifacts/`,
`scripts/outputs/`, or scenario files omitted from this publication. They are
not run by pytest or CI.

Their logic is preserved. Only paths affected by the move are adjusted:
references to other moved scripts now use `scripts/legacy_validation/`, while
test discovery and imports still refer to `tests/validation/`. Both locations
are two levels below the repository root, so `Path(__file__).parents[2]` keeps
its original meaning. Historical narrative and remote receipts are retained.

Run a script only with its original inputs, environment, and explicit resource
budget. Moving these files does not restore their missing artifacts or qualify
their historical results. The existing disabled remote-launch guard remains
disabled.
