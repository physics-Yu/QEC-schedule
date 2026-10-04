"""Serve a fixed independently accepted physical-prefix report on localhost."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8773)
    args = parser.parse_args()
    from neutral_atom_experiments.qec_pbc.native_parallel_report import render_report
    render_report(args.run_dir)
    root = args.run_dir.resolve()
    allowed = {'/': ('index.html', 'text/html; charset=utf-8'),
               '/index.html': ('index.html', 'text/html; charset=utf-8'),
               '/animation.html': ('animation.html', 'text/html; charset=utf-8'),
               '/atom-viewer.js': ('atom-viewer.js', 'text/javascript; charset=utf-8'),
               '/recording.json': ('recording.json', 'application/json; charset=utf-8'),
               '/summary.json': ('summary.json', 'application/json; charset=utf-8'),
               '/independent-audit.json': ('independent-audit.json', 'application/json; charset=utf-8')}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format, *args):
            pass

        def do_GET(self):
            request = urlsplit(self.path)
            if request.query or request.path not in allowed:
                self.send_error(404)
                return
            name, content_type = allowed[request.path]
            data = (root/name).read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'http://127.0.0.1:{server.server_port}/', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
