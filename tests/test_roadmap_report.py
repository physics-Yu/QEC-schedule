"""Isolated read-only report tests; intentional rejection is not a stage failure."""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import threading
import urllib.error
import urllib.request

import pytest
from playwright.sync_api import sync_playwright

from neutral_atom_env.visualization.roadmap_report import create_server,validate_status,write_page


def ledger():
    return {'schema_version':1,'updated_at':'2026-09-12T18:00:00+08:00',
            'stages':[{'id':f'step{i}','title':f'测试阶段 {i}','status':'pending','attempts':[]} for i in range(1,5)]}


def failed_ledger():
    value=ledger();value['stages'][0].update(status='awaiting_approval',attempts=[{
        'number':1,'formal':True,'status':'failed','started_at':'2026-09-12T17:00:00+08:00',
        'finished_at':'2026-09-12T17:01:00+08:00',
        'evidence':[{'label':'预期负例夹具，不是正式失败','path':'isolated/expected-rejection.json'}],
        'failure':{'facts':['测试夹具：正式结果未满足声明终态'],
                   'hypotheses':['测试假设：归还预算可能不足，尚未核实'],
                   'proposed_retry_scope':['等待审批后只重核归还预算'],
                   'approval':{'status':'pending','user_message':None}}}])
    return value


@contextmanager
def serve(tmp_path,value):
    path=tmp_path/'status.json';path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
    server=create_server(tmp_path,0)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield f'http://127.0.0.1:{server.server_port}',path
    finally:server.shutdown();server.server_close();thread.join(timeout=5)


def test_persistent_page_never_overwrites_root_owned_status(tmp_path):
    path=tmp_path/'status.json';path.write_text(json.dumps(ledger()),encoding='utf-8')
    before=path.read_bytes();write_page(tmp_path)
    assert path.read_bytes()==before
    assert (tmp_path/'index.html').exists() and (tmp_path/'roadmap.js').exists()


def test_pending_stages_are_not_passed_and_expected_failure_is_valid():
    assert validate_status(ledger())['stages'][0]['status']=='pending'
    assert validate_status(failed_ledger())['stages'][0]['status']=='awaiting_approval'


def test_local_candidate_rejection_does_not_fail_stage():
    value=ledger();value['stages'][0]['attempts']=[{'number':1,'formal':False,'status':'failed','evidence':[]}]
    assert validate_status(value)['stages'][0]['status']=='pending'


def test_pass_requires_actual_formal_evidence():
    value=ledger();value['stages'][0]['status']='passed'
    with pytest.raises(ValueError,match='passed formal attempt'):validate_status(value)
    value['stages'][0]['attempts']=[{'number':1,'formal':True,'status':'passed','evidence':[]}]
    with pytest.raises(ValueError,match='evidence'):validate_status(value)
    value['stages'][0]['attempts'][0]['evidence']=[{'label':'check','path':'check.json'}]
    assert validate_status(value)['stages'][0]['status']=='passed'


def test_failed_attempt_cannot_be_hidden_or_retried_without_user_approval():
    value=failed_ledger();value['stages'][0]['status']='pending'
    with pytest.raises(ValueError,match='remain visibly'):validate_status(value)
    value=failed_ledger();value['stages'][0]['status']='running'
    value['stages'][0]['attempts'].append({'number':2,'formal':True,'status':'running','evidence':[]})
    with pytest.raises(ValueError,match='explicit recorded user approval'):validate_status(value)
    approval=value['stages'][0]['attempts'][0]['failure']['approval'];approval['status']='approved'
    with pytest.raises(ValueError,match='user message'):validate_status(value)
    approval['user_message']='预期测试：明确批准该次受限重试'
    assert validate_status(value)['stages'][0]['status']=='running'


