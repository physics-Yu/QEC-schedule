"""Display producer LogicalDAG and actual t=0 placement; no invented execution."""
import hashlib
import json
from pathlib import Path

from .bundle import load_bundle
from . import canonical, export_view


def export_hierarchy(bundle_path,out):
    manifest,values,receipt=load_bundle(bundle_path)
    expected={'logical_dag':'LogicalDAG/0.1.0','patch_placement':'patch-placement/0.1','initial_state':'preinitialized-state/0.1','device':'DeviceSpec/0.2.0-draft'}
    for role,schema in expected.items():
        if values.get(role,{}).get('schema_version')!=schema:
            raise ValueError('HIERARCHY_VIEW_SCHEMA_UNSUPPORTED_OR_MISSING: '+role)
    dag,placement,state,device=(values[k] for k in ('logical_dag','patch_placement','initial_state','device'))
    if placement.get('initial_state')!=state or placement.get('device_hash')!=canonical(device):
        raise ValueError('HIERARCHY_VIEW_PLACEMENT_INPUT_MISMATCH')
    if state.get('entry_mode')!='preinitialized' or state.get('startup_actions') or state.get('startup_duration_us')!=0:
        raise ValueError('HIERARCHY_VIEW_PREINITIALIZED_REQUIRED')
    algorithms={p['patch_id'] for p in dag['patches']}
    placed=set(placement['placements'])
    resources=values.get('resource_requirements')
    if not algorithms<=placed or (resources is None and algorithms!=placed) or (resources is not None and not placed<=set(resources['patches'])):
        raise ValueError('HIERARCHY_VIEW_PATCH_COVERAGE')
    physical=values.get('physical_dag_bundle')
    if physical is not None:
        if physical.get('schema_version')!='PhysicalDAGBundle/0.1.0' or physical.get('logical_dag')!=dag or physical.get('logical_dag_sha256')!=canonical(dag):
            raise ValueError('HIERARCHY_VIEW_PHYSICAL_BUNDLE_MISMATCH')
        if physical.get('resource_requirements')!=resources or set(physical['instances'])!={n['id'] for n in dag['nodes']}:
            raise ValueError('HIERARCHY_VIEW_PHYSICAL_COVERAGE')
        if canonical({k:v for k,v in physical.items() if k!='bundle_hash'})!=physical['bundle_hash']:
            raise ValueError('HIERARCHY_VIEW_PHYSICAL_BUNDLE_HASH')
        for spec in physical['specifications'].values():
            if canonical({k:v for k,v in spec.items() if k!='spec_hash'})!=spec['spec_hash']:
                raise ValueError('HIERARCHY_VIEW_PHYSICAL_SPEC_HASH')
    from na_pipeline.frontend import validate_logical_dag
    from na_pipeline.device import validate_preinitialized_state
    if validate_logical_dag(dag):raise ValueError('HIERARCHY_VIEW_INVALID_LOGICAL_DAG')
    if validate_preinitialized_state(state,device):raise ValueError('HIERARCHY_VIEW_INVALID_INITIAL_STATE')
    out=Path(out);out.parent.mkdir(parents=True,exist_ok=True)
    atom_view=None
    if 'atom' in values:
        if values['atom'].get('initial_state',{}).get('atoms')!=state['atoms']:
            raise ValueError('HIERARCHY_VIEW_ATOM_ENTRY_MISMATCH')
        root=Path(bundle_path).resolve().parent
        paths={f['role']:root/f['path'] for f in manifest['files']}
        target=out.with_name(out.stem+'.atoms.html')
        export_view(paths['atom'],target,trace_path=paths.get('trace'),device_path=paths['device'],report_path=paths.get('validation'))
        atom_view={'name':target.name,'byte_sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
    payload={'version':'na-hierarchy-view/0.1','bundle':manifest,'values':values,'receipt':receipt,'atom_view':atom_view,'display_scope':'producer logical graph and actual initial placement; execution only when supplied','user_visual_acceptance':'pending'}
    encoded=json.dumps(payload,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    here=Path(__file__).parent
    html=(here/'hierarchy.html').read_text(encoding='utf-8').replace('/*__STYLE__*/',(here/'viewer.css').read_text(encoding='utf-8')).replace('/*__SCRIPT__*/',(here/'hierarchy.js').read_text(encoding='utf-8')).replace('__PAYLOAD__',encoded)
    out.write_bytes(html.encode('utf-8'))
    result={'version':payload['version'],'path':str(out.resolve()),'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'inputs':receipt,'atom_view':atom_view,'user_visual_acceptance':'pending','browser_verified':False}
    out.with_suffix('.receipt.json').write_bytes((json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    return result
