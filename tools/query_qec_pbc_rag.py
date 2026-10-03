"""Dependency-free evidence retrieval for the curated surface-code/PBC corpus.

This returns source material, not a generated answer or a physical compiler.
Compatible with Python 3.7+; use --check before relying on project snapshots.
Repository sources may declare text_lf fingerprints to ignore checkout line
endings. Their historical raw_sha256 values remain evidence of reviewed bytes.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "references" / "qec_pbc_rag"
CLAIM_TYPES = {"literature_fact", "mathematical_derivation", "project_snapshot", "engineering_design"}
REQUIRED = {"schema", "id", "title", "layer", "claim_type", "implementation_status",
            "reviewed_at", "tags", "questions", "content", "source_refs",
            "limitations", "validation", "related_ids"}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load():
    chunks = [json.loads(line) for line in (CORPUS / "knowledge.jsonl").read_text(
        encoding="utf-8-sig").splitlines() if line.strip()]
    registry = read_json(CORPUS / "sources.json")
    return chunks, {source["id"]: source for source in registry["sources"]}


def tokens(value):
    # Preserve English identifiers; Chinese bigrams provide a small no-model baseline.
    result = []
    for part in re.findall(r"[a-zA-Z0-9_]+|[\u3400-\u9fff]+", value.lower()):
        if re.fullmatch(r"[\u3400-\u9fff]+", part):
            result.extend([part] if len(part) == 1 else
                          [part[i:i + 2] for i in range(len(part) - 1)])
        else:
            result.append(part)
    return result


def document_tokens(chunk):
    # Weight explicit routing terms and user questions above incidental mentions.
    return tokens(" ".join([chunk["title"]] * 3 + chunk["tags"] * 3 +
                           chunk["questions"] * 2 + [chunk["content"]] +
                           chunk["limitations"] + chunk["validation"]))


def retrieve(query, chunks, top_k=5):
    if not chunks:
        return []
    docs = [Counter(document_tokens(chunk)) for chunk in chunks]
    lengths = [sum(doc.values()) for doc in docs]
    avg_length = sum(lengths) / len(lengths)
    frequencies = Counter(term for doc in docs for term in doc)
    query_terms = set(tokens(query))
    scored = []
    for chunk, doc, length in zip(chunks, docs, lengths):
        score = 0.0
        for term in query_terms:
            tf = doc[term]
            if tf:
                df = frequencies[term]
                idf = math.log(1 + (len(docs) - df + 0.5) / (df + 0.5))
                score += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * length / avg_length))
        if score > 0:
            scored.append((score, chunk))
    scored.sort(key=lambda item: (-item[0], item[1]["id"]))
    return scored[:top_k]


def source_sha256(path, normalization=None):
    """Hash exact bytes by default, or explicitly declared UTF-8 text with LF.

    text_lf preserves every character, including a possible UTF-8 BOM, while
    normalizing CRLF and CR line endings. It never hides textual changes.
    """
    value = path.read_bytes()
    if normalization == "text_lf":
        value = value.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
    elif normalization is not None:
        raise ValueError("unknown SHA256 normalization: " + str(normalization))
    return hashlib.sha256(value).hexdigest()


def source_issues(source):
    issues = []
    if source["kind"] == "repository_snapshot":
        normalization = source.get("sha256_normalization")
        if normalization not in (None, "text_lf"):
            return ["unknown SHA256 normalization: " + str(normalization)]
        for relative in source.get("paths", []):
            path = (ROOT / relative).resolve()
            try:
                path.relative_to(ROOT)
            except ValueError:
                issues.append("path outside repository: " + relative)
                continue
            if not path.is_file():
                issues.append("missing: " + relative)
            else:
                try:
                    digest = source_sha256(path, normalization)
                except UnicodeDecodeError:
                    issues.append("text_lf source is not UTF-8: " + relative)
                    continue
                if source.get("sha256", {}).get(relative) != digest:
                    issues.append("stale SHA256: " + relative)
    elif not source.get("url", "").startswith("https://") or not source.get("version"):
        issues.append("external source lacks fixed version / HTTPS URL")
    return issues


def check(chunks, sources):
    errors = []
    ids = [chunk.get("id") for chunk in chunks]
    if len(ids) != len(set(ids)):
        errors.append("duplicate chunk IDs")
    for chunk in chunks:
        label = chunk.get("id", "?")
        if REQUIRED - chunk.keys():
            errors.append(label + " missing fields: " + str(sorted(REQUIRED - chunk.keys())))
        if chunk.get("schema") != "qec-pbc-rag-chunk/1":
            errors.append(label + " invalid schema")
        if chunk.get("claim_type") not in CLAIM_TYPES:
            errors.append(label + " invalid claim_type")
        for field in ("content", "title", "source_refs", "limitations", "validation"):
            if not chunk.get(field):
                errors.append(label + " empty " + field)
        for ref in chunk.get("source_refs", []):
            if ref.get("source_id") not in sources or not ref.get("locator"):
                errors.append(label + " invalid source reference")
        for related in chunk.get("related_ids", []):
            if related not in ids:
                errors.append(label + " unknown related ID: " + related)
    for source in sources.values():
        errors.extend(source["id"] + " " + issue for issue in source_issues(source))
    return {"ok": not errors, "chunks": len(chunks), "sources": len(sources), "errors": errors}


def hydrate(score, chunk, sources):
    result = dict(chunk)
    result["score"] = round(score, 6)
    result["citations"] = []
    for ref in chunk["source_refs"]:
        source = sources[ref["source_id"]]
        citation = {"source_id": source["id"], "title": source["title"],
                    "version": source["version"], "locator": ref["locator"]}
        if "url" in source:
            citation["url"] = source["url"]
            citation["freshness"] = "fixed_version_reviewed_" + source["retrieved_at"]
        else:
            citation["paths"] = source["paths"]
            if source.get("sha256_normalization"):
                citation["sha256_normalization"] = source["sha256_normalization"]
            citation["freshness"] = "stale" if source_issues(source) else "current_sha256"
        result["citations"].append(citation)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--query", help="Chinese/English evidence question")
    action.add_argument("--check", action="store_true", help="Check schema, links and source SHA256")
    action.add_argument("--self-test", action="store_true", help="Run fixed evidence-recall cases")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--layer", help="Optional exact layer filter")
    parser.add_argument("--claim-type", choices=sorted(CLAIM_TYPES))
    parser.add_argument("--status", help="Optional exact implementation_status filter")
    args = parser.parse_args()
    if args.top_k < 1:
        parser.error("--top-k must be positive")
    chunks, sources = load()
    if args.check:
        result = check(chunks, sources)
        exit_code = 0 if result["ok"] else 1
    elif args.self_test:
        cases = read_json(CORPUS / "query_cases.json")
        rows = []
        for case in cases["cases"]:
            found = [chunk["id"] for _, chunk in retrieve(case["query"], chunks, cases["top_k"])]
            rows.append({"query": case["query"], "found": found,
                         "ok": bool(set(found) & set(case["expected_any"]))})
        result = {"ok": all(row["ok"] for row in rows), "passed": sum(row["ok"] for row in rows),
                  "total": len(rows), "top_k": cases["top_k"], "cases": rows}
        exit_code = 0 if result["ok"] else 1
    else:
        selected = [chunk for chunk in chunks if
                    (not args.layer or chunk["layer"] == args.layer) and
                    (not args.claim_type or chunk["claim_type"] == args.claim_type) and
                    (not args.status or chunk["implementation_status"] == args.status)]
        result = {"query": args.query, "method": "lexical_bm25_english_tokens_chinese_bigrams",
                  "matches": [hydrate(score, chunk, sources) for score, chunk in
                              retrieve(args.query, selected, args.top_k)]}
        exit_code = 0
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
