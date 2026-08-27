"""Frozen neutral probes for the native mutable planning-state pilot."""

from __future__ import annotations

from typing import Any, Final


ACK_RESPONSE_FORMAT: Final[dict[str, Any]] = {
    "type": "text",
    "mime_type": "application/json",
    "schema": {
        "type": "object",
        "properties": {"ack": {"type": "boolean"}},
        "required": ["ack"],
        "additionalProperties": False,
    },
}

_KNOWLEDGE: Final[dict[str, Any]] = {
    "type": "string",
    "enum": ["known", "unknown"],
}

ID_SET_RESPONSE_FORMAT: Final[dict[str, Any]] = {
    "type": "text",
    "mime_type": "application/json",
    "schema": {
        "type": "object",
        "properties": {
            "knowledge": _KNOWLEDGE,
            "ids": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["knowledge", "ids"],
        "additionalProperties": False,
    },
}

RANKING_RESPONSE_FORMAT: Final[dict[str, Any]] = {
    "type": "text",
    "mime_type": "application/json",
    "schema": {
        "type": "object",
        "properties": {
            "knowledge": _KNOWLEDGE,
            "ids_high_to_low": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["knowledge", "ids_high_to_low"],
        "additionalProperties": False,
    },
}

VIABILITY_RESPONSE_FORMAT: Final[dict[str, Any]] = {
    "type": "text",
    "mime_type": "application/json",
    "schema": {
        "type": "object",
        "properties": {
            "knowledge": _KNOWLEDGE,
            "viable_ids": {"type": "array", "items": {"type": "string"}},
            "nonviable_ids": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["knowledge", "viable_ids", "nonviable_ids"],
        "additionalProperties": False,
    },
}

_PREAMBLE: Final[str] = """\
The preceding experimental history, if any, is the only source for this
question. Recover only the current local planning state made available by that
history. Identifiers are semantically opaque: do not infer them from spelling or
generic patterns and do not invent them.

An established empty collection is known state. If the requested state is
recoverable, set "knowledge" to "known" and return its complete collection,
which may be empty. If it cannot be recovered, set "knowledge" to "unknown" and
return empty arrays for every collection key.

Return exactly one JSON object conforming to the supplied schema. Return no
markdown or explanation.

"""

PROBES: Final[dict[str, dict[str, Any]]] = {
    "candidate_registry": {
        "kind": "id_set",
        "response_format": ID_SET_RESPONSE_FORMAT,
        "prompt": _PREAMBLE
        + """\
Recover every exact opaque identifier currently registered as a candidate.
Order does not matter.

Use the keys "knowledge" and "ids".
""",
    },
    "utility_ranking": {
        "kind": "ranking",
        "response_format": RANKING_RESPONSE_FORMAT,
        "prompt": _PREAMBLE
        + """\
Recover the complete current utility ranking of all registered candidates.
Return their exact opaque identifiers from highest utility to lowest utility.
Include a registered candidate even if it is currently nonviable. Do not return
numeric utilities.

Use the keys "knowledge" and "ids_high_to_low".
""",
    },
    "viability_partition": {
        "kind": "viability",
        "response_format": VIABILITY_RESPONSE_FORMAT,
        "prompt": _PREAMBLE
        + """\
Partition every currently registered candidate into currently viable and
currently nonviable identifiers. The arrays must be disjoint and together cover
the complete current candidate registry. Order within each array does not
matter.

Use the keys "knowledge", "viable_ids", and "nonviable_ids".
""",
    },
    "selected_candidate": {
        "kind": "id_set",
        "response_format": ID_SET_RESPONSE_FORMAT,
        "prompt": _PREAMBLE
        + """\
Recover the exact opaque identifier of every currently selected candidate. If
the history establishes that no candidate is selected, return "known" with an
empty "ids" array.

Use the keys "knowledge" and "ids".
""",
    },
}

PROBE_IDS: Final[tuple[str, ...]] = tuple(PROBES)

