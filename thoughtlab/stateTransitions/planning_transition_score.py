"""Missing-safe normalization and scoring for mutable planning-state probes."""

from __future__ import annotations

from itertools import combinations
import hashlib
from typing import Any

from thoughtlab.opaque_ids import is_opaque_id


COLLECTION_KEYS = {
    "id_set": ("ids",),
    "ranking": ("ids_high_to_low",),
    "viability": ("viable_ids", "nonviable_ids"),
}


def validate_planning_answer(kind: str, value: Any) -> dict[str, Any]:
    """Validate only the structural contract, including unknown-empty semantics."""
    if not isinstance(value, dict):
        return {
            "schema_valid": False,
            "errors": ["top-level value is not an object"],
            "knowledge": None,
            "collections": {},
            "all_ids": [],
        }

    keys = COLLECTION_KEYS.get(kind)
    if keys is None:
        return {
            "schema_valid": False,
            "errors": [f"unknown probe kind: {kind}"],
            "knowledge": value.get("knowledge"),
            "collections": {},
            "all_ids": [],
        }

    errors: list[str] = []
    expected_keys = {"knowledge", *keys}
    if set(value) != expected_keys:
        errors.append(f"answer keys must be exactly {sorted(expected_keys)}")

    knowledge = value.get("knowledge")
    if knowledge not in {"known", "unknown"}:
        errors.append("knowledge must be known or unknown")

    collections: dict[str, list[str] | None] = {}
    all_ids: list[str] = []
    for key in keys:
        collection = value.get(key)
        if not isinstance(collection, list):
            errors.append(f"{key} must be an array")
            collections[key] = None
            continue
        if any(not isinstance(item, str) for item in collection):
            errors.append(f"every {key} element must be a string")
            collections[key] = None
            continue
        copied = list(collection)
        collections[key] = copied
        all_ids.extend(copied)

    if knowledge == "unknown" and any(
        isinstance(collection, list) and collection
        for collection in collections.values()
    ):
        errors.append("unknown answers must use empty collections")

    return {
        "schema_valid": not errors,
        "errors": errors,
        "knowledge": knowledge,
        "collections": collections,
        "all_ids": all_ids,
    }


def empty_shape(kind: str, normalized: dict[str, Any]) -> bool:
    keys = COLLECTION_KEYS.get(kind, ())
    collections = normalized.get("collections")
    return bool(
        normalized.get("schema_valid")
        and normalized.get("knowledge") == "unknown"
        and isinstance(collections, dict)
        and all(collections.get(key) == [] for key in keys)
    )


def _duplicates(values: list[str]) -> list[str]:
    return sorted({value for value in values if values.count(value) > 1})


def _value_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _expected_collections(kind: str, expected: dict[str, Any]) -> dict[str, list[str]]:
    return {
        key: list(expected.get(key) or [])
        for key in COLLECTION_KEYS.get(kind, ())
    }


