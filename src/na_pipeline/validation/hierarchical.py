"""T605 product adapter boundary; unsupported wire versions fail explicitly."""
from .dag_core import DAGAudit
from .dag_session import validate_session_run


def validate_hierarchical_run(bundle):
    fixture=isinstance(bundle,dict) and bundle.get('fixture') is True
    audit=DAGAudit('hierarchical_dag_run',{'bundle':bundle},fixture=fixture)
    if not isinstance(bundle,dict):
        audit.fail('HIERARCHICAL_INPUT_MISSING','A complete product bundle is required'); return audit.report()
    if 'windows' in bundle:
        required={'logical_dag','patch_placement','logical_schedule','device','initial_state','event_trace'}
        missing=sorted(required-set(bundle))
        physical=bundle.get('physical_bundle',bundle.get('physical_dag_bundle'))
        if physical is None: missing.append('physical_dag_bundle')
        if missing or not bundle['windows']:
            audit.fail('HIERARCHICAL_INPUT_MISSING','Original continuous-session products and executed windows are required',missing=missing); return audit.report()
        # The report intentionally retains its component scope. A collection of
        # stored windows cannot infer complete factory or Shor qualification.
        return validate_session_run({**bundle,'physical_bundle':physical})
    required={'logical_dag','physical_dags','patch_placement','logical_schedule','device','initial_state','atom_program','event_trace','source_program','scenario','enola_evidence'}
    missing=sorted(required-set(bundle))
    if missing:
        audit.fail('HIERARCHICAL_INPUT_MISSING','Required products are absent',missing=missing); return audit.report()
    audit.need('DAG_ADAPTER_UNAVAILABLE','Producer schema adapters require published versioned fields; old fixed-home strategy evidence cannot qualify the new pipeline')
    return audit.report()
