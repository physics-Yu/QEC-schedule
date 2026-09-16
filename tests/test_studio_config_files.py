from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from neutral_atom_app.visualization.studio_config import CONFIG_PATH, catalog, load_catalog
from neutral_atom_app.visualization.workbench import validate_input


def frontend_default(config):
    script = Path(__file__).resolve().parents[1] / 'src/neutral_atom_app/visualization/studio_model.js'
    code = "const m=require(process.argv[1]);console.log(JSON.stringify(m.newCustom(JSON.parse(require('fs').readFileSync(0,'utf8')))));"
    result = subprocess.run(['node', '-e', code, str(script)], input=json.dumps(config),
                            text=True, encoding='utf-8', capture_output=True, check=True)
    return json.loads(result.stdout)


def test_frontend_reads_changed_catalog_defaults_without_js_edits():
    config = catalog()
    config['default_algorithm'] = 'smt_ordered'
    config['default_circuit'] = 'mixed'
    config['workspace_defaults'].update(atom_count=2, layout='row',aod_backend='row_column_orthogonal',aod_rows=1,aod_columns=1,aod_row_offsets_um=[0],aod_column_offsets_um=[0])
    config['compilation_defaults']['max_decisions'] = 27
    draft = frontend_default(config)
    result = validate_input(draft)
    assert result['compiler'] == 'smt_ordered'
    assert result['atom_count'] == 2 and result['layout'] == 'row'
    assert result['max_decisions'] == 27
    assert [g['gate_type'] for g in result['gates']] == ['H', 'CZ', 'T']
    assert catalog()['default_algorithm'] == 'ordered_greedy'  # returned config is detached


@pytest.mark.parametrize('damage', ['specialized_algorithm', 'duplicate_id', 'bad_budget', 'path_escape', 'retired_algorithm', 'missing_guide'])
def test_invalid_catalog_rejects_before_advertising_choices(tmp_path, damage):
    root = tmp_path / 'studio'
    shutil.copytree(CONFIG_PATH.parent, root)
    config = deepcopy(catalog())
    if damage == 'specialized_algorithm': config['algorithms'][0]['id'] = 'qec_joint'
    elif damage == 'duplicate_id': config['algorithms'][1]['id'] = config['algorithms'][0]['id']
    elif damage == 'retired_algorithm': config['algorithms'][0]['id'] = 'returning'
    elif damage == 'missing_guide': config['algorithms'][0].pop('decision')
    elif damage == 'bad_budget': config['compilation_defaults']['max_decisions'] = True
    else: config['demos'][0]['input_file'] = '../outside.json'
    target = root / 'workbench.json'
    target.write_text(json.dumps(config), encoding='utf-8')
    with pytest.raises(ValueError):
        load_catalog(target)


def test_demo_files_are_explicit_inputs_without_derived_mirrors():
    for demo in catalog()['demos']:
        value = json.loads((CONFIG_PATH.parent / demo['input_file']).read_text(encoding='utf-8'))
        assert value['gates'] and 'compilation' in value
        assert not {'studio', 'compiler', 'compilation_backend', 'aod_traps', 'max_decisions', 'compile_timeout_s'} & value.keys()
        result = validate_input(value)
        assert result['aod_rows'] * result['aod_columns'] <= 128


def test_station_catalog_has_distinct_documented_current_methods():
    config=catalog()
    assert [a['id'] for a in config['algorithms']]==['ordered_greedy','smt_ordered']
    greedy,smt=config['algorithms']
    assert greedy['decision']!=smt['decision']
    assert 'solver_timeout_ms' not in greedy['defaults']
    assert 'beam_width' not in smt['defaults']
    for a in config['algorithms']:
        assert all(a[k] for k in ('version','purpose','decision','tradeoff','validation'))
