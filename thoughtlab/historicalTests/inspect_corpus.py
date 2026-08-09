#!/usr/bin/env python3
"""Inspect and rank harvested BookForge thought capsules without API calls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def score_row(row: dict[str, Any], root: Path) -> tuple[int, int, int]:
    capsule_rel = row.get("corpus_file")
    prompt_chars = 0
    visible_chars = 0
    if capsule_rel:
        path = root / str(capsule_rel)
        try:
            cap = json.loads(path.read_text(encoding="utf-8"))
            prompt_chars = len(str(cap.get("prompt_text") or ""))
            visible_chars = len(str(cap.get("visible_output") or ""))
        except Exception:
            pass
    sig_chars = int(row.get("signature_chars") or 0)
    # Prefer large signatures with rich withheld ground truth and a nontrivial
    # visible control surface.
    return sig_chars, prompt_chars, visible_chars


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--index",
        default="bookforge-thought-corpus/index.json",
        help="Harvested corpus index.",
    )
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()

    index_path = Path(args.index).expanduser().resolve()
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    root = index_path.parent
    rows = list(payload.get("capsules") or [])
    ranked = sorted(rows, key=lambda r: score_row(r, root), reverse=True)

    print(f"Corpus: {index_path}")
    print(f"Capsules: {len(rows)}")
    print()
    print(f"{'#':>3} {'sig':>9} {'model':24} {'label':28} {'file'}")
    print("-" * 120)
    for i, row in enumerate(ranked[: max(0, args.top)], 1):
        sig = int(row.get("signature_chars") or 0)
        print(
            f"{i:>3} {sig:>9} "
            f"{str(row.get('model') or '')[:24]:24} "
            f"{str(row.get('label') or '')[:28]:28} "
            f"{row.get('corpus_file')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
