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
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def test_frontend_reads_changed_catalog_defaults_without_js_edits():
    config = catalog()
    config['default_algorithm'] = 'returning'
    config['default_circuit'] = 'mixed'
    config['workspace_defaults'].update(atom_count=2, layout='row')
    config['compilation_defaults']['max_decisions'] = 27
    draft = frontend_default(config)
    result = validate_input(draft)
    assert result['compiler'] == 'returning'
    assert result['atom_count'] == 2 and result['layout'] == 'row'
    assert result['max_decisions'] == 27
    assert [g['gate_type'] for g in result['gates']] == ['H', 'CZ', 'T']
    assert catalog()['default_algorithm'] == 'greedy'  # returned config is detached


@pytest.mark.parametrize('damage', ['specialized_algorithm', 'duplicate_id', 'bad_budget', 'path_escape'])
def test_invalid_catalog_rejects_before_advertising_choices(tmp_path, damage):
    root = tmp_path / 'studio'
    shutil.copytree(CONFIG_PATH.parent, root)
    config = deepcopy(catalog())
    if damage == 'specialized_algorithm': config['algorithms'][0]['id'] = 'qec_joint'
    elif damage == 'duplicate_id': config['algorithms'][1]['id'] = config['algorithms'][0]['id']
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
