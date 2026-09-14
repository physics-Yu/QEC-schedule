"""Plan state binding and independent validation; no strategy imports."""
def fingerprint(state):
    from neutral_atom_env.replay.snapshot_encoding import snapshot_digest
    return snapshot_digest(state.snapshot_data())


def exact_validate(plan,state):
    from neutral_atom_env.program.validation import validate_plan
    validate_plan(plan,state)
