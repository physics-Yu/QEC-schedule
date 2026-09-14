import json
from pathlib import Path
import threading
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import pytest
from neutral_atom_app.visualization.workbench import validate_input, build_inputs, compile_input, preview
from neutral_atom_app.visualization.workbench_server import CompileJobs, create_server


def request(layout='row',count=4,gates=None):
    return {'atom_count':count,'layout':layout,'seed':7,'gates':gates if gates is not None else [
        {'id':'g','gate_type':'CZ','qubit_ids':['Q000','Q003'],'column':0}]}


def test_layout_identity_geometry_and_seed():
    value,circuit,row,placement=build_inputs(request())
    _,_,grid,_=build_inputs(request('grid'))
    assert row.world.traps['S003'].position.y_um==0
    assert grid.world.traps['S003'].position.y_um==10
    a=build_inputs(request('shuffled'))[3]
    assert a==build_inputs(request('shuffled'))[3] and a!=placement
    assert set(a.values())==set(placement.values())
    for q,site in a.items():
        assert any(z.zone_type.value=='storage' and z.bounds.contains(grid.world.traps[site].position) for z in grid.world.zones)


@pytest.mark.parametrize('layout',['row','grid','shuffled'])
def test_real_compilation_for_layouts_and_no_hidden_moves(layout):
    value=request(layout)
    before=preview(value)['recording']['frames'][0]['atom_updates']
    result,state=compile_input(value)
    assert result['status']=='completed' and state.dag.completed
    after={q:state.placement.position(q,state.world,state.aod) for q in state.atoms}
    assert all(after[a['id']].x_um==a['position']['x_um'] and after[a['id']].y_um==a['position']['y_um'] for a in before)
    assert state.metrics()['aod_load_count']==state.metrics()['aod_offload_count']==3
    assert len([o for o in result['recording']['operations'] if o['kind']=='entangling_pulse'])==1


def test_empty_circuit_and_one_atom_rotation():
    result,state=compile_input(request('grid',1,[]))
    assert result['status']=='completed' and state.time_us==0 and not result['recording']['operations']
    value=request('row',1,[{'id':'u','gate_type':'X','parameters':[],'qubit_ids':['Q000'],'column':0}])
    value['raman_duration_us']=7.5
    result,state=compile_input(value)
    assert state.time_us==1
    assert 'raman_duration_us' not in result['input']
    assert result['recording']['operations'][0]['u_parameters_rad']==[3.141592653589793,0,3.141592653589793]


@pytest.mark.parametrize('change',[{'atom_count':True},{'atom_count':0},{'atom_count':129},{'layout':'unknown'},
    {'seed':-1},{'gates':[{'id':'g','gate_type':'U3','parameters':[0,0,float('nan')],'qubit_ids':['Q000'],'column':0}]},
    {'gates':[{'id':'g','gate_type':'CZ','qubit_ids':['Q000','Q000'],'column':0}]}])
def test_reject_invalid_input(change):
    with pytest.raises((ValueError,TypeError)):
        validate_input(request()|change)


def test_column_order_conflicts_and_unknown_atoms():
    gates=[{'id':'z','gate_type':'H','qubit_ids':['Q000'],'column':0},
           {'id':'a','gate_type':'X','qubit_ids':['Q000'],'column':1}]
    _,circuit,_,_=build_inputs(request(gates=gates))
    assert [g.id for g in circuit.gates]==['z','a']
    with pytest.raises(ValueError):validate_input(request(count=2))
    gates[1]['column']=0
    with pytest.raises(ValueError):validate_input(request(gates=gates))


def wait_job(jobs,key):
    end=time.monotonic()+15
    while time.monotonic()<end:
        value=jobs.get(key)
        if value['status']!='compiling':return value
        time.sleep(.05)
    raise AssertionError('Job did not terminate')


def test_jobs_cancel_replace_and_actual_result(tmp_path):
    jobs=CompileJobs(tmp_path)
    try:
        first=jobs.start(request())
        second=jobs.start(request(gates=[]))
        assert jobs.get(first)['status']=='cancelled'
        assert wait_job(jobs,second)['status']=='completed'
        assert jobs.get(second,True)['recording']['duration']==0
        assert (tmp_path/second/'checkpoint.json').exists()
    finally:jobs.close()


def test_compile_timeout(tmp_path):
    jobs=CompileJobs(tmp_path,timeout=.001)
    try:
        key=jobs.start(request())
        assert wait_job(jobs,key)['error']['code']=='COMPILE_TIMEOUT'
    finally:jobs.close()


def test_http_preview_validation_and_origin(tmp_path):
    server=create_server(0,tmp_path)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    url=f'http://127.0.0.1:{server.server_port}'
    try:
        assert b'Atom Studio' in urlopen(url).read()
        req=Request(url+'/api/preview',json.dumps(request()).encode(),headers={'Content-Type':'application/json'})
        data=json.load(urlopen(req))
        assert len(data['recording']['frames'][0]['atom_updates'])==4
        bad=Request(url+'/api/compile',b'{}',headers={'Content-Type':'application/json'})
        with pytest.raises(HTTPError) as error:urlopen(bad)
        assert error.value.code==400
        bad.add_header('Origin','https://unrelated.example')
        with pytest.raises(HTTPError) as error:urlopen(bad)
        assert error.value.code==403
    finally:server.shutdown();server.jobs.close();server.server_close();thread.join()