def test_http_is_read_only_and_invalid_ledger_is_not_rendered_as_pass(tmp_path):
    with serve(tmp_path,ledger()) as (base,path):
        before=path.read_bytes()
        for method in ('POST','PUT','PATCH','DELETE'):
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(urllib.request.Request(base+'/status.json',data=b'{}',method=method))
            assert error.value.code==405
        assert path.read_bytes()==before
        value=ledger();value['stages'][1]['status']='passed'
        path.write_text(json.dumps(value),encoding='utf-8')
        with pytest.raises(urllib.error.HTTPError) as error:urllib.request.urlopen(base+'/status.json')
        assert error.value.code==422


def test_resuming_engineering_work_closes_obsolete_failure_popup(tmp_path):
    fixture=failed_ledger()
    with serve(tmp_path,fixture) as (base,path),sync_playwright() as p:
        browser=p.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True)
        page=browser.new_page()
        page.goto(base)
        page.locator('#failure-dialog').wait_for(state='visible')
        stage=fixture['stages'][0]
        stage['attempts'][0]['failure']['approval']={'status':'approved',
            'user_message':'工程问题自行修复，仅物理和框架调整需要审批'}
        stage['attempts'].append({'number':2,'formal':True,'status':'running','evidence':[]})
        stage['status']='running'
        path.write_text(json.dumps(fixture),encoding='utf-8')
        # Mirror the read-only automatic refresh without waiting ten seconds.
        page.evaluate("document.getElementById('refresh').click()")
        page.locator('#failure-dialog').wait_for(state='hidden')
        assert '正式验收中' in page.locator('[data-stage="step1"]').inner_text()
        assert len(json.loads(path.read_text(encoding='utf-8'))['stages'][0]['attempts'])==2
        browser.close()


def test_real_browser_expected_failure_popup_never_approves_or_retries(tmp_path):
    """The deliberately failed fixture must show a blocking report; no experiment runs."""
    fixture=failed_ledger()
    output=Path('artifacts/qec-roadmap-display-tests');output.mkdir(parents=True,exist_ok=True)
    with serve(tmp_path,fixture) as (base,path),sync_playwright() as p:
        before=path.read_bytes();requests=[];errors=[]
        browser=p.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True)
        page=browser.new_page(viewport={'width':1400,'height':1050})
        page.on('request',lambda request:requests.append({'method':request.method,'url':request.url}))
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(base)
        page.locator('#failure-dialog').wait_for(state='visible')
        assert 'Attempt 1' in page.locator('#failure-attempt').inner_text()
        assert '等待用户明确审批' in page.locator('#failure-body').inner_text()
        assert '已观察到的事实' in page.locator('#failure-body').inner_text()
        assert '原因假设' in page.locator('#failure-body').inner_text()
        assert page.locator('.stage .tag.passed').count()==0
        page.screenshot(path=str(output/'expected-failure-popup.png'),full_page=True)
        page.locator('#failure-close').click();page.locator('#refresh').click()
        page.wait_for_timeout(200)
        assert page.locator('#failure-dialog').is_hidden()
        assert '等待用户审批' in page.locator('[data-stage="step1"]').inner_text()
        assert path.read_bytes()==before
        assert all(r['method']=='GET' for r in requests)
        assert not any('/compile' in r['url'] or '/retry' in r['url'] or '/approve' in r['url'] for r in requests)
        # Expected local candidate rejection is not a formal failure.
        local=ledger();local['stages'][0]['attempts']=[{'number':1,'formal':False,'status':'failed','evidence':[]}]
        path.write_text(json.dumps(local),encoding='utf-8')
        page.reload();page.locator('.stage').first.wait_for()
        assert page.locator('#failure-dialog').is_hidden()
        assert page.locator('.stage .tag.passed').count()==0
        assert not errors,errors
        browser.close()
    (output/'browser-report.json').write_text(json.dumps({'status':'passed','scope':'isolated expected-negative UI test only',
        'formal_stage_acceptance':False,'expected_failure_popup':True,'facts_vs_hypotheses_distinct':True,
        'no_approval_or_retry_actions':True,'root_status_untouched':True,'local_rejection_no_popup':True,
        'page_errors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
