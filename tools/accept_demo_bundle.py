"""Browser smoke checks against a running demo/launch.py (Playwright required)."""
import argparse
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--demo', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    links = json.loads(args.session.read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    report = {'checks': [], 'errors': []}
    def check(name, value=True):
        assert value, name
        report['checks'].append(name)

    with sync_playwright() as p:
        edge = Path(os.environ.get('PROGRAMFILES(X86)', '')) / 'Microsoft/Edge/Application/msedge.exe'
        browser = p.chromium.launch(**({'executable_path': str(edge)} if edge.is_file() else {}))
        page = browser.new_page(viewport={'width': 1400, 'height': 950})
        page.on('pageerror', lambda e: report['errors'].append(str(e)))
        posts = []
        page.on('request', lambda r: posts.append(r.url) if r.url.endswith('/api/compile') else None)
        try:
            page.goto(links['gallery'])
            check('gallery resolves current dynamic ports', page.locator('#workbench').get_attribute('href') == links['workbench'])
            page.screenshot(path=str(args.output / 'gallery.png'), full_page=True)
            page.goto(links['workbench'])
            page.locator('#experiment-demo').select_option('parallel-h')
            page.wait_for_function("document.querySelector('#circuit-count').textContent.includes('4')")
            check('demo load does not compile', not posts)
            page.locator('#compile').click()
            page.wait_for_function("document.querySelector('#compile-state').dataset.state==='completed'", timeout=90000)
            check('fresh environment compiles four H')
            page.locator('#experiment-demo').select_option('custom')
            page.wait_for_timeout(400)
            # Import an edited supported circuit through the actual UI file control.
            spec = json.loads((args.demo.parent / 'configs/studio/demos/parallel-h.json').read_text(encoding='utf-8'))
            spec['studio'] = {'mode': 'custom'}
            spec['gates'].append({'id': 'EDIT_X', 'gate_type': 'X', 'qubit_ids': ['Q000'], 'column': 1})
            page.locator('#import-file').set_input_files({'name': 'edited.json', 'mimeType': 'application/json', 'buffer': json.dumps(spec).encode()})
            page.wait_for_function("document.querySelector('#circuit-count').textContent.includes('5')")
            check('edited input does not auto compile', len(posts) == 1)
            page.locator('#compile').click()
            page.wait_for_function("document.querySelector('#compile-state').dataset.state==='completed'", timeout=90000)
            check('workbench edited five-gate circuit compiles')
            page.locator('#execution-workspace').scroll_into_view_if_needed()
            page.screenshot(path=str(args.output / 'workbench.png'))
            page.goto(links['smt'])
            page.locator('#metrics tr').first.wait_for()
            check('SMT saved suite works without historical artifacts', page.locator('#metrics tr').count() == 3)
            page.select_option('#gateType', 'X')
            page.click('#add')
            page.click('#compile')
            page.wait_for_function("document.querySelector('#status').textContent.includes('三策略编译完成')", timeout=120000)
            check('SMT edited circuit three real compiles')
            for strategy in ('greedy', 'smt_single', 'smt_multi'):
                page.click(f'[data-strategy="{strategy}"]')
                frame = page.frame_locator('#animation')
                frame.locator('#play').wait_for()
                frame.locator('#speed').select_option('32')
                frame.locator('#play').click()
                page.wait_for_timeout(250)
                check(strategy + ' replay moves', float(frame.locator('#slider').input_value()) > 0)
            page.locator('#results').scroll_into_view_if_needed()
            page.screenshot(path=str(args.output / 'smt.png'))
            for relative in ('index.html', 'workbench/index.html', 'smt/index.html'):
                page.goto((args.demo / relative).resolve().as_uri())
                page.wait_for_timeout(250)
                check('offline entry ' + relative)
            page.goto((args.demo / 'smt/reference/closure/smt_multi/animation.html').resolve().as_uri())
            page.locator('#play').wait_for()
            page.locator('#play').click()
            page.wait_for_timeout(200)
            check('offline SMT animation moves', float(page.locator('#slider').input_value()) > 0)
            page.goto((args.demo / 'ghz4/animation.html').resolve().as_uri(), timeout=60000)
            page.locator('#play').wait_for(timeout=60000)
            page.locator('#speed').select_option('32')
            page.locator('#play').click()
            page.wait_for_timeout(500)
            check('offline full GHZ animation loads and moves', float(page.locator('#slider').input_value()) > 0)
            page.locator('#play').click()
            page.locator('#slider').fill(page.locator('#slider').get_attribute('max'))
            page.locator('#slider').dispatch_event('input')
            check('offline GHZ terminal seek')
            page.goto(links['gallery'])
            page.set_viewport_size({'width': 720, 'height': 900})
            check('720px gallery no overflow', page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
            check('no browser script errors', not report['errors'])
            report['status'] = 'passed'
        except Exception as e:
            report.update(status='failed', failure=str(e))
            page.screenshot(path=str(args.output / 'failure.png'))
            raise
        finally:
            (args.output / 'acceptance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            browser.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