def score_planning_answer(
    *,
    kind: str,
    normalized: dict[str, Any],
    expected: dict[str, Any],
    candidate_universe: set[str],
    source_id_universe: set[str],
    condition_id: str,
    other_trial_universe: set[str] | None = None,
) -> dict[str, Any]:
    """Score exact truth while separately classifying malformed and foreign IDs."""
    if not normalized.get("schema_valid"):
        return {
            "scored": False,
            "exact": False,
            "outcome": "schema_invalid",
            "errors": list(normalized.get("errors") or []),
            "returned_ids": [],
        }

    keys = COLLECTION_KEYS.get(kind, ())
    collections = normalized.get("collections")
    if not isinstance(collections, dict) or any(
        not isinstance(collections.get(key), list) for key in keys
    ):
        return {
            "scored": False,
            "exact": False,
            "outcome": "schema_invalid",
            "errors": ["normalized collections are incomplete"],
            "returned_ids": [],
        }

    actual = {key: list(collections[key]) for key in keys}
    expected_collections = _expected_collections(kind, expected)
    all_ids = [item for key in keys for item in actual[key]]
    duplicate_ids = _duplicates(all_ids)
    duplicate_values_by_collection = {
        key: _duplicates(actual[key]) for key in keys if _duplicates(actual[key])
    }
    noncanonical_values = sorted({item for item in all_ids if not is_opaque_id(item)})
    noncanonical_value_hashes = [_value_hash(item) for item in noncanonical_values]
    canonical_ids = [item for item in all_ids if is_opaque_id(item)]
    source_universe = set(source_id_universe)
    other_universe = set(other_trial_universe or set())
    reviewed_universe = source_universe | other_universe
    foreign_reviewed_ids = sorted(
        (set(canonical_ids) - source_universe) & reviewed_universe
    )
    unknown_canonical_values = sorted(set(canonical_ids) - reviewed_universe)
    unknown_canonical_value_hashes = [
        _value_hash(item) for item in unknown_canonical_values
    ]
    cross_trial_ids = sorted(set(canonical_ids) & other_universe)
    role_inappropriate_ids = sorted(set(canonical_ids) & {condition_id})
    expected_ids = {
        item for key in keys for item in expected_collections.get(key, [])
    }
    missing_ids = sorted(expected_ids - set(canonical_ids))
    extra_reviewed_ids = sorted((set(canonical_ids) - expected_ids) & reviewed_universe)
    extra_unknown_canonical_hashes = sorted(
        _value_hash(item)
        for item in set(canonical_ids) - expected_ids - reviewed_universe
    )

    truth_shape_errors: list[str] = []
    if kind == "viability":
        viable = actual["viable_ids"]
        nonviable = actual["nonviable_ids"]
        overlap = sorted(set(viable) & set(nonviable))
        if overlap:
            truth_shape_errors.append("viability arrays overlap")
        if set(viable) | set(nonviable) != set(candidate_universe):
            truth_shape_errors.append(
                "viability union does not equal the checkpoint candidate registry"
            )

    knowledge_exact = normalized.get("knowledge") == expected.get("knowledge")
    collections_exact = False
    if kind in {"id_set", "viability"}:
        collections_exact = all(
            not _duplicates(actual[key])
            and set(actual[key]) == set(expected_collections[key])
            and len(actual[key]) == len(expected_collections[key])
            for key in keys
        )
    elif kind == "ranking":
        collections_exact = actual["ids_high_to_low"] == expected_collections[
            "ids_high_to_low"
        ]

    exact = bool(
        knowledge_exact
        and collections_exact
        and not duplicate_ids
        and not noncanonical_values
        and not foreign_reviewed_ids
        and not unknown_canonical_values
        and not role_inappropriate_ids
        and not truth_shape_errors
    )
    if exact:
        outcome = "exact"
    elif normalized.get("knowledge") == "unknown":
        outcome = "unknown_for_known"
    else:
        outcome = "value_mismatch"

    result: dict[str, Any] = {
        "scored": True,
        "exact": exact,
        "outcome": outcome,
        "knowledge": normalized.get("knowledge"),
        "knowledge_exact": knowledge_exact,
        "returned_reviewed_ids": [
            item for item in canonical_ids if item in reviewed_universe
        ],
        "unknown_canonical_value_sha256": unknown_canonical_value_hashes,
        "duplicate_canonical_ids": sorted(
            item
            for item in duplicate_ids
            if is_opaque_id(item) and item in reviewed_universe
        ),
        "duplicate_unknown_canonical_value_sha256": sorted(
            _value_hash(item)
            for item in duplicate_ids
            if is_opaque_id(item) and item not in reviewed_universe
        ),
        "duplicate_noncanonical_value_sha256": sorted(
            _value_hash(item) for item in duplicate_ids if not is_opaque_id(item)
        ),
        "within_collection_duplicate_canonical_ids": {
            key: [
                item
                for item in values
                if is_opaque_id(item) and item in reviewed_universe
            ]
            for key, values in duplicate_values_by_collection.items()
        },
        "within_collection_duplicate_unknown_canonical_sha256": {
            key: [
                _value_hash(item)
                for item in values
                if is_opaque_id(item) and item not in reviewed_universe
            ]
            for key, values in duplicate_values_by_collection.items()
        },
        "within_collection_duplicate_noncanonical_sha256": {
            key: [_value_hash(item) for item in values if not is_opaque_id(item)]
            for key, values in duplicate_values_by_collection.items()
        },
        "noncanonical_value_sha256": noncanonical_value_hashes,
        "foreign_reviewed_ids": foreign_reviewed_ids,
        "unknown_foreign_canonical_value_sha256": unknown_canonical_value_hashes,
        "cross_trial_ids": cross_trial_ids,
        "role_inappropriate_ids": role_inappropriate_ids,
        "missing_ids": missing_ids,
        "extra_reviewed_ids": extra_reviewed_ids,
        "extra_unknown_canonical_value_sha256": extra_unknown_canonical_hashes,
        "truth_shape_errors": truth_shape_errors,
        "source_universe_hits": sorted(set(all_ids) & source_universe),
    }
    if kind == "ranking":
        expected_ranking = expected_collections["ids_high_to_low"]
        actual_ranking = actual["ids_high_to_low"]
        actual_positions = {
            value: index
            for index, value in enumerate(actual_ranking)
            if is_opaque_id(value)
        }
        correct = sum(
            left in actual_positions
            and right in actual_positions
            and actual_positions[left] < actual_positions[right]
            for left, right in combinations(expected_ranking, 2)
        )
        result["pairwise_order"] = {
            "correct": correct,
            "total": len(list(combinations(expected_ranking, 2))),
        }
    return result


