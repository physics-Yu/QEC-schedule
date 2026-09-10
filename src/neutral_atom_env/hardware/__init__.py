"""Read-only hardware legality checks."""


def get_backend(hardware):
    """Select once from immutable experiment configuration, never from replay UI."""
    from .rigid_aod import RigidRectangularAODBackend
    from .row_column_aod import RowColumnAODBackend
    from neutral_atom_env.domain.errors import ValidationError
    backends={'rigid':RigidRectangularAODBackend,'row_column':RowColumnAODBackend}
    if hardware.backend not in backends:
        raise ValidationError('UNKNOWN_BACKEND','Unknown AOD backend')
    return backends[hardware.backend]()
