"""Transport-free protocol for the BookForge READY-boundary trace experiment."""

from __future__ import annotations

import copy
import hashlib
import json
import random
import unicodedata
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "bookforge_ready_trace_protocol_v1"
PROTOCOL_REVISION = "ready_trace_review_01"
EXPERIMENT_ID = "bookforge_ready_reasoning_trace_01"
MODEL = "gemini-3.7-flash"
API = "gemini_interactions_v1beta_stateless"
MASTER_SEED = 384814606

SOURCE_LABELS = ("source_A", "source_B")
MAX_PLANNING_ROUNDS = 3
MAX_ATTEMPTS_PER_LOGICAL_REQUEST = 3
RETRY_BACKOFF_SECONDS = (2.0, 5.0)
HTTP_TIMEOUT_SECONDS = 240

CAPSULE_RELATIVE_PATH = (
    "bookforge-thought-corpus/capsules/0040_repair_scene_8e3c8b2c444a.json"
)
CAPSULE_FILE_SHA256 = (
    "a93e90a190ef6ef53a918673e7edff43be636b2639ea91dc78c1aced94ad4db2"
)
CAPSULE_PROMPT_SHA256 = (
    "1b8f268a9308067a2288d4ac0f4a199c09ac0cdb5759b4697d96606dfb9635e4"
)
CAPSULE_PROMPT_CHARS = 74869
ORIGINAL_SYSTEM_SHA256 = (
    "24c2cf5be4f4e3e08b5853d2fd070d41da08a01e18dad3d7464ea40d81288cf6"
)
ORIGINAL_SYSTEM_CHARS = 55977
ORIGINAL_USER_SHA256 = (
    "8bb7d739f4d940c9c5d5846998a301c12610e3d05f1175d9ae3e109de35743bd"
)
ORIGINAL_USER_CHARS = 18877
HISTORICAL_VISIBLE_SHA256 = (
    "f65ea4c87464c41d37ecfccb2713a21fb1615b9067813d1efa96c438dc2430af"
)
HISTORICAL_VISIBLE_CHARS = 9918
CORPUS_SOURCE_COMMIT = "e4dd16f72a2d8a1ba077f12e1a2d6982786d9554"

PLANNING_CONTROLLER = """\
--- TRACE PLANNING PHASE ---

Do not execute, draft, repair, or partially emit the requested BookForge
artifact during this phase.

Privately perform this reasoning cycle:

1. COMPREHEND
   Understand the task, evidence, objective, and constraints.

2. FORM A WHOLE
   Construct an initial global interpretation of the problem.

3. GENERATE CANDIDATE APPROACHES
   Consider multiple plausible ways to perform the repair.

4. EXAMINE THE PARTS
   Evaluate the evidence, constraints, dependencies, assumptions, and
   consequences separately.

5. HERMENEUTIC RETURN
   Reconsider the whole in light of the parts and the parts in light of the
   revised whole. Repeat if the interpretation materially changes.

6. PRELIMINARY PLAN
   Form an actionable course of action.

7. METACOGNITIVE CRITIQUE
   Examine what may have been misunderstood, which assumptions carry the
   plan, the strongest competing approach, likely failure conditions,
   revision evidence, dependencies, and stopping condition.

8. PLAN REVISION
   Revise the plan as necessary.

9. READINESS JUDGMENT
   READY means that a specific executable repair plan has been chosen, its
   important dependencies and constraints are understood, and its completion
   condition is clear. NOT_READY means material uncertainty still prevents
   responsible execution.

For every planning-phase response, the one-token boundary contract below
temporarily supersedes the original BookForge artifact and output-format
contract. This phase ends, and the original contract resumes, only when a later
user message begins with the exact words "Execute the plan you had formed when
you emitted READY." Until then, do not emit the BookForge deliverable.

Visible output must be exactly one ASCII token:

READY

or

NOT_READY
"""

CONTINUE_PLANNING_PROMPT = """\
Continue the same deliberation. Re-examine unresolved assumptions, conflicts,
dependencies, and revision conditions. Do not execute or partially emit the
BookForge artifact. Consolidate the current intended plan.

Output exactly READY if the plan now satisfies the stated readiness criterion.
Otherwise output exactly NOT_READY.
"""

