"""Serve the local, fixed-schedule noisy-shot experiment and its small JSON API."""

import argparse
import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from ..simplified_circuit.compile_inputs import BUILD
from . import engine

ROOT = Path(__file__).resolve().parent
MAX_BODY_BYTES = 65_536
MAX_SHOTS = 10_000
SAMPLING_LOCK = threading.Lock()
PLANS = [
    {"n": 15, "num_qubits": 12, "num_bits": 8},
    {"n": 21, "num_qubits": 14, "num_bits": 9},
]


class Handler(BaseHTTPRequestHandler):
    """Handle only the experiment page and explicitly listed sampling endpoints."""

    def _send(self, status: int, content: bytes, media_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            # A browser can stop receiving a completed request without stopping work.
            self.log_message("Client disconnected before response delivery")

    def _json(self, status: int, value: object) -> None:
        self._send(
            status,
            json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def do_GET(self) -> None:
        """Return the page, current engine defaults, or fixed-plan metadata."""
        path = urlsplit(self.path).path
        if path in ("/", "/index.html"):
            complete = BUILD / "share/SmallShor-Local.html"
            self._send(
                HTTPStatus.OK,
                (complete if complete.exists() else ROOT / "index.html").read_bytes(),
                "text/html; charset=utf-8",
            )
        elif path == "/share.html":
            self._send(
                HTTPStatus.OK,
                (BUILD / "share/SmallShor-Complete.html").read_bytes(),
                "text/html; charset=utf-8",
            )
        elif path == "/api/defaults":
            self._json(HTTPStatus.OK, engine.DEFAULTS)
        elif path == "/api/plans":
            self._json(HTTPStatus.OK, PLANS)
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "Unknown endpoint"})

    def do_POST(self) -> None:
        """Validate a bounded request and run one experiment at a time."""
        if urlsplit(self.path).path != "/api/sample":
            self._json(HTTPStatus.NOT_FOUND, {"error": "Unknown endpoint"})
            return
        acquired = False
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY_BYTES:
                raise ValueError("Request body must be between 1 and 65536 bytes")
            request = json.loads(self.rfile.read(length))
            if not isinstance(request, dict):
                raise TypeError("Request must be a JSON object")
            n, shots = request.get("n"), request.get("shots")
            parameters, seed = request.get("parameters", {}), request.get("seed")
            if type(n) is not int or n not in (15, 21):
                raise ValueError("n must be 15 or 21")
            if type(shots) is not int or not 1 <= shots <= MAX_SHOTS:
                raise ValueError("shots must be an integer from 1 to 10000")
            if not isinstance(parameters, dict):
                raise TypeError("parameters must be an object")
            if type(seed) is not int or not 0 <= seed <= 4_294_967_295:
                raise ValueError("seed must be an unsigned 32-bit integer")
            acquired = SAMPLING_LOCK.acquire(blocking=False)
            if not acquired:
                self._json(
                    HTTPStatus.CONFLICT,
                    {
                        "error": "上一次采样仍在计算，请稍后重试。停止接收不会中断后台计算。"
                    },
                )
                return
            result = engine.sample(n, parameters, shots, seed)
            self._json(HTTPStatus.OK, result)
        except (ValueError, TypeError, KeyError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except (RuntimeError, OSError, ArithmeticError) as exc:
            self.log_error("Sampling failed: %r", exc)
            self._json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": f"采样失败：{type(exc).__name__}: {exc}"},
            )
        finally:
            if acquired:
                SAMPLING_LOCK.release()


def main() -> None:
    """Run the local HTTP service; use --host and --port to select its binding."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Small Shor shot simulator: http://{args.host}:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping local shot simulator", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
