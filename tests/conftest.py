import json
from pathlib import Path
import pytest
from neutral_atom_env.simulation import make_demo_state


def pytest_addoption(parser):
    parser.addoption('--visual', action='store_true', help='Build the curated acceptance report once after tests')


@pytest.fixture
def test_context():
    state = make_demo_state()
    return {'state': state, 'initial': state.snapshot()}


def pytest_runtest_logreport(report):
    if report.when == 'call' or (report.when in {'setup','teardown'} and report.failed):
        _results.append({'test':report.nodeid,'phase':report.when,'outcome':report.outcome,
                         'error':str(report.longrepr) if report.failed else None})


_results = []


def pytest_sessionfinish(session, exitstatus):
    directory = Path('artifacts/acceptance')
    directory.mkdir(parents=True,exist_ok=True)
    (directory/'machine-tests.json').write_text(json.dumps({'exitstatus':int(exitstatus),'tests':_results},indent=2),encoding='utf-8')
    if session.config.getoption('--visual'):
        from neutral_atom_env.testing.acceptance import build_report
        build_report(directory)
