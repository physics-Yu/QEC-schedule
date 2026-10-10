"""Immutable, hash-chained event chunks; never a template/result cache."""
import gzip
from hashlib import sha256
import io
import json
from pathlib import Path

from .engine import digest
from .errors import fail


def byte_hash(path):
    h = sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024*1024), b""): h.update(block)
    return h.hexdigest()


def write_chunk(path, body, previous_hash):
    path = Path(path).resolve()
    if path.exists(): fail("HISTORY_CHUNK_EXISTS", "Committed history chunks cannot be overwritten")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name+".writing")
    if tmp.exists(): fail("HISTORY_CHUNK_TEMP_EXISTS", "An incomplete writer needs explicit recovery")
    with tmp.open("xb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=1) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8") as stream:
                json.dump(body, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    tmp.replace(path)
    payload = {"path": str(path), "byte_sha256": byte_hash(path), "size_bytes": path.stat().st_size,
               "previous_chain_sha256": previous_hash, "action_count": len(body["actions"]),
               "result_count": len(body["results"]), "plan_count": len(body["submitted_plans"]),
               "start_us": body["start_us"], "end_us": body["end_us"]}
    # File relocation does not alter the evidence chain; raw bytes still must match.
    payload["chain_sha256"] = digest({k: v for k, v in payload.items() if k != "path"})
    return payload


def verify_chunks(chunks, *, archive_root=None):
    result, previous = [], None
    for record in chunks:
        item = dict(record)
        path = Path(archive_root)/Path(item["path"]).name if archive_root is not None else Path(item["path"])
        expected = digest({k: v for k, v in item.items() if k not in ("path", "chain_sha256")})
        if item["previous_chain_sha256"] != previous or item["chain_sha256"] != expected or not path.is_file() or byte_hash(path) != item["byte_sha256"]:
            fail("HISTORY_CHUNK_INTEGRITY", "A committed event chunk is missing, reordered or changed")
        item["path"] = str(path.resolve()); result.append(item); previous = item["chain_sha256"]
    return result
