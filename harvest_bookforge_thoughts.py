#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, re, subprocess, sys
from pathlib import Path
from typing import Any

DEFAULT_REF = "e4dd16f72a2d8a1ba077f12e1a2d6982786d9554"

def git(repo: Path, *args: str) -> str:
    p = subprocess.run(
        ["git", "-C", str(repo), *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace"
    )
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or f"git {' '.join(args)} failed")
    return p.stdout

def sig_value(part: dict[str, Any]):
    for k in ("thoughtSignature", "thought_signature", "thoughtsignature"):
        if part.get(k):
            return part[k]
    fc = part.get("functionCall")
    if isinstance(fc, dict):
        for k in ("thoughtSignature", "thought_signature", "thoughtsignature"):
            if fc.get(k):
                return fc[k]
    return None

def walk(node: Any, ptr="$"):
    if isinstance(node, dict):
        if sig_value(node):
            yield ptr, node
        for k, v in node.items():
            yield from walk(v, f"{ptr}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, f"{ptr}[{i}]")

def prompt_text(payload: dict[str, Any]) -> str:
    prompt = payload.get("prompt")
    if not isinstance(prompt, dict):
        return ""
    chunks = []
    if prompt.get("system"):
        chunks.append("SYSTEM:\n" + str(prompt["system"]))
    for m in prompt.get("messages", []) or []:
        if isinstance(m, dict) and m.get("content"):
            chunks.append(f"{str(m.get('role') or 'unknown').upper()}:\n{m['content']}")
    return "\n\n".join(chunks)

def safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s or "thought").strip("-_.")[:36] or "thought"

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="Path to local BookForge repo")
    ap.add_argument("--ref", default=DEFAULT_REF)
    ap.add_argument("--out", default="bookforge-thought-corpus")
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    if not (repo / ".git").exists():
        print(f"Not a git repository: {repo}", file=sys.stderr)
        return 2

    try:
        ref = git(repo, "rev-parse", "--verify", f"{args.ref}^{{commit}}").strip()
        paths = [
            x.strip() for x in git(repo, "ls-tree", "-r", "--name-only", ref).splitlines()
            if x.strip().startswith("workspace/logs/llm/") and x.strip().endswith(".json")
        ]
    except Exception as e:
        print(e, file=sys.stderr)
        return 2

    out = Path(args.out).expanduser().resolve()
    capdir = out / "capsules"
    capdir.mkdir(parents=True, exist_ok=True)

    records = []
    failures = []
    for path in paths:
        try:
            payload = json.loads(git(repo, "show", f"{ref}:{path}"))
            if not isinstance(payload, dict):
                continue
            seen = set()
            for ptr, part in walk(payload):
                sig = str(sig_value(part))
                h = hashlib.sha256(sig.encode()).hexdigest()
                if h in seen:
                    continue
                seen.add(h)
                extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
                records.append({
                    "schema_version": "bookforge_historical_thought_capsule_v1",
                    "source_ref": ref,
                    "source_path": path,
                    "json_pointer": ptr,
                    "label": payload.get("label"),
                    "created_at": payload.get("created_at"),
                    "provider": payload.get("provider"),
                    "model": payload.get("model"),
                    "book_id": extra.get("book_id"),
                    "chapter": extra.get("chapter"),
                    "scene": extra.get("scene"),
                    "phase_id": extra.get("phase_id") or extra.get("phase"),
                    "turn_id": extra.get("turn_id") or extra.get("turn"),
                    "signature_sha256": h,
                    "signature_chars": len(sig),
                    "visible_output": str(payload.get("text") or ""),
                    "prompt_text": prompt_text(payload),
                    "signed_part": part,
                })
        except Exception as e:
            failures.append({"path": path, "error": str(e)})

    records.sort(key=lambda r: (str(r["source_path"]), str(r["signature_sha256"])))
    for i, r in enumerate(records, 1):
        fn = f"{i:04d}_{safe(str(r.get('label') or 'thought'))}_{r['signature_sha256'][:12]}.json"
        r["corpus_file"] = f"capsules/{fn}"
        (capdir / fn).write_text(json.dumps(r, indent=2, ensure_ascii=True), encoding="utf-8")

    index = {
        "schema_version": "bookforge_historical_thought_corpus_v1",
        "source_repo": str(repo),
        "requested_ref": args.ref,
        "resolved_ref": ref,
        "json_files_examined": len(paths),
        "capsule_count": len(records),
        "parse_failures": failures,
        "capsules": [
            {k: r.get(k) for k in (
                "corpus_file","source_path","label","created_at","provider","model",
                "book_id","chapter","scene","phase_id","turn_id",
                "signature_sha256","signature_chars"
            )} for r in records
        ]
    }
    (out / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=True), encoding="utf-8")

    print(f"Resolved ref: {ref}")
    print(f"JSON log files examined: {len(paths)}")
    print(f"Thought capsules extracted: {len(records)}")
    print(f"Output: {out}")
    if failures:
        print(f"Failures: {len(failures)}")

    if records:
        print("\nLargest signatures:")
        for r in sorted(records, key=lambda x: x["signature_chars"], reverse=True)[:args.top]:
            print(f"{r['signature_chars']:>8}  {str(r.get('model') or ''):24}  {str(r.get('label') or ''):28}  {r['source_path']}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