def normalized_state(kind: str, normalized: dict[str, Any]) -> dict[str, Any] | None:
    if not normalized.get("schema_valid") or normalized.get("knowledge") != "known":
        return None
    collections = normalized.get("collections")
    keys = COLLECTION_KEYS.get(kind, ())
    if not isinstance(collections, dict) or any(
        not isinstance(collections.get(key), list) for key in keys
    ):
        return None
    if kind == "ranking":
        return {"ids_high_to_low": list(collections["ids_high_to_low"])}
    return {key: sorted(collections[key]) for key in keys}


def expected_normalized(kind: str, expected: dict[str, Any]) -> dict[str, Any]:
    keys = COLLECTION_KEYS[kind]
    if kind == "ranking":
        return {"ids_high_to_low": list(expected["ids_high_to_low"])}
    return {key: sorted(expected[key]) for key in keys}


def derive_delta(
    kind: str,
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    """Return the frozen mechanical state operation between normalized endpoints."""
    if kind == "id_set":
        before_ids = set(before["ids"])
        after_ids = set(after["ids"])
        return {
            "added_ids": sorted(after_ids - before_ids),
            "removed_ids": sorted(before_ids - after_ids),
            "stable": before_ids == after_ids,
        }
    if kind == "ranking":
        left = list(before["ids_high_to_low"])
        right = list(after["ids_high_to_low"])
        shared = set(left) & set(right)
        left_pos = {value: index for index, value in enumerate(left)}
        right_pos = {value: index for index, value in enumerate(right)}
        reversals = []
        for first, second in combinations(sorted(shared), 2):
            if (left_pos[first] < left_pos[second]) != (
                right_pos[first] < right_pos[second]
            ):
                reversals.append([first, second])
        return {
            "added_ids": sorted(set(right) - set(left)),
            "removed_ids": sorted(set(left) - set(right)),
            "pairwise_reversals": reversals,
            "stable": left == right,
        }
    if kind == "viability":
        return {
            "viable_added": sorted(
                set(after["viable_ids"]) - set(before["viable_ids"])
            ),
            "viable_removed": sorted(
                set(before["viable_ids"]) - set(after["viable_ids"])
            ),
            "nonviable_added": sorted(
                set(after["nonviable_ids"]) - set(before["nonviable_ids"])
            ),
            "nonviable_removed": sorted(
                set(before["nonviable_ids"]) - set(after["nonviable_ids"])
            ),
            "stable": before == after,
        }
    raise ValueError(f"unknown probe kind: {kind}")
