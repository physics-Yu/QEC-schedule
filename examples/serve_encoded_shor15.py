"""Serve verified encoded Shor artifacts through a bounded read-only local API."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import RLock
from urllib.parse import parse_qs, urlsplit

from neutral_atom_experiments.qec_pbc.encoded_native_visuals import (
    EncodedNativeView, render_viewer,
)


def make_handler(view, html):
    """Bind one immutable run; requests cannot choose filesystem paths."""
    page = Path(html).read_bytes()
    access = RLock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format, *args):
            return

        def do_GET(self):
            # The verified span cache belongs to this run. Serialize API reads
            # so concurrent browser requests cannot mutate its ordering midway.
            with access:
                self.read_request()

        def read_request(self):
            request = urlsplit(self.path)
            try:
                params = parse_qs(request.query, keep_blank_values=True)
                if any(len(values) != 1 for values in params.values()):
                    raise ValueError('Query parameters must occur once')

                def arguments(allowed):
                    if set(params) - set(allowed):
                        raise ValueError('Unknown query parameter')
                    return {key: values[0] for key, values in params.items()}

                def number(value):
                    if not value.isascii() or not value.isdecimal():
                        raise ValueError('Indices must be nonnegative decimal integers')
                    return int(value)

                if request.path in ('/', '/index.html'):
                    arguments(())
                    self.reply(200, page, 'text/html; charset=utf-8')
                    return
                if request.path == '/api/encoded-native/overview':
                    arguments(())
                    payload = view.overview()
                elif request.path == '/api/encoded-native/functions':
                    values = arguments(('shot', 'injection', 'kind', 'start', 'count'))
                    payload = view.list_functions(**{
                        key: value if key == 'kind' else number(value)
                        for key, value in values.items()
                    })
                elif request.path == '/api/encoded-native/function':
                    values = arguments(('id', 'gate_page', 'projection_page'))
                    if 'id' not in values:
                        raise ValueError('A function id is required')
                    payload = view.function_detail(values.pop('id'), **{
                        key: number(value) for key, value in values.items()
                    })
                else:
                    self.reply(404, b'{"error":"Unknown read-only endpoint"}',
                               'application/json; charset=utf-8')
                    return
                self.reply(200, json.dumps(payload, ensure_ascii=False,
                                          allow_nan=False).encode('utf-8'),
                           'application/json; charset=utf-8')
            except KeyError:
                self.reply(404, b'{"error":"Unknown function identity"}',
                           'application/json; charset=utf-8')
            except (ValueError, OSError) as error:
                self.reply(409, json.dumps({'error': str(error)},
                                          ensure_ascii=False).encode('utf-8'),
                           'application/json; charset=utf-8')

        def reply(self, status, data, content_type):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(data)

    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8769)
    options = parser.parse_args(argv)
    if not 0 <= options.port <= 65535:
        parser.error('--port must be in 0..65535')
    view = EncodedNativeView(options.run_dir)
    html = render_viewer(options.run_dir / 'index.html')
    server = ThreadingHTTPServer(('127.0.0.1', options.port), make_handler(view, html))
    print(f'http://127.0.0.1:{server.server_port}/', flush=True)
    print('Verified reference artifacts; read-only native gate-index replay.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
