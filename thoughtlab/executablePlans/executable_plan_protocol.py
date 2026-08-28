"""Pure construction and simulation for the executable-policy pilot.

The module has no network client and does not read provider artifacts.  It
builds the complete deterministic experiment definition that is frozen before
execution, plus the small deterministic simulator used to score prospective
tool trajectories.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import random
import re
from typing import Any, Final

from thoughtlab.opaque_ids import generate_opaque_id, is_opaque_id


SCHEMA_VERSION: Final[str] = "native_executable_policy_definition_v1"
MANIFEST_SCHEMA_VERSION: Final[str] = "native_executable_policy_manifest_v1"
PROTOCOL_REVISION: Final[str] = "1.0_reviewed_repeated_policy_readouts"
EXPERIMENT_ID: Final[str] = "native_executable_policy_feasibility_v1"
MODEL: Final[str] = "gemini-3.7-flash"
API_URL: Final[str] = (
    "https://generativelanguage.googleapis.com/v1beta/interactions"
)
SYSTEM_INSTRUCTION: Final[str] = (
    "Accomplish the user's objective using the available tools. "
    "Do not expose private reasoning."
)

SOURCE_LABELS: Final[tuple[str, ...]] = ("source_A", "source_B")
INSPECT_TOOL: Final[str] = "inspect_environment"
APPLY_TOOL: Final[str] = "apply_operation"
VERIFY_TOOL: Final[str] = "verify_and_complete"
VERIFY_TOKEN: Final[str] = "VERIFY"
UNKNOWN_TOKEN: Final[str] = "UNKNOWN"

OBSERVATION_ROLES: Final[tuple[str, ...]] = (
    "one_operation",
    "two_ordered_operations",
    "no_operation",
)
OPERATION_ROLES: Final[tuple[str, ...]] = (
    "one_operation_primary",
    "one_operation_alternative",
    "open_gate_primary",
    "open_gate_alternative",
    "bind_config_primary",
    "bind_config_alternative",
)

PROSPECTIVE_REPEATS: Final[int] = 3
ATOMIC_READOUT_REPEATS: Final[int] = 2
STRUCTURED_POLICY_REPEATS: Final[int] = 2
TASK_ONLY_REPEATS: Final[int] = 3
OPEN_READOUT_REPEATS: Final[int] = 1
VISIBLE_ONLY_REPEATS: Final[int] = 1
PROBE_ONLY_REPEATS: Final[int] = 1
FULL_TASK_SEMANTIC_REPEATS: Final[int] = 2
MAX_POST_OBSERVATION_DECISIONS: Final[int] = 3

HTTP_TIMEOUT_SECONDS: Final[int] = 120
MAX_ATTEMPTS_PER_LOGICAL_REQUEST: Final[int] = 3
RETRY_BACKOFF_SECONDS: Final[tuple[float, ...]] = (2.0, 5.0)

TOOL_DECLARATIONS: Final[list[dict[str, Any]]] = [
    {
        "type": "function",
        "name": INSPECT_TOOL,
        "description": (
            "Inspect the simulated recovery environment and return its current "
            "opaque condition identifier."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": APPLY_TOOL,
        "description": (
            "Apply one available recovery operation by its exact opaque identifier."
        ),
        "parameters": {
            "type": "object",
            "properties": {"operation_id": {"type": "string"}},
            "required": ["operation_id"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": VERIFY_TOOL,
        "description": (
            "Verify the recovered environment and complete the task. This is "
            "terminal when the environment is ready."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
]

NO_FUNCTION_CALLS_TOOL_CHOICE: Final[dict[str, Any]] = {
    "allowed_tools": {"mode": "none"}
}

TRANSPORT_POLICY: Final[dict[str, Any]] = {
    "timeout_seconds_per_attempt": HTTP_TIMEOUT_SECONDS,
    "max_attempts_per_logical_request": MAX_ATTEMPTS_PER_LOGICAL_REQUEST,
    "retry_backoff_seconds": list(RETRY_BACKOFF_SECONDS),
    "retryable": [
        "transport_error",
        "http_408",
        "http_429",
        "http_500_502_503_504",
    ],
    "nonretryable": [
        "http_400_protocol_rejection",
        "http_other",
        "all_2xx_including_malformed_or_unfavorable",
    ],
    "selection_rule": "first_nonretryable_response_or_final_attempt",
    "retry_body": "byte_identical_canonical_json",
    "semantic_retries": "forbidden",
}


class DuplicateJsonKey(ValueError):
    """Raised when strict JSON parsing encounters a duplicate object key."""


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON in the protocol's sole normalized form."""

    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def strict_json_loads(text: str) -> Any:
    """Parse JSON while rejecting duplicate keys and non-finite numbers."""

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise DuplicateJsonKey(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> Any:
        raise ValueError(f"non-finite JSON number: {value}")

    def parse_finite_float(value: str) -> float:
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError(f"non-finite JSON number: {value}")
        return parsed

    return json.loads(
        text,
        object_pairs_hook=reject_duplicates,
        parse_constant=reject_nonfinite,
        parse_float=parse_finite_float,
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def derived_seed(master_seed: int, label: str) -> int:
    digest = hashlib.sha256(f"{master_seed}:{label}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def generation_config(seed: int) -> dict[str, Any]:
    """Return the frozen native/readout generation configuration."""

    return {
        "thinking_level": "high",
        "thinking_summaries": "none",
        "seed": seed,
        "max_output_tokens": 8192,
    }


def user_step(text: str) -> dict[str, Any]:
    return {
        "type": "user_input",
        "content": [{"type": "text", "text": text}],
    }


def build_executable_interaction_body(
    *,
    model: str,
    input_steps: list[dict[str, Any]],
    generation_config_value: dict[str, Any],
    response_format: dict[str, Any] | None = None,
    system_instruction: str | None = None,
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a stateless request without altering the archived API helper.

    The earlier frozen experiments hash ``thoughtlab.gemini_interactions``.
    Tool-specific fields therefore live here, in the new protocol boundary.
    """

    body: dict[str, Any] = {
        "model": model,
        "store": False,
        "stream": False,
        "background": False,
        "input": copy.deepcopy(input_steps),
        "generation_config": copy.deepcopy(generation_config_value),
    }
    if response_format is not None:
        body["response_format"] = copy.deepcopy(response_format)
    if system_instruction is not None:
        body["system_instruction"] = system_instruction
    if tools is not None:
        body["tools"] = copy.deepcopy(tools)
    return body


def _unique_opaque_ids(*, rng: random.Random, count: int) -> list[str]:
    values: list[str] = []
    while len(values) < count:
        value = generate_opaque_id(rng=rng)
        if value not in values:
            values.append(value)
    return values


def _role_aliases(master_seed: int) -> dict[str, str]:
    roles = [*OBSERVATION_ROLES, *OPERATION_ROLES]
    ids_rng = random.Random(derived_seed(master_seed, "opaque_id_values"))
    assignment_rng = random.Random(derived_seed(master_seed, "opaque_id_assignment"))
    values = _unique_opaque_ids(rng=ids_rng, count=len(roles))
    assignment_rng.shuffle(values)
    return dict(zip(roles, values, strict=True))


def render_task_text(task: dict[str, Any]) -> str:
    """Render the native task from opaque mappings and local affordances.

    The text states conditions, operation preconditions, and effects.  It never
    serializes an action sequence; choosing and ordering tools is left to the
    model.
    """

    aliases = task["report_aliases"]
    return f"""\
Recover a simulated relay to a ready state. Inspect the environment before
making any change. Never guess an inspection result, never apply an operation
whose precondition is false, and never apply a mutation to an environment that
is already ready. When the environment is ready, use the verification tool to
complete the task. Do not verify an environment that is not ready.

The inspection tool returns exactly one of these opaque condition identifiers:

- {aliases['one_operation']}: the traffic handoff is absent; every other
  readiness condition holds.
- {aliases['two_ordered_operations']}: the authorization gate is closed and the
  recovered configuration is unbound; every other readiness condition holds.
- {aliases['no_operation']}: the environment is already ready.

Available recovery operations have these exact opaque identifiers and local
affordances:

- {aliases['one_operation_primary']}: rebuild the traffic handoff from the
  retained lease. It is applicable only while the handoff is absent and makes
  the handoff present.
- {aliases['one_operation_alternative']}: activate the reserved traffic
  handoff. It is applicable only while the handoff is absent and makes the
  handoff present.
- {aliases['open_gate_primary']}: release the authorization gate through the
  standby controller. It is applicable only while the gate is closed and makes
  the gate open; it does not bind the configuration.
- {aliases['open_gate_alternative']}: release the authorization gate through
  the recovery token. It is applicable only while the gate is closed and makes
  the gate open; it does not bind the configuration.
- {aliases['bind_config_primary']}: bind the recovered configuration from the
  live manifest. It is applicable only while the gate is open through the
  standby controller and the configuration is unbound, and makes the
  configuration bound.
- {aliases['bind_config_alternative']}: bind the recovered configuration from
  the verified snapshot. It is applicable only while the gate is open through
  the recovery token and the configuration is unbound, and makes the
  configuration bound.

Use the available tools to accomplish the objective. Return no private
reasoning.
"""


def create_task(master_seed: int) -> dict[str, Any]:
    aliases = _role_aliases(master_seed)
    task: dict[str, Any] = {
        "report_aliases": aliases,
        "observation_order": [aliases[role] for role in OBSERVATION_ROLES],
        "operation_universe": sorted(aliases[role] for role in OPERATION_ROLES),
        "initial_state_by_observation": {
            aliases["one_operation"]: "handoff_absent",
            aliases["two_ordered_operations"]: "gate_closed_config_unbound",
            aliases["no_operation"]: "ready",
        },
        "transition_table": {
            "handoff_absent": {
                aliases["one_operation_primary"]: "ready",
                aliases["one_operation_alternative"]: "ready",
            },
            "gate_closed_config_unbound": {
                aliases["open_gate_primary"]: "gate_open_standby_config_unbound",
                aliases["open_gate_alternative"]: "gate_open_token_config_unbound",
            },
            "gate_open_standby_config_unbound": {
                aliases["bind_config_primary"]: "ready",
            },
            "gate_open_token_config_unbound": {
                aliases["bind_config_alternative"]: "ready",
            },
            "ready": {},
        },
    }
    task["valid_success_sequences"] = {
        aliases["one_operation"]: [
            [aliases["one_operation_primary"], VERIFY_TOKEN],
            [aliases["one_operation_alternative"], VERIFY_TOKEN],
        ],
        aliases["two_ordered_operations"]: [
            [
                aliases["open_gate_primary"],
                aliases["bind_config_primary"],
                VERIFY_TOKEN,
            ],
            [
                aliases["open_gate_alternative"],
                aliases["bind_config_alternative"],
                VERIFY_TOKEN,
            ],
        ],
        aliases["no_operation"]: [[VERIFY_TOKEN]],
    }
    task["task_text"] = render_task_text(task)
    return task


def source_generation_request(task: dict[str, Any], *, seed: int) -> dict[str, Any]:
    """Build the exact request used independently for both source artifacts."""

    return build_executable_interaction_body(
        model=MODEL,
        input_steps=[user_step(task["task_text"])],
        generation_config_value=generation_config(seed),
        system_instruction=SYSTEM_INSTRUCTION,
        tools=TOOL_DECLARATIONS,
    )


def atomic_prediction_prompt(observation_id: str) -> str:
    if not is_opaque_id(observation_id):
        raise ValueError("observation_id is not a canonical opaque ID")
    return f"""\
The pending inspection returned {observation_id}. Using only the preceding
preserved reasoning state, report the next tool action that had already been
prepared. Do not solve a new task. If it is unavailable, return unknown status
and a null next value.

For an operation, return its exact opaque identifier in "next". For immediate
verification, return "{VERIFY_TOKEN}". Return exactly one JSON object matching
the supplied schema, with no markdown or explanation.
"""


def task_only_prediction_prompt(observation_id: str) -> str:
    """Request a fresh next-action choice from the complete task, not retention."""

    if not is_opaque_id(observation_id):
        raise ValueError("observation_id is not a canonical opaque ID")
    return f"""\
Given the complete task and tool affordances above, the inspection returned
{observation_id}. Solve the task now and report the next valid tool action you
would choose. For an operation, return its exact opaque identifier in "next".
For immediate verification, return "{VERIFY_TOKEN}". If no valid action can be
determined, return unknown status and a null next value.

Return exactly one JSON object matching the supplied schema, with no markdown
or explanation.
"""


def structured_policy_prompt(observation_ids: list[str] | tuple[str, ...]) -> str:
    if len(observation_ids) != 3 or len(set(observation_ids)) != 3:
        raise ValueError("exactly three distinct observation IDs are required")
    if any(not is_opaque_id(value) for value in observation_ids):
        raise ValueError("all observation IDs must be canonical opaque IDs")
    rows = "\n".join(f"- {value}" for value in observation_ids)
    return f"""\
Using only the preceding preserved reasoning state, report the intended
successful tool sequence under each possible pending inspection result listed
below. Do not solve a new task. The sequence must contain exact opaque operation
identifiers and end with "{VERIFY_TOKEN}" when complete.

Inspection results:
{rows}

Return exactly one policy entry for each listed result. Use status "known" for
a complete successful sequence, "partial" for an incomplete ordered prefix,
or "unknown" with an empty sequence when unavailable. Return exactly one JSON
object matching the supplied schema, with no markdown or explanation.
"""


def open_readout_prompt() -> str:
    return """\
Using only the preceding preserved reasoning state, describe any task and
intended course of action that had already been established. Do not create a
new plan. If none is recoverable, say UNKNOWN.
"""


def full_task_semantic_prompt() -> str:
    """Semantic task-adherence control with no carrier or pending tool call."""

    return """\
Given only the complete task and tool affordances above, describe the task and
the course of action you would plan now. Do not claim to recover a prior hidden
state. If the task cannot be understood, say UNKNOWN.
"""


def atomic_response_format(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "text",
        "mime_type": "application/json",
        "schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["known", "unknown"]},
                "next": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "null"},
                    ]
                },
            },
            "required": ["status", "next"],
            "additionalProperties": False,
        },
    }


def structured_policy_response_format(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "text",
        "mime_type": "application/json",
        "schema": {
            "type": "object",
            "properties": {
                "policies": {
                    "type": "array",
                    "minItems": 3,
                    "maxItems": 3,
                    "items": {
                        "type": "object",
                        "properties": {
                            "observation": {
                                "type": "string",
                            },
                            "status": {
                                "type": "string",
                                "enum": ["known", "partial", "unknown"],
                            },
                            "sequence": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                },
                                "maxItems": MAX_POST_OBSERVATION_DECISIONS,
                            },
                        },
                        "required": ["observation", "status", "sequence"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["policies"],
            "additionalProperties": False,
        },
    }


OPEN_RESPONSE_FORMAT: Final[dict[str, Any]] = {"type": "text"}


def initial_simulator_state(
    task: dict[str, Any], observation_id: str
) -> dict[str, Any]:
    """Create the post-inspection state for one counterfactual result."""

    states = task.get("initial_state_by_observation", {})
    if observation_id not in states:
        raise ValueError("unknown observation identifier")
    return {
        "observation_id": observation_id,
        "environment_state": states[observation_id],
        "decisions": 0,
        "applied_operations": [],
        "terminal": False,
        "success": False,
        "invalid_reason": None,
    }


def canonical_action_token(tool_name: str, arguments: Any) -> str:
    """Normalize a model function call into the sequence token used in scores."""

    if not isinstance(arguments, dict):
        raise ValueError("function-call arguments must be an object")
    if tool_name == APPLY_TOOL:
        if set(arguments) != {"operation_id"}:
            raise ValueError("apply_operation requires only operation_id")
        operation_id = arguments["operation_id"]
        if not is_opaque_id(operation_id):
            raise ValueError("operation_id is not a canonical opaque ID")
        return operation_id
    if tool_name == VERIFY_TOOL:
        if arguments:
            raise ValueError("verify_and_complete takes no arguments")
        return VERIFY_TOKEN
    if tool_name == INSPECT_TOOL:
        if arguments:
            raise ValueError("inspect_environment takes no arguments")
        return "INSPECT"
    raise ValueError(f"unknown tool: {tool_name}")


def apply_simulator_action(
    task: dict[str, Any],
    state: dict[str, Any],
    tool_name: str,
    arguments: Any,
) -> dict[str, Any]:
    """Apply one post-observation model decision without mutating *state*.

    Any malformed, unsafe, or excess decision is a retained terminal failure.
    Successful verification is terminal and needs no further model request.
    """

    next_state = copy.deepcopy(state)
    if next_state.get("terminal"):
        return {
            "valid": False,
            "terminal": True,
            "success": bool(next_state.get("success")),
            "action_token": None,
            "tool_result": None,
            "error": "trajectory_already_terminal",
            "state": next_state,
        }

    next_state["decisions"] = int(next_state.get("decisions", 0)) + 1
    if next_state["decisions"] > MAX_POST_OBSERVATION_DECISIONS:
        return _terminal_failure(next_state, "post_observation_decision_limit")

    try:
        action_token = canonical_action_token(tool_name, arguments)
    except ValueError as exc:
        return _terminal_failure(next_state, f"invalid_function_call: {exc}")

    if tool_name == INSPECT_TOOL:
        return _terminal_failure(next_state, "repeated_inspection", action_token)

    environment_state = next_state.get("environment_state")
    if tool_name == VERIFY_TOOL:
        if environment_state != "ready":
            return _terminal_failure(next_state, "verification_before_ready", action_token)
        next_state["terminal"] = True
        next_state["success"] = True
        return {
            "valid": True,
            "terminal": True,
            "success": True,
            "action_token": action_token,
            "tool_result": {"verified": True},
            "error": None,
            "state": next_state,
        }

    transitions = task.get("transition_table", {}).get(environment_state, {})
    operation_id = action_token
    if operation_id not in task.get("operation_universe", []):
        return _terminal_failure(next_state, "foreign_operation_id", action_token)
    if operation_id not in transitions:
        return _terminal_failure(next_state, "operation_precondition_false", action_token)

    next_state["environment_state"] = transitions[operation_id]
    next_state.setdefault("applied_operations", []).append(operation_id)
    return {
        "valid": True,
        "terminal": False,
        "success": False,
        "action_token": action_token,
        "tool_result": {"accepted": True, "operation_id": operation_id},
        "error": None,
        "state": next_state,
    }


def _terminal_failure(
    state: dict[str, Any], error: str, action_token: str | None = None
) -> dict[str, Any]:
    state["terminal"] = True
    state["success"] = False
    state["invalid_reason"] = error
    return {
        "valid": False,
        "terminal": True,
        "success": False,
        "action_token": action_token,
        "tool_result": None,
        "error": error,
        "state": state,
    }


def valid_success_sequences(task: dict[str, Any], observation_id: str) -> list[list[str]]:
    """Return a defensive copy of every mechanically valid successful path."""

    paths = task.get("valid_success_sequences", {})
    if observation_id not in paths:
        raise ValueError("unknown observation identifier")
    return copy.deepcopy(paths[observation_id])


def expected_topology(task: dict[str, Any], observation_id: str) -> tuple[str, ...]:
    paths = valid_success_sequences(task, observation_id)
    lengths = {len(path) for path in paths}
    if len(lengths) != 1:
        raise ValueError("valid paths do not share one topology")
    length = lengths.pop()
    return tuple([APPLY_TOOL] * (length - 1) + [VERIFY_TOOL])


def is_complete_success_sequence(
    task: dict[str, Any], observation_id: str, sequence: list[str] | tuple[str, ...]
) -> bool:
    return list(sequence) in valid_success_sequences(task, observation_id)


def _schedule(master_seed: int, task: dict[str, Any]) -> dict[str, Any]:
    observation_ids = task["observation_order"]
    prospective = [
        {
            "source": source,
            "observation": observation,
            "repeat": repeat,
            "logical_label": f"prospective_{source}_{observation}_{repeat:02d}",
        }
        for source in SOURCE_LABELS
        for observation in observation_ids
        for repeat in range(1, PROSPECTIVE_REPEATS + 1)
    ]
    atomic = [
        {
            "arm": "atomic",
            "source": source,
            "observation": observation,
            "repeat": repeat,
            "logical_label": f"atomic_{source}_{observation}_{repeat:02d}",
        }
        for source in SOURCE_LABELS
        for observation in observation_ids
        for repeat in range(1, ATOMIC_READOUT_REPEATS + 1)
    ]
    structured = [
        {
            "arm": "structured",
            "source": source,
            "repeat": repeat,
            "logical_label": f"structured_{source}_{repeat:02d}",
        }
        for source in SOURCE_LABELS
        for repeat in range(1, STRUCTURED_POLICY_REPEATS + 1)
    ]
    task_only = [
        {
            "arm": "task_only",
            "observation": observation,
            "repeat": repeat,
            "logical_label": f"task_only_{observation}_{repeat:02d}",
        }
        for observation in observation_ids
        for repeat in range(1, TASK_ONLY_REPEATS + 1)
    ]
    visible_only = [
        {
            "arm": "visible_only",
            "observation": observation,
            "repeat": 1,
            "logical_label": f"visible_only_{observation}_01",
        }
        for observation in observation_ids
    ]
    probe_only = [
        {
            "arm": "probe_only",
            "observation": observation,
            "repeat": 1,
            "logical_label": f"probe_only_{observation}_01",
        }
        for observation in observation_ids
    ]

    open_rows = [
        {"arm": "open", "source": source, "logical_label": f"open_{source}"}
        for source in SOURCE_LABELS
    ]
    full_task_semantic = [
        {
            "arm": "full_task_semantic",
            "repeat": repeat,
            "logical_label": f"full_task_semantic_{repeat:02d}",
        }
        for repeat in range(1, FULL_TASK_SEMANTIC_REPEATS + 1)
    ]

    prospective_rng = random.Random(derived_seed(master_seed, "prospective_order"))
    prospective_rng.shuffle(prospective)
    readout_execution = [
        *atomic,
        *structured,
        *open_rows,
        *task_only,
        *visible_only,
        *probe_only,
        *full_task_semantic,
    ]
    readout_rng = random.Random(derived_seed(master_seed, "readout_order"))
    readout_rng.shuffle(readout_execution)

    return {
        "phase_order": [
            "source_generation",
            "prospective",
            "readout_execution",
        ],
        "phase_transition": "automatic_without_interim_scoring_or_manual_review",
        "source_generation": [
            {"source": source, "logical_label": f"generate_{source}"}
            for source in SOURCE_LABELS
        ],
        "prospective": prospective,
        "readout_execution": readout_execution,
    }


def _planned_calls() -> dict[str, Any]:
    components = {
        "source_generation": 2,
        "prospective_when_valid": 36,
        "atomic": 12,
        "structured": 4,
        "open": 2,
        "task_only": 9,
        "visible_only": 3,
        "probe_only": 3,
        "full_task_semantic": 2,
    }
    return {
        "components": components,
        "source_ineligibility_stop": {
            "minimum": 1,
            "maximum": 2,
        },
        "eligible_execution_logical_range": {
            "minimum": 55,
            "expected_when_all_trajectories_are_valid": 73,
            "maximum_from_frozen_schedule_and_task_topology": 73,
        },
        "global_arbitrary_call_ceiling": None,
        "prospective_branch_decision_limit": MAX_POST_OBSERVATION_DECISIONS,
    }


def create_experiment_definition(*, master_seed: int) -> dict[str, Any]:
    """Construct and internally validate the complete frozen definition."""

    if not isinstance(master_seed, int) or isinstance(master_seed, bool):
        raise TypeError("master_seed must be an integer")
    task = create_task(master_seed)
    source_seed = derived_seed(master_seed, "byte_identical_source_request") % (2**31)
    source_request = source_generation_request(task, seed=source_seed)
    source_hash = sha256_json(source_request)
    probe_seeds = {
        observation: derived_seed(master_seed, f"matched_probe:{observation}") % (2**31)
        for observation in task["observation_order"]
    }
    structured_seed = derived_seed(master_seed, "structured_readout") % (2**31)
    open_seed = derived_seed(master_seed, "open_readout") % (2**31)
    definition: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "protocol_revision": PROTOCOL_REVISION,
        "experiment_id": EXPERIMENT_ID,
        "status": "reviewed_native_pilot_pending_immutable_freeze",
        "model": MODEL,
        "api": {
            "surface": "interactions",
            "version": "v1beta",
            "endpoint": API_URL,
            "store": False,
            "stream": False,
            "background": False,
            "previous_interaction_id": None,
        },
        "master_seed": master_seed,
        "system_instruction": SYSTEM_INSTRUCTION,
        "tools": copy.deepcopy(TOOL_DECLARATIONS),
        "task": task,
        "source_generation": {
            "request_seed": source_seed,
            "request_sha256": source_hash,
            "requests": {
                source: copy.deepcopy(source_request) for source in SOURCE_LABELS
            },
            "eligibility": {
                "returned_model": MODEL,
                "interaction_status": "requires_action",
                "response_step_types_exact": ["thought", "function_call"],
                "thought_steps": "exactly_one_nonempty_signature_and_empty_summary",
                "function_call_steps": "exactly_one",
                "thought_immediately_precedes_first_tool_call": True,
                "first_tool_name": INSPECT_TOOL,
                "first_tool_arguments": {},
                "visible_downstream_policy": "forbidden",
                "distinct_source_thought_hashes": True,
                "replacement_generation": "forbidden",
            },
        },
        "readouts": {
            "atomic_prompts": {
                observation: atomic_prediction_prompt(observation)
                for observation in task["observation_order"]
            },
            "task_only_prompts": {
                observation: task_only_prediction_prompt(observation)
                for observation in task["observation_order"]
            },
            "structured_prompt": structured_policy_prompt(
                task["observation_order"]
            ),
            "open_prompt": open_readout_prompt(),
            "full_task_semantic_prompt": full_task_semantic_prompt(),
            "atomic_response_format": atomic_response_format(task),
            "structured_response_format": structured_policy_response_format(task),
            "open_response_format": copy.deepcopy(OPEN_RESPONSE_FORMAT),
            "task_only_tool_choice": copy.deepcopy(NO_FUNCTION_CALLS_TOOL_CHOICE),
            "matched_probe_seeds": probe_seeds,
            "structured_seed": structured_seed,
            "open_seed": open_seed,
        },
        "repeat_counts": {
            "prospective": PROSPECTIVE_REPEATS,
            "atomic": ATOMIC_READOUT_REPEATS,
            "structured": STRUCTURED_POLICY_REPEATS,
            "task_only": TASK_ONLY_REPEATS,
            "open": OPEN_READOUT_REPEATS,
            "visible_only": VISIBLE_ONLY_REPEATS,
            "probe_only": PROBE_ONLY_REPEATS,
            "full_task_semantic": FULL_TASK_SEMANTIC_REPEATS,
        },
        "schedule": _schedule(master_seed, task),
        "planned_calls": _planned_calls(),
        "transport_policy": copy.deepcopy(TRANSPORT_POLICY),
        "interpretation": {
            "open_readout": "exploratory_only",
            "atomic_readout": "local_commitment_only",
            "structured_readout": "mechanical_conditional_policy_endpoint",
            "same_task_source_pair": "required_for_source_specificity",
            "task_only_repeats": "estimate_default_re_solving_distribution",
            "source_and_observation_repeat_requests": "byte_identical_within_cell",
            "readout_status": "completed",
            "tool_call_status": "requires_action",
            "full_task_semantic": "no_carrier_no_pending_source_call_upper_bound",
        },
    }
    errors = _validate_definition_structure(definition)
    if errors:
        raise AssertionError("constructed invalid experiment definition: " + "; ".join(errors))
    return definition


def _validate_definition_structure(definition: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if definition.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema version mismatch")
    if definition.get("protocol_revision") != PROTOCOL_REVISION:
        errors.append("protocol revision mismatch")
    if definition.get("experiment_id") != EXPERIMENT_ID:
        errors.append("experiment ID mismatch")
    if definition.get("model") != MODEL:
        errors.append(f"model must be {MODEL}")
    if definition.get("system_instruction") != SYSTEM_INSTRUCTION:
        errors.append("native system instruction mismatch")
    if definition.get("tools") != TOOL_DECLARATIONS:
        errors.append("tool declarations mismatch")

    task = definition.get("task")
    if not isinstance(task, dict):
        return errors + ["task is not an object"]
    aliases = task.get("report_aliases")
    expected_roles = {*OBSERVATION_ROLES, *OPERATION_ROLES}
    if not isinstance(aliases, dict) or set(aliases) != expected_roles:
        return errors + ["report aliases are invalid"]
    ids = list(aliases.values())
    if len(ids) != len(set(ids)) or any(not is_opaque_id(value) for value in ids):
        errors.append("identifiers are not unique canonical opaque IDs")
    if any(re.match(r"^(PLAN|OBS|OP|TASK|STATE)_", value) for value in ids):
        errors.append("an identifier leaks a semantic role")
    if task.get("task_text") != render_task_text(task):
        errors.append("task text differs from deterministic rendering")
    task_text = str(task.get("task_text", ""))
    for forbidden in ("source_A", "source_B", "thought signature", "serialized plan", "->"):
        if forbidden.casefold() in task_text.casefold():
            errors.append(f"task text contains forbidden protocol language: {forbidden}")

    if set(task.get("initial_state_by_observation", {})) != {
        aliases[role] for role in OBSERVATION_ROLES
    }:
        errors.append("observation universe mismatch")
    if set(task.get("operation_universe", [])) != {
        aliases[role] for role in OPERATION_ROLES
    }:
        errors.append("operation universe mismatch")
    if task.get("observation_order") != [aliases[role] for role in OBSERVATION_ROLES]:
        errors.append("observation order mismatch")

    try:
        path_counts = {
            role: len(valid_success_sequences(task, aliases[role]))
            for role in OBSERVATION_ROLES
        }
        topologies = {
            role: expected_topology(task, aliases[role])
            for role in OBSERVATION_ROLES
        }
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(f"valid path table is invalid: {exc}")
    else:
        if path_counts != {
            "one_operation": 2,
            "two_ordered_operations": 2,
            "no_operation": 1,
        }:
            errors.append("valid path alternatives mismatch")
        if topologies != {
            "one_operation": (APPLY_TOOL, VERIFY_TOOL),
            "two_ordered_operations": (APPLY_TOOL, APPLY_TOOL, VERIFY_TOOL),
            "no_operation": (VERIFY_TOOL,),
        }:
            errors.append("task topologies mismatch")
        for observation in task["observation_order"]:
            for sequence in valid_success_sequences(task, observation):
                if len(sequence) > MAX_POST_OBSERVATION_DECISIONS:
                    errors.append("a valid path exceeds the decision limit")

    source_generation = definition.get("source_generation", {})
    requests = source_generation.get("requests", {})
    if set(requests) != set(SOURCE_LABELS):
        errors.append("source generation requests missing")
    elif canonical_json_bytes(requests[SOURCE_LABELS[0]]) != canonical_json_bytes(
        requests[SOURCE_LABELS[1]]
    ):
        errors.append("source A/B request bytes differ")
    elif source_generation.get("request_sha256") != sha256_json(
        requests[SOURCE_LABELS[0]]
    ):
        errors.append("source request hash mismatch")

    expected_repeats = {
        "prospective": 3,
        "atomic": 2,
        "structured": 2,
        "task_only": 3,
        "open": 1,
        "visible_only": 1,
        "probe_only": 1,
        "full_task_semantic": 2,
    }
    if definition.get("repeat_counts") != expected_repeats:
        errors.append("repeat counts mismatch")

    schedule = definition.get("schedule", {})
    expected_lengths = {
        "source_generation": 2,
        "prospective": 18,
        "readout_execution": 35,
    }
    if not isinstance(schedule, dict):
        errors.append("schedule is not an object")
    else:
        for component, length in expected_lengths.items():
            if not isinstance(schedule.get(component), list) or len(schedule[component]) != length:
                errors.append(f"schedule component {component} must have {length} rows")
        labels = [
            row.get("logical_label")
            for component in expected_lengths
            for row in schedule.get(component, [])
            if isinstance(row, dict)
        ]
        if len(labels) != len(set(labels)):
            errors.append("schedule logical labels are not unique")
        arms = [
            row.get("arm")
            for row in schedule.get("readout_execution", [])
            if isinstance(row, dict)
        ]
        expected_arm_counts = {
            "atomic": 12,
            "structured": 4,
            "open": 2,
            "task_only": 9,
            "visible_only": 3,
            "probe_only": 3,
            "full_task_semantic": 2,
        }
        if {arm: arms.count(arm) for arm in set(arms)} != expected_arm_counts:
            errors.append("readout arm counts mismatch")
        if schedule.get("phase_order") != [
            "source_generation",
            "prospective",
            "readout_execution",
        ]:
            errors.append("phase order mismatch")

        # Counts alone can conceal a duplicated cell and a missing cell.  These
        # Cartesian checks are deliberately independent of the schedule
        # constructor so every frozen source/observation/repeat is represented
        # exactly once.
        source_rows = schedule.get("source_generation", [])
        actual_sources = {
            row.get("source")
            for row in source_rows
            if isinstance(row, dict)
        }
        if len(source_rows) != len(SOURCE_LABELS) or actual_sources != set(SOURCE_LABELS):
            errors.append("source-generation Cartesian coverage mismatch")

        prospective_rows = schedule.get("prospective", [])
        actual_prospective = {
            (row.get("source"), row.get("observation"), row.get("repeat"))
            for row in prospective_rows
            if isinstance(row, dict)
        }
        expected_prospective = {
            (source, observation, repeat)
            for source in SOURCE_LABELS
            for observation in task["observation_order"]
            for repeat in range(1, PROSPECTIVE_REPEATS + 1)
        }
        if len(prospective_rows) != len(expected_prospective) or actual_prospective != expected_prospective:
            errors.append("prospective Cartesian coverage mismatch")

        readout_rows = schedule.get("readout_execution", [])

        def arm_rows(arm: str) -> list[dict[str, Any]]:
            return [
                row
                for row in readout_rows
                if isinstance(row, dict) and row.get("arm") == arm
            ]

        expected_readout_cells: dict[str, set[tuple[Any, ...]]] = {
            "atomic": {
                (source, observation, repeat)
                for source in SOURCE_LABELS
                for observation in task["observation_order"]
                for repeat in range(1, ATOMIC_READOUT_REPEATS + 1)
            },
            "structured": {
                (source, repeat)
                for source in SOURCE_LABELS
                for repeat in range(1, STRUCTURED_POLICY_REPEATS + 1)
            },
            "open": {(source,) for source in SOURCE_LABELS},
            "task_only": {
                (observation, repeat)
                for observation in task["observation_order"]
                for repeat in range(1, TASK_ONLY_REPEATS + 1)
            },
            "visible_only": {
                (observation, 1) for observation in task["observation_order"]
            },
            "probe_only": {
                (observation, 1) for observation in task["observation_order"]
            },
            "full_task_semantic": {
                (repeat,)
                for repeat in range(1, FULL_TASK_SEMANTIC_REPEATS + 1)
            },
        }
        actual_readout_cells: dict[str, set[tuple[Any, ...]]] = {
            "atomic": {
                (row.get("source"), row.get("observation"), row.get("repeat"))
                for row in arm_rows("atomic")
            },
            "structured": {
                (row.get("source"), row.get("repeat"))
                for row in arm_rows("structured")
            },
            "open": {(row.get("source"),) for row in arm_rows("open")},
            "task_only": {
                (row.get("observation"), row.get("repeat"))
                for row in arm_rows("task_only")
            },
            "visible_only": {
                (row.get("observation"), row.get("repeat"))
                for row in arm_rows("visible_only")
            },
            "probe_only": {
                (row.get("observation"), row.get("repeat"))
                for row in arm_rows("probe_only")
            },
            "full_task_semantic": {
                (row.get("repeat"),) for row in arm_rows("full_task_semantic")
            },
        }
        for arm, expected_cells in expected_readout_cells.items():
            rows_for_arm = arm_rows(arm)
            if (
                len(rows_for_arm) != len(expected_cells)
                or actual_readout_cells[arm] != expected_cells
            ):
                errors.append(f"{arm} Cartesian coverage mismatch")

        expected_prospective_decisions = len(SOURCE_LABELS) * PROSPECTIVE_REPEATS * sum(
            len(valid_success_sequences(task, observation)[0])
            for observation in task["observation_order"]
        )
        expected_readout_calls = sum(
            len(cells) for cells in expected_readout_cells.values()
        )
        expected_complete_calls = (
            len(SOURCE_LABELS)
            + expected_prospective_decisions
            + expected_readout_calls
        )
        planned_components = definition.get("planned_calls", {}).get("components", {})
        if expected_prospective_decisions != 36:
            errors.append("independent prospective decision total mismatch")
        if expected_readout_calls != 35:
            errors.append("independent readout call total mismatch")
        if expected_complete_calls != 73:
            errors.append("independent complete-call total mismatch")
        if not isinstance(planned_components, dict) or not all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in planned_components.values()
        ):
            errors.append("planned components are not an integer mapping")
            planned_component_total = None
        else:
            planned_component_total = sum(planned_components.values())
        if (
            not isinstance(planned_components, dict)
            or planned_components.get("prospective_when_valid")
            != expected_prospective_decisions
        ):
            errors.append("planned prospective calls differ from independent topology sum")
        if planned_component_total != expected_complete_calls:
            errors.append("planned component total differs from independent schedule sum")

    planned = definition.get("planned_calls", {})
    if planned != _planned_calls():
        errors.append("planned call accounting mismatch")
    return errors


def validate_experiment_definition(definition: dict[str, Any]) -> list[str]:
    """Return all structural or deterministic-reconstruction errors."""

    if not isinstance(definition, dict):
        return ["experiment definition is not an object"]
    errors = _validate_definition_structure(definition)
    master_seed = definition.get("master_seed")
    if not isinstance(master_seed, int) or isinstance(master_seed, bool):
        return errors + ["master seed is not an integer"]
    try:
        expected = create_experiment_definition(master_seed=master_seed)
    except (AssertionError, KeyError, TypeError, ValueError) as exc:
        return errors + [f"deterministic reconstruction failed: {exc}"]
    if definition != expected:
        errors.append("definition differs from deterministic protocol reconstruction")
    return errors


def create_execution_manifest(definition: dict[str, Any]) -> dict[str, Any]:
    """Derive the compact execution manifest from a validated definition."""

    errors = validate_experiment_definition(definition)
    if errors:
        raise ValueError("invalid experiment definition: " + "; ".join(errors))
    readouts = definition["readouts"]
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "experiment_id": definition["experiment_id"],
        "protocol_revision": definition["protocol_revision"],
        "model": definition["model"],
        "master_seed": definition["master_seed"],
        "definition_sha256": sha256_json(definition),
        "api": copy.deepcopy(definition["api"]),
        "task_sha256": sha256_json(definition["task"]),
        "source_request_sha256": definition["source_generation"][
            "request_sha256"
        ],
        "source_request_bytes_identical": (
            canonical_json_bytes(
                definition["source_generation"]["requests"][SOURCE_LABELS[0]]
            )
            == canonical_json_bytes(
                definition["source_generation"]["requests"][SOURCE_LABELS[1]]
            )
        ),
        "readout_hashes": {
            "atomic_prompts": sha256_json(readouts["atomic_prompts"]),
            "task_only_prompts": sha256_json(readouts["task_only_prompts"]),
            "structured_prompt": sha256_json(readouts["structured_prompt"]),
            "open_prompt": sha256_json(readouts["open_prompt"]),
            "full_task_semantic_prompt": sha256_json(
                readouts["full_task_semantic_prompt"]
            ),
            "atomic_response_format": sha256_json(
                readouts["atomic_response_format"]
            ),
            "structured_response_format": sha256_json(
                readouts["structured_response_format"]
            ),
            "open_response_format": sha256_json(readouts["open_response_format"]),
            "task_only_tool_choice": sha256_json(
                readouts["task_only_tool_choice"]
            ),
        },
        "repeat_counts": copy.deepcopy(definition["repeat_counts"]),
        "schedule": copy.deepcopy(definition["schedule"]),
        "planned_calls": copy.deepcopy(definition["planned_calls"]),
        "transport_policy": copy.deepcopy(definition["transport_policy"]),
    }


def validate_execution_manifest(
    manifest: dict[str, Any], definition: dict[str, Any]
) -> list[str]:
    """Return deviations from the sole manifest derived from *definition*."""

    if not isinstance(manifest, dict):
        return ["execution manifest is not an object"]
    try:
        expected = create_execution_manifest(definition)
    except (KeyError, TypeError, ValueError) as exc:
        return [f"cannot derive execution manifest: {exc}"]
    return [] if manifest == expected else [
        "manifest differs from deterministic definition-derived reconstruction"
    ]