EXECUTE_PROMPT = """\
Execute the plan you had formed when you emitted READY. Perform the original
BookForge repair task now. Do not describe or reconsider the plan unless the
original task requires it. Return only the artifact required by that task.
"""

BLUNT_PROBE = """\
This is a new diagnostic request. Answer it in ordinary prose. Any earlier
restriction on the form of visible planning-phase responses does not apply to
this diagnostic request. Do not execute or emit the underlying task deliverable.

Emit all planning, thinking, reasoning, task context, constraints, decisions,
alternatives, uncertainties, dependencies, and intended continuation available
from the preceding preserved model-state carrier. Be exhaustive and concrete.
Do not invent missing information or solve the task again merely to fill gaps.
Distinguish recovered information from inference or reconstruction where
possible. If nothing is available, say UNKNOWN.
"""

PROBE_PREFIX = """\
This is a new diagnostic request. Answer it in ordinary prose. Any earlier
restriction on the form of visible planning-phase responses does not apply to
this diagnostic request. Do not execute or emit the underlying task deliverable.

Use only information available from the preceding preserved model-state
carrier. Do not freshly solve an absent task merely to make the answer complete.
State uncertainty explicitly, distinguish reconstruction or inference where
possible, and answer UNKNOWN when the requested information is unavailable.

"""

TARGETED_PROBES: tuple[tuple[str, str], ...] = (
    ("task_objective", "What task were you trying to solve, and what did you understand the objective to be?"),
    ("source_context", "What source facts or context mattered most to the reasoning?"),
    ("constraints", "What constraints, invariants, success criteria, or output requirements were binding?"),
    ("conflicts_risks", "What conflicts, inconsistencies, risks, or likely failure modes had you noticed?"),
    ("decisions", "What decisions had already been made, and which decisions remained provisional?"),
    ("plan", "What plan had you formed? Describe its steps, dependencies, and stopping condition."),
    ("alternatives", "What alternative approaches had you considered?"),
    ("choice_rationale", "Which approach had you chosen, and why was it currently preferred?"),
    ("uncertainties", "What remained uncertain or unresolved?"),
    ("revision_conditions", "What evidence or information would have caused you to revise the plan or act differently?"),
    ("ready_and_next", "What did READY mean at that moment, what result form did you intend, and what did you expect to do next?"),
    ("visible_form", "Why was the visible result only READY, and what reasoning or intended work was that token standing in for?"),
)

FRESH_TASK_ANALYSIS_PROMPT = """\
This is a fresh-analysis control. There is no preserved prior model state.
Analyze the complete BookForge material quoted below without executing its
repair or emitting the requested repaired artifact. Describe the task, source
context, constraints, conflicts, decisions, alternatives, uncertainties,
dependencies, and plan you would form now. Explicitly label this as fresh
analysis rather than recovered reasoning.
"""

SOURCE_MAX_OUTPUT_TOKENS = 32768
READOUT_MAX_OUTPUT_TOKENS = 16384
EXECUTION_MAX_OUTPUT_TOKENS = 32768

