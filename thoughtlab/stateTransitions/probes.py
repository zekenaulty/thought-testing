"""Frozen probe definitions for the first true checkpoint-fork pilot."""

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

ANCESTRY_RESPONSE_FORMAT: Final[dict[str, Any]] = {
    "type": "text",
    "mime_type": "application/json",
    "schema": {
        "type": "object",
        "properties": {
            "knowledge": _KNOWLEDGE,
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "role": {
                            "type": "string",
                            "enum": ["fact", "constraint", "objective", "plan", "unknown"],
                        },
                        "status": {
                            "type": "string",
                            "enum": [
                                "active",
                                "candidate",
                                "selected",
                                "rejected",
                                "inactive",
                                "unknown",
                            ],
                        },
                    },
                    "required": ["id", "role", "status"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["knowledge", "items"],
        "additionalProperties": False,
    },
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

_PREAMBLE = """\
The preceding experimental history, if any, is the only source for this
question. Recover only state made available by that history. The identifiers are
semantically opaque: do not infer them from generic patterns and do not invent
them.

If the requested state cannot be recovered, set "knowledge" to "unknown" and
return an empty collection. If any requested state is recoverable, set
"knowledge" to "known" and return every requested item you can recover.

Return exactly one JSON object conforming to the supplied schema. Return no
markdown or explanation.

"""

PROBES: Final[dict[str, dict[str, Any]]] = {
    "active_ancestry": {
        "kind": "ancestry",
        "response_format": ANCESTRY_RESPONSE_FORMAT,
        "prompt": _PREAMBLE
        + """\
Recover every non-plan ledger entry inherited from the shared pre-fork state.
For each entry, return its exact identifier, assigned role, and current lifecycle
status. Do not include plan entries.

Use the keys "knowledge" and "items".
""",
    },
    "active_objective": {
        "kind": "id_set",
        "response_format": ID_SET_RESPONSE_FORMAT,
        "prompt": _PREAMBLE
        + """\
Recover the exact opaque identifier of every objective whose current lifecycle
status is active.

Use the keys "knowledge" and "ids".
""",
    },
    "active_constraint": {
        "kind": "id_set",
        "response_format": ID_SET_RESPONSE_FORMAT,
        "prompt": _PREAMBLE
        + """\
Recover the exact opaque identifier of every constraint whose current lifecycle
status is active.

Use the keys "knowledge" and "ids".
""",
    },
    "candidate_plans": {
        "kind": "id_set",
        "response_format": ID_SET_RESPONSE_FORMAT,
        "prompt": _PREAMBLE
        + """\
Recover every exact opaque plan identifier that existed as a candidate
immediately before the current plan-selection transition. Include the plan that
is now selected and every plan that is now rejected.

Use the keys "knowledge" and "ids".
""",
    },
    "selected_plan": {
        "kind": "id_set",
        "response_format": ID_SET_RESPONSE_FORMAT,
        "prompt": _PREAMBLE
        + """\
Recover the exact opaque identifier of every plan whose current lifecycle status
is selected.

Use the keys "knowledge" and "ids".
""",
    },
    "rejected_plans": {
        "kind": "id_set",
        "response_format": ID_SET_RESPONSE_FORMAT,
        "prompt": _PREAMBLE
        + """\
Recover the exact opaque identifier of every plan whose current lifecycle status
is rejected.

Use the keys "knowledge" and "ids".
""",
    },
    "utility_ranking": {
        "kind": "ranking",
        "response_format": RANKING_RESPONSE_FORMAT,
        "prompt": _PREAMBLE
        + """\
Recover the original relative utility ranking of every registered plan. Return
the exact opaque plan identifiers ordered from highest utility to lowest utility.
Do not return the numeric utility values.

Use the keys "knowledge" and "ids_high_to_low".
""",
    },
}

PROBE_IDS: Final[tuple[str, ...]] = tuple(PROBES)
