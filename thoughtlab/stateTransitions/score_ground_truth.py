"""Pure normalization and exact scoring for fork-pilot tomography."""

from __future__ import annotations

from itertools import combinations
from typing import Any

from thoughtlab.opaque_ids import is_opaque_id

ANCESTRY_ROLES = {"fact", "constraint", "objective", "plan", "unknown"}
LIFECYCLE_STATUSES = {
    "active",
    "candidate",
    "selected",
    "rejected",
    "inactive",
    "unknown",
}


def validate_probe_answer(kind: str, value: Any) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return {"schema_valid": False, "errors": ["top-level value is not an object"]}

    knowledge = value.get("knowledge")
    if knowledge not in {"known", "unknown"}:
        errors.append("knowledge must be known or unknown")

    collection: list[Any] | None = None
    if kind == "ancestry":
        if set(value) != {"knowledge", "items"}:
            errors.append("ancestry answer must contain exactly knowledge and items")
        collection = value.get("items")
        if not isinstance(collection, list):
            errors.append("items must be an array")
        else:
            for index, item in enumerate(collection):
                if not isinstance(item, dict):
                    errors.append(f"items[{index}] must be an object")
                    continue
                if set(item) != {"id", "role", "status"}:
                    errors.append(f"items[{index}] has the wrong keys")
                if not isinstance(item.get("id"), str):
                    errors.append(f"items[{index}].id must be a string")
                if item.get("role") not in ANCESTRY_ROLES:
                    errors.append(f"items[{index}].role is invalid")
                if item.get("status") not in LIFECYCLE_STATUSES:
                    errors.append(f"items[{index}].status is invalid")
    elif kind == "id_set":
        if set(value) != {"knowledge", "ids"}:
            errors.append("set answer must contain exactly knowledge and ids")
        collection = value.get("ids")
        if not isinstance(collection, list):
            errors.append("ids must be an array")
        elif any(not isinstance(item, str) for item in collection):
            errors.append("every ids element must be a string")
    elif kind == "ranking":
        if set(value) != {"knowledge", "ids_high_to_low"}:
            errors.append(
                "ranking answer must contain exactly knowledge and ids_high_to_low"
            )
        collection = value.get("ids_high_to_low")
        if not isinstance(collection, list):
            errors.append("ids_high_to_low must be an array")
        elif any(not isinstance(item, str) for item in collection):
            errors.append("every ranking element must be a string")
    else:
        errors.append(f"unknown probe kind: {kind}")

    return {
        "schema_valid": not errors,
        "errors": errors,
        "knowledge": knowledge,
        "collection": collection if isinstance(collection, list) else None,
    }


def _ids_from_collection(kind: str, collection: list[Any]) -> list[str]:
    if kind == "ancestry":
        return [str(item.get("id")) for item in collection if isinstance(item, dict)]
    return [item for item in collection if isinstance(item, str)]


def _pairwise_order_score(actual: list[str], expected: list[str]) -> dict[str, int]:
    actual_positions = {item: index for index, item in enumerate(actual)}
    correct = 0
    total = 0
    for left, right in combinations(expected, 2):
        total += 1
        if left in actual_positions and right in actual_positions:
            correct += int(actual_positions[left] < actual_positions[right])
    return {"correct": correct, "total": total}


def score_probe_answer(
    *,
    kind: str,
    normalized: dict[str, Any],
    expected: list[Any],
    truth_universe: set[str],
) -> dict[str, Any]:
    if not normalized.get("schema_valid"):
        return {
            "scored": False,
            "exact": False,
            "outcome": "schema_invalid",
            "errors": list(normalized.get("errors") or []),
        }

    collection = list(normalized.get("collection") or [])
    actual_ids = _ids_from_collection(kind, collection)
    duplicate_ids = sorted({item for item in actual_ids if actual_ids.count(item) > 1})
    noncanonical_ids = sorted({item for item in actual_ids if not is_opaque_id(item)})
    foreign_ids = sorted(set(actual_ids) - truth_universe)
    expected_ids = _ids_from_collection(kind, expected)
    expected_foreign_ids = sorted(set(expected_ids) - truth_universe)
    missing_ids = sorted(set(expected_ids) - set(actual_ids))
    extra_ids = sorted(set(actual_ids) - set(expected_ids))

    if normalized.get("knowledge") == "unknown":
        exact = False
        outcome = "unknown_for_known"
    elif kind == "ancestry":
        actual_map = {
            item["id"]: (item["role"], item["status"])
            for item in collection
            if isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and isinstance(item.get("role"), str)
            and isinstance(item.get("status"), str)
        }
        expected_map = {
            item["id"]: (item["role"], item["status"])
            for item in expected
            if isinstance(item, dict)
        }
        exact = (
            not duplicate_ids
            and not noncanonical_ids
            and not foreign_ids
            and not expected_foreign_ids
            and actual_map == expected_map
            and len(collection) == len(expected)
        )
        outcome = "exact_known" if exact else "value_mismatch"
    elif kind == "id_set":
        exact = (
            not duplicate_ids
            and not noncanonical_ids
            and not foreign_ids
            and not expected_foreign_ids
            and set(actual_ids) == set(expected_ids)
            and len(actual_ids) == len(expected_ids)
        )
        outcome = "exact_known" if exact else "value_mismatch"
    elif kind == "ranking":
        exact = (
            not duplicate_ids
            and not noncanonical_ids
            and not foreign_ids
            and not expected_foreign_ids
            and actual_ids == expected_ids
        )
        outcome = "exact_known" if exact else "value_mismatch"
    else:
        exact = False
        outcome = "schema_invalid"

    result: dict[str, Any] = {
        "scored": True,
        "exact": exact,
        "outcome": outcome,
        "knowledge": normalized.get("knowledge"),
        "duplicate_ids": duplicate_ids,
        "noncanonical_ids": noncanonical_ids,
        "foreign_ids": foreign_ids,
        "expected_foreign_ids": expected_foreign_ids,
        "missing_ids": missing_ids,
        "extra_ids": extra_ids,
        "truth_universe_hits": sorted(set(actual_ids) & truth_universe),
    }
    if kind == "ranking":
        pairwise_valid = not (
            duplicate_ids
            or noncanonical_ids
            or foreign_ids
            or expected_foreign_ids
        )
        result["pairwise_order"] = (
            _pairwise_order_score(actual_ids, expected_ids)
            if pairwise_valid
            else {"correct": 0, "total": 0}
        )
        result["pairwise_order_valid"] = pairwise_valid
    return result