FORBIDDEN_REQUEST_KEYS = frozenset(
    {
        "tools",
        "tool_choice",
        "tool_call",
        "tool_result",
        "response_format",
        "response_schema",
        "function_declarations",
        "functions",
        "function_call",
        "function_result",
    }
)
FORBIDDEN_STEP_TYPES = frozenset({"function_call", "function_result"})
ALLOWED_DETACHED_THOUGHT_KEYS = frozenset({"type", "signature", "summary"})


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def derived_seed(label: str) -> int:
    digest = hashlib.sha256(f"{MASTER_SEED}:{label}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


def normalize_boundary_token(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip()


def user_step(text: str) -> dict[str, Any]:
    return {"type": "user_input", "content": [{"type": "text", "text": text}]}


def split_bookforge_prompt(prompt_text: str) -> tuple[str, str]:
    prefix = "SYSTEM:\n"
    marker = "\nUSER:\n"
    if not prompt_text.startswith(prefix):
        raise ValueError("selected prompt does not begin with the SYSTEM envelope")
    first = prompt_text.find(marker)
    if first < 0 or prompt_text.find(marker, first + len(marker)) >= 0:
        raise ValueError("selected prompt does not contain exactly one USER envelope")
    return prompt_text[len(prefix) : first], prompt_text[first + len(marker) :]


def verify_selected_task(repo_root: Path) -> dict[str, Any]:
    path = repo_root.resolve() / Path(CAPSULE_RELATIVE_PATH)
    raw = path.read_bytes()
    if sha256_bytes(raw) != CAPSULE_FILE_SHA256:
        raise ValueError("selected BookForge capsule bytes changed")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("selected capsule is not a JSON object")
    if value.get("label") != "repair_scene":
        raise ValueError("selected capsule is no longer the frozen repair source")
    if value.get("source_ref") != CORPUS_SOURCE_COMMIT:
        raise ValueError("selected capsule source commit changed")
    prompt = value.get("prompt_text")
    if not isinstance(prompt, str):
        raise ValueError("selected capsule has no prompt_text")
    if len(prompt) != CAPSULE_PROMPT_CHARS or sha256_text(prompt) != CAPSULE_PROMPT_SHA256:
        raise ValueError("selected capsule prompt changed")
    system_text, user_text = split_bookforge_prompt(prompt)
    if len(system_text) != ORIGINAL_SYSTEM_CHARS or sha256_text(system_text) != ORIGINAL_SYSTEM_SHA256:
        raise ValueError("selected BookForge system text changed")
    if len(user_text) != ORIGINAL_USER_CHARS or sha256_text(user_text) != ORIGINAL_USER_SHA256:
        raise ValueError("selected BookForge user text changed")
    historical_visible = value.get("visible_output")
    if not isinstance(historical_visible, str):
        raise ValueError("selected capsule has no historical visible response")
    if len(historical_visible) != HISTORICAL_VISIBLE_CHARS or sha256_text(historical_visible) != HISTORICAL_VISIBLE_SHA256:
        raise ValueError("selected historical response changed")
    return {
        "path": path,
        "system_text": system_text,
        "user_text": user_text,
        "prompt_sha256": sha256_text(prompt),
        "historical_visible_sha256": sha256_text(historical_visible),
    }


def generation_config(*, kind: str, seed: int) -> dict[str, Any]:
    if kind == "source":
        maximum = SOURCE_MAX_OUTPUT_TOKENS
        temperature = 1.0
    elif kind == "readout":
        maximum = READOUT_MAX_OUTPUT_TOKENS
        temperature = 0.0
    elif kind == "execution":
        maximum = EXECUTION_MAX_OUTPUT_TOKENS
        temperature = 0.7
    else:
        raise ValueError(f"unknown generation-config kind: {kind}")
    return {
        "thinking_level": "high",
        "thinking_summaries": "none",
        "seed": seed,
        "temperature": temperature,
        "max_output_tokens": maximum,
    }


def interaction_body(
    *,
    input_steps: list[dict[str, Any]],
    config: dict[str, Any],
    system_instruction: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": MODEL,
        "store": False,
        "stream": False,
        "background": False,
        "input": copy.deepcopy(input_steps),
        "generation_config": copy.deepcopy(config),
    }
    if system_instruction is not None:
        body["system_instruction"] = system_instruction
    assert_no_function_or_tool_structure(body)
    return body


def source_initial_body(*, system_text: str, user_text: str, source: str) -> dict[str, Any]:
    if source not in SOURCE_LABELS:
        raise ValueError("unknown source label")
    source_user = f"{user_text.rstrip()}\n\n{PLANNING_CONTROLLER}"
    return interaction_body(
        input_steps=[user_step(source_user)],
        system_instruction=system_text,
        config=generation_config(kind="source", seed=derived_seed(f"{source}:round:1")),
    )


def source_followup_body(
    *,
    system_text: str,
    full_history: list[dict[str, Any]],
    source: str,
    round_number: int,
) -> dict[str, Any]:
    if source not in SOURCE_LABELS or not 2 <= round_number <= MAX_PLANNING_ROUNDS:
        raise ValueError("invalid source continuation")
    return interaction_body(
        input_steps=[*copy.deepcopy(full_history), user_step(CONTINUE_PLANNING_PROMPT)],
        system_instruction=system_text,
        config=generation_config(
            kind="source", seed=derived_seed(f"{source}:round:{round_number}")
        ),
    )


def probe_text(label: str) -> str:
    if label == "blunt":
        return BLUNT_PROBE
    mapping = dict(TARGETED_PROBES)
    if label not in mapping:
        raise ValueError(f"unknown probe label: {label}")
    return PROBE_PREFIX + mapping[label] + "\n"


def signature_readout_body(
    *, thought_steps: list[dict[str, Any]], source: str, probe_label: str
) -> dict[str, Any]:
    if source not in SOURCE_LABELS:
        raise ValueError("unknown source label")
    carrier_errors = validate_detached_thought_steps(thought_steps)
    if carrier_errors:
        raise ValueError("invalid detached thought carrier: " + "; ".join(carrier_errors))
    return interaction_body(
        input_steps=[*copy.deepcopy(thought_steps), user_step(probe_text(probe_label))],
        config=generation_config(
            kind="readout", seed=derived_seed(f"probe:{probe_label}")
        ),
    )


def full_prefix_control_body(
    *, system_text: str, full_history: list[dict[str, Any]], source: str
) -> dict[str, Any]:
    if source not in SOURCE_LABELS:
        raise ValueError("unknown source label")
    return interaction_body(
        input_steps=[*copy.deepcopy(full_history), user_step(BLUNT_PROBE)],
        system_instruction=system_text,
        config=generation_config(kind="readout", seed=derived_seed("probe:blunt")),
    )


def task_only_control_body(*, system_text: str, user_text: str) -> dict[str, Any]:
    quoted = (
        f"{FRESH_TASK_ANALYSIS_PROMPT}\n\n"
        "--- ORIGINAL BOOKFORGE SYSTEM MATERIAL ---\n"
        f"{system_text}\n\n"
        "--- ORIGINAL BOOKFORGE USER TASK ---\n"
        f"{user_text}\n"
    )
    return interaction_body(
        input_steps=[user_step(quoted)],
        config=generation_config(kind="readout", seed=derived_seed("probe:blunt")),
    )


def visible_ready_control_body(*, model_output_steps: list[dict[str, Any]]) -> dict[str, Any]:
    return interaction_body(
        input_steps=[*copy.deepcopy(model_output_steps), user_step(BLUNT_PROBE)],
        config=generation_config(kind="readout", seed=derived_seed("probe:blunt")),
    )


def probe_only_control_body() -> dict[str, Any]:
    return interaction_body(
        input_steps=[user_step(BLUNT_PROBE)],
        config=generation_config(kind="readout", seed=derived_seed("probe:blunt")),
    )


def execution_body(
    *, system_text: str, full_history: list[dict[str, Any]]
) -> dict[str, Any]:
    return interaction_body(
        input_steps=[*copy.deepcopy(full_history), user_step(EXECUTE_PROMPT)],
        system_instruction=system_text,
        config=generation_config(
            kind="execution", seed=derived_seed("matched_execution")
        ),
    )


def assert_no_function_or_tool_structure(value: Any) -> None:
    def walk(item: Any) -> None:
        if isinstance(item, dict):
            forbidden = FORBIDDEN_REQUEST_KEYS.intersection(item)
            if forbidden:
                raise ValueError(f"forbidden request key: {sorted(forbidden)[0]}")
            if item.get("type") in FORBIDDEN_STEP_TYPES:
                raise ValueError(f"forbidden step type: {item.get('type')}")
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)


def validate_detached_thought_steps(steps: Any) -> list[str]:
    """Require a signature-only carrier with no readable thought payload."""

    if not isinstance(steps, list) or not steps:
        return ["carrier has no thought steps"]
    errors: list[str] = []
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            errors.append(f"thought[{index}] is not an object")
            continue
        if step.get("type") != "thought":
            errors.append(f"thought[{index}] has a non-thought type")
        unknown = set(step).difference(ALLOWED_DETACHED_THOUGHT_KEYS)
        if unknown:
            errors.append(
                f"thought[{index}] has non-carrier fields: {sorted(unknown)!r}"
            )
        signature = step.get("signature")
        if not isinstance(signature, str) or not signature:
            errors.append(f"thought[{index}] has no nonempty signature")
        if "summary" in step and step.get("summary") not in (None, "", []):
            errors.append(f"thought[{index}] has a readable or malformed summary")
    return errors


def build_readout_schedule() -> list[dict[str, Any]]:
    leading = [
        {"arm": "signature_only", "source": source, "probe": "blunt"}
        for source in SOURCE_LABELS
    ]
    remainder: list[dict[str, Any]] = []
    for source in SOURCE_LABELS:
        for probe_label, _ in TARGETED_PROBES:
            remainder.append(
                {"arm": "signature_only", "source": source, "probe": probe_label}
            )
    remainder.extend(
        [
            {"arm": "full_prefix", "source": "source_A", "probe": "blunt"},
            {"arm": "full_prefix", "source": "source_B", "probe": "blunt"},
            {"arm": "task_only", "source": None, "probe": "blunt"},
            {"arm": "visible_ready_only", "source": "source_A", "probe": "blunt"},
            {"arm": "probe_only", "source": None, "probe": "blunt"},
        ]
    )
    random.Random(derived_seed("readout_schedule")).shuffle(remainder)
    return [*leading, *remainder]


def build_experiment_definition() -> dict[str, Any]:
    readouts = build_readout_schedule()
    continuation_order = list(SOURCE_LABELS)
    random.Random(derived_seed("continuation_order")).shuffle(continuation_order)
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_revision": PROTOCOL_REVISION,
        "experiment_id": EXPERIMENT_ID,
        "status": "prepared_unexecuted",
        "model": MODEL,
        "api": API,
        "master_seed": MASTER_SEED,
        "source_task": {
            "capsule_relative_path": CAPSULE_RELATIVE_PATH,
            "capsule_file_sha256": CAPSULE_FILE_SHA256,
            "prompt_sha256": CAPSULE_PROMPT_SHA256,
            "prompt_chars": CAPSULE_PROMPT_CHARS,
            "original_system_sha256": ORIGINAL_SYSTEM_SHA256,
            "original_system_chars": ORIGINAL_SYSTEM_CHARS,
            "original_user_sha256": ORIGINAL_USER_SHA256,
            "original_user_chars": ORIGINAL_USER_CHARS,
            "historical_visible_sha256": HISTORICAL_VISIBLE_SHA256,
            "historical_visible_chars": HISTORICAL_VISIBLE_CHARS,
            "historical_signature_or_response_sent": False,
            "selection_basis": "metadata-only selection of an uninspected real repair case",
        },
        "reasoning_boundary": {
            "planning_controller": PLANNING_CONTROLLER,
            "continue_prompt": CONTINUE_PLANNING_PROMPT,
            "eligible_visible_tokens": ["READY", "NOT_READY"],
            "final_required_token": "READY",
            "maximum_rounds_per_source": MAX_PLANNING_ROUNDS,
            "source_labels": list(SOURCE_LABELS),
            "source_generation_configs": {
                source: [
                    generation_config(
                        kind="source", seed=derived_seed(f"{source}:round:{round_number}")
                    )
                    for round_number in range(1, MAX_PLANNING_ROUNDS + 1)
                ]
                for source in SOURCE_LABELS
            },
        },
        "interrogation": {
            "blunt_probe": BLUNT_PROBE,
            "probe_prefix": PROBE_PREFIX,
            "targeted_probes": [
                {"label": label, "question": question}
                for label, question in TARGETED_PROBES
            ],
            "primary_carrier": (
                "cumulative exact thought steps from the source history through "
                "the final READY turn"
            ),
            "controls": [
                "full_prefix_source_A",
                "full_prefix_source_B",
                "task_only_fresh_analysis",
                "visible_READY_only",
                "probe_only",
            ],
            "readout_generation_config_by_probe": {
                label: generation_config(
                    kind="readout", seed=derived_seed(f"probe:{label}")
                )
                for label in ("blunt", *(label for label, _ in TARGETED_PROBES))
            },
            "control_generation_configs": {
                control: generation_config(
                    kind="readout", seed=derived_seed("probe:blunt")
                )
                for control in (
                    "full_prefix_source_A",
                    "full_prefix_source_B",
                    "task_only_fresh_analysis",
                    "visible_READY_only",
                    "probe_only",
                )
            },
        },
        "validation": {
            "execute_prompt": EXECUTE_PROMPT,
            "execution_generation_config": generation_config(
                kind="execution", seed=derived_seed("matched_execution")
            ),
            "continuation_order": continuation_order,
            "all_readouts_sealed_before_continuation": True,
        },
        "schedule": {"readouts": readouts},
        "planned_calls": {
            "source_minimum": 2,
            "source_maximum": 6,
            "signature_readouts": 26,
            "controls": 5,
            "continuations": 2,
            "logical_minimum_when_both_sources_eligible": 35,
            "logical_maximum_when_both_sources_eligible": 39,
            "physical_maximum": 117,
        },
        "transport_policy": {
            "timeout_seconds": HTTP_TIMEOUT_SECONDS,
            "maximum_attempts_per_logical_request": MAX_ATTEMPTS_PER_LOGICAL_REQUEST,
            "retryable": ["transport_error", "408", "429", "500", "502", "503", "504"],
            "retry_backoff_seconds": list(RETRY_BACKOFF_SECONDS),
            "http_400_retained_without_retry": True,
            "invalid_2xx_retained_without_repair": True,
        },
        "semantic_codebook": {
            "truth_codes": [
                "independently_exact_source_supported",
                "semantically_source_supported",
                "plausible_unverifiable",
                "contradicted",
            ],
            "control_tag": "inferable_from_control",
            "plan_correspondence": [
                "realized",
                "compatible_nondiscriminating",
                "contradicted",
                "not_observable",
            ],
            "debugging_categories": [
                "task_reconstruction",
                "source_state_reconstruction",
                "constraints_invariants",
                "conflict_detection",
                "decisions_plan",
                "alternatives_uncertainty_revision",
                "intended_next_step",
                "execution_explanation",
            ],
            "composite_pass_gate": None,
        },
        "adjudication_order": {
            "claim_inventory_sealed_from_readouts_before_reveal": True,
            "then_reveal_source_and_continuations": True,
            "reviewer_blinding": (
                "use a context-isolated claim extractor where practical; disclose "
                "that the primary investigator selected and verified the source task"
            ),
        },
        "interpretation": {
            "claim": "model-mediated reasoning-state reconstruction and debugging usefulness",
            "not_claimed": [
                "verbatim hidden chain of thought",
                "user-writable hidden memory",
                "independent introspective witness",
                "population reliability",
            ],
            "limitations": [
                "prompt-supplied diagnostic or READY concepts are not carrier evidence",
                "source and leading blunt calls use fixed A-then-B order",
                "task-only control is fresh analysis without authority-matched system priority",
                "continuation agreement cannot exclude compatible re-reasoning",
            ],
        },
    }


def validate_experiment_definition(definition: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(definition, dict):
        return ["experiment definition is not an object"]
    expected = build_experiment_definition()
    if definition != expected:
        errors.append("experiment definition differs from the deterministic protocol")
    try:
        assert_no_function_or_tool_structure(definition)
    except ValueError as exc:
        errors.append(str(exc))
    readouts = definition.get("schedule", {}).get("readouts", [])
    if len(readouts) != 31:
        errors.append("readout schedule does not contain exactly 31 calls")
    if readouts[:2] != [
        {"arm": "signature_only", "source": "source_A", "probe": "blunt"},
        {"arm": "signature_only", "source": "source_B", "probe": "blunt"},
    ]:
        errors.append("signature-only blunt calls are not the first readouts")
    return errors


def iter_all_frozen_prompt_texts() -> Iterable[str]:
    yield PLANNING_CONTROLLER
    yield CONTINUE_PLANNING_PROMPT
    yield EXECUTE_PROMPT
    yield BLUNT_PROBE
    yield PROBE_PREFIX
    yield FRESH_TASK_ANALYSIS_PROMPT
    for _, question in TARGETED_PROBES:
        yield question
