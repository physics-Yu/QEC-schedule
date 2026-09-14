"""Launch the curated demos from a source checkout on Windows, macOS or Linux."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8800, help='Gallery port; 0 selects a free port')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/demo-runs')
    args = parser.parse_args()
    try:
        import z3  # noqa: F401
    except ImportError:
        parser.error('Missing SMT dependency. From the repository run: python -m pip install -e ".[smt]"')
    from neutral_atom_app.visualization.workbench_server import create_server as workbench_server
    from neutral_atom_app.smt_experiment import create_server as smt_server

    demo = ROOT / 'demo'
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    servers = []
    threads = []
    try:
        workbench = workbench_server(0, output / 'workbench', ui_root=demo / 'workbench')
        servers.append(workbench)
        smt = smt_server(output / 'smt', 0, reference=demo / 'smt/reference', ui_file=demo / 'smt/index.html')
        servers.append(smt)
        links = {'workbench': f'http://127.0.0.1:{workbench.server_port}/',
                 'smt': f'http://127.0.0.1:{smt.server_port}/'}

        class Gallery(SimpleHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/launch-links.js':
                    data = ('window.demoLinks=' + json.dumps(links) + ';').encode()
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/javascript; charset=utf-8')
                    self.send_header('Content-Length', str(len(data)))
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers()
                    self.wfile.write(data)
                    return
                super().do_GET()

            def log_message(self, *args):
                pass

        gallery = ThreadingHTTPServer(('127.0.0.1', args.port), partial(Gallery, directory=str(demo)))
        servers.append(gallery)
        for server in servers:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            threads.append(thread)
        links['gallery'] = f'http://127.0.0.1:{gallery.server_port}/'
        (output / 'session.json').write_text(json.dumps(links, indent=2), encoding='utf-8')
        print(json.dumps(links, indent=2), flush=True)
        print('Keep this terminal open. Press Ctrl+C to stop. New runs: ' + str(output), flush=True)
        if not args.no_browser:
            webbrowser.open(links['gallery'])
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        for server in servers[:len(threads)]:
            server.shutdown()
        for server in servers:
            if hasattr(server, 'jobs'):
                server.jobs.close()
            server.server_close()


if __name__ == '__main__':
    main()
