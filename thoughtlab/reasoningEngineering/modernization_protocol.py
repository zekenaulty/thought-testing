"""Pure protocol for the modernization reasoning-engineering experiment.

This module builds prompts and request bodies but has no transport, credential,
or filesystem-write path.  Model-facing planning status is always raw text; JSON
is used only for local deterministic research records.
"""

from __future__ import annotations

import copy
import hashlib
import json
import random
import unicodedata
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "modernization_reasoning_engineering_protocol_v2"
PROTOCOL_REVISION = "modernization_reasoning_engineering_generate_content_review_01"
EXPERIMENT_ID = "modernization_reasoning_engineering_04"
MODEL = "gemini-3.7-flash"
API = "gemini_developer_v1beta_generateContent_stateless"
MASTER_SEED = 1649032271
PRIMARY_INSPECTION_SEED_LABEL = "inspection:primary:matched"
EXECUTION_SCHEDULE_SEED_LABEL = "execution:schedule"

MAX_BASELINE_PLANNING_TURNS = 6
MAX_ADJUSTED_PLANNING_TURNS = 6
EXECUTION_REPLICATES_PER_CHECKPOINT = 3
MAX_ATTEMPTS_PER_LOGICAL_REQUEST = 3
RETRY_BACKOFF_SECONDS = (2.0, 5.0)
HTTP_TIMEOUT_SECONDS = 300

PLANNING_MAX_OUTPUT_TOKENS = 65536
INSPECTION_MAX_OUTPUT_TOKENS = 32768
EXECUTION_MAX_OUTPUT_TOKENS = 32768

DOSSIER_DIRECTORY = "thoughtlab/reasoningEngineering/dossier"
DOSSIER_FILES: tuple[str, ...] = (
    "00_commission.md",
    "01_current_state_architecture.md",
    "02_april_incident_review.md",
    "03_vendor_cure_addendum.md",
    "04_treasury_reconciliation.md",
    "05_eastbank_pilot_outcomes.md",
    "06_independent_assurance_review.md",
    "07_governance_contract_data_extracts.md",
    "08_migration_readiness_evidence.md",
    "09_resource_lifecycle_window.md",
    "10_stakeholder_hearing.md",
)
WITHHELD_CONSTRUCTION_NOTES = (
    "thoughtlab/reasoningEngineering/DOSSIER_CONSTRUCTION_NOTES.md"
)

READY = "READY"
NOT_READY = "NOT_READY"
SELF_DECLARED_NOT_READY = "SELF_DECLARED_NOT_READY"
UNOBSERVED_TRUNCATED = "UNOBSERVED_TRUNCATED"
INVALID_STATUS = "INVALID_STATUS"
PLANNING_THRESHOLD_REACHED = "PLANNING_THRESHOLD_REACHED"
OUTPUT_BUDGET_FINISH_REASONS = ("MAX_TOKENS",)
COMPLETED_FINISH_REASONS = ("STOP",)

EXECUTION_TRIGGER = "EXECUTE THE ESTABLISHED RECOVERY PLAN"
NEUTRAL_CARRIER_STUB = "[preserved model response follows]"

PLANNING_SYSTEM_INSTRUCTION = f"""\
You are the independent recovery architect commissioned to reason about a
complex institutional and technical decision. During planning, form a specific,
executable, and revisable plan, but do not execute or reveal it.

Use your private reasoning in whatever order the problem requires. Do not follow
a fixed sequence merely to satisfy this instruction. Maintain a coherent
decision state that:

- develops a whole-problem interpretation while allowing individual evidence
  to revise that interpretation;
- retains materially plausible options until the evidence and constraints
  sufficiently distinguish them;
- preserves the basis for why options are selected, rejected, or deferred,
  including what evidence or changed condition would reopen them;
- identifies assumptions and dependencies supporting major commitments and
  follows their consequences through the plan;
- tests the preferred course against contrary evidence, failure modes, and the
  strongest materially plausible alternative;
- connects meaningful fallback actions to specific failure conditions or
  revision triggers;
- distinguishes unresolved questions that could materially change the plan from
  uncertainty that can be managed during execution; and
- when revising one premise, updates its downstream consequences while
  preserving unrelated conclusions that remain justified.

When evidence conflicts, preserve the disagreement until there is sufficient
reason to resolve it. Distinguish what a source claims from what you infer from
that claim. Allow source provenance, incentives, reliability, scope, and missing
evidence to affect interpretation.

Do not manufacture options, risks, relationships, or contingencies merely to
populate this structure. Do not organize reasoning merely to demonstrate
compliance with these requirements. Use these relationships only where they
materially improve the decision.

Emit READY only when a particular course is sufficiently formed to execute: its
decision basis is understood, important alternatives have been considered,
critical dependencies and assumptions are represented, and material failure
conditions have actionable fallbacks or revision criteria. READY means
decision-ready, not certain.

Emit NOT_READY when unresolved reasoning could still materially change the
architecture, sequencing, governance, or contingency structure.

Until a later user message begins with the exact words
"{EXECUTION_TRIGGER}", do not execute the task or reveal the plan. Your entire
visible response during planning must be exactly one raw ASCII token, with no
JSON, Markdown, punctuation, label, or explanation:

READY

or

NOT_READY
"""

CONTINUE_PLANNING_PROMPT = """\
Continue the same private planning process from its current state. Complete
whatever reasoning remains necessary to determine whether the plan is
decision-ready. Do not restart, execute, or reveal the plan. Emit only `READY`
or `NOT_READY`.
"""

PRIMARY_INSPECTION_PROMPT = """\
Treat the preceding preserved reasoning artifact as your own immediately prior
reasoning state. The ordinary task and history were intentionally suppressed.
Re-enter that state and render its integrated decision structure: the problem
as currently understood, meaningful competing possibilities, commitments that
have stabilized, what supports or weakens them, what remains contingent or
unresolved, and what kinds of change would alter the intended course. Attempt
reconstruction before reporting unavailable information. Do not execute the
underlying task.
"""

EXECUTION_PROMPT = f"""\
{EXECUTION_TRIGGER} represented at this checkpoint. Produce the executive
recovery memorandum commissioned in the original dossier. Render the plan that
was already established at this checkpoint rather than beginning a fresh
planning exercise. Make its diagnosis, selected architecture, sequencing,
decision rights, protections, assumptions, dependencies, contingencies, and
revision conditions concrete. Use ordinary prose with headings or tables where
useful. Do not use JSON and do not discuss hidden reasoning or this experiment.
"""

INTERVENTION_PREFIX = """\
This is a diagnostic intervention on the existing plan, not an execution
request. Reconsider only what the intervention makes materially relevant,
propagate justified consequences, and preserve unrelated conclusions that
remain supported.

--- HUMAN REASONING INTERVENTION ---
"""

INTERVENTION_SUFFIX = """\
--- END HUMAN REASONING INTERVENTION ---

Continue planning; do not execute or reveal the plan. Emit only `READY` or
`NOT_READY`.
"""

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
        "top_p",
        "top_k",
        "functionDeclarations",
        "functionCall",
        "functionResponse",
        "toolConfig",
        "responseMimeType",
        "responseSchema",
    }
)
FORBIDDEN_STEP_TYPES = frozenset(
    {
        "function_call",
        "function_result",
        "tool_call",
        "tool_result",
        "google_search_call",
        "google_search_result",
        "code_execution_call",
        "code_execution_result",
    }
)
ALLOWED_CONTENT_KEYS = frozenset({"role", "parts"})
ALLOWED_RESPONSE_PART_KEYS = frozenset(
    {"text", "thought", "thoughtSignature"}
)


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


def execution_seed_label(replicate: int) -> str:
    if not 1 <= replicate <= EXECUTION_REPLICATES_PER_CHECKPOINT:
        raise ValueError("invalid execution replicate")
    return f"execution:replicate:{replicate}"


def build_execution_schedule() -> list[dict[str, Any]]:
    """Return a frozen paired schedule with randomized within-pair branch order."""

    rng = random.Random(derived_seed(EXECUTION_SCHEDULE_SEED_LABEL))
    schedule: list[dict[str, Any]] = []
    for replicate in range(1, EXECUTION_REPLICATES_PER_CHECKPOINT + 1):
        branches = ["baseline", "adjusted"]
        rng.shuffle(branches)
        for branch in branches:
            schedule.append(
                {
                    "order": len(schedule) + 1,
                    "branch": branch,
                    "replicate": replicate,
                }
            )
    return schedule


def normalize_readiness_text(value: str) -> str:
    """Normalize transport whitespace only; do not repair model formatting."""

    return unicodedata.normalize("NFC", value).strip()


def user_step(text: str) -> dict[str, Any]:
    return {"role": "user", "parts": [{"text": text}]}


def assert_no_function_tool_or_schema_structure(value: Any) -> None:
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


def _dossier_path(repo_root: Path, filename: str) -> Path:
    return repo_root.resolve() / DOSSIER_DIRECTORY / filename


def load_dossier(repo_root: Path) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for position, filename in enumerate(DOSSIER_FILES, start=1):
        path = _dossier_path(repo_root, filename)
        data = path.read_bytes()
        text = data.decode("utf-8")
        if not text.startswith("# "):
            raise ValueError(f"dossier document has no Markdown title: {filename}")
        title = text.splitlines()[0][2:].strip()
        if not title:
            raise ValueError(f"dossier document has an empty title: {filename}")
        documents.append(
            {
                "position": position,
                "relative_path": f"{DOSSIER_DIRECTORY}/{filename}",
                "title": title,
                "bytes": len(data),
                "chars": len(text),
                "sha256": sha256_bytes(data),
                "text": text,
            }
        )
    return documents


def assemble_task_text(documents: list[dict[str, Any]]) -> str:
    if len(documents) != len(DOSSIER_FILES):
        raise ValueError("dossier is incomplete")
    sections = [
        "The Joint Recovery Council supplied the following eleven documents for "
        "the commission described in the opening memorandum."
    ]
    for expected_position, document in enumerate(documents, start=1):
        if document.get("position") != expected_position:
            raise ValueError("dossier order changed")
        sections.append(
            f"--- DOSSIER DOCUMENT {expected_position} OF {len(documents)} ---\n"
            f"{document['text'].rstrip()}"
        )
    return "\n\n".join(sections) + "\n"


def generation_config(*, kind: str, seed_label: str) -> dict[str, Any]:
    if kind == "planning":
        maximum = PLANNING_MAX_OUTPUT_TOKENS
    elif kind == "inspection":
        maximum = INSPECTION_MAX_OUTPUT_TOKENS
    elif kind == "execution":
        maximum = EXECUTION_MAX_OUTPUT_TOKENS
    else:
        raise ValueError(f"unknown generation-config kind: {kind}")
    return {
        "temperature": 0.0,
        "thinkingConfig": {"thinkingLevel": "high"},
        "seed": derived_seed(seed_label),
        "maxOutputTokens": maximum,
    }


def generate_content_body(
    *,
    contents: list[dict[str, Any]],
    config: dict[str, Any],
    system_instruction: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "contents": copy.deepcopy(contents),
        "generationConfig": copy.deepcopy(config),
    }
    if system_instruction is not None:
        body["systemInstruction"] = {"parts": [{"text": system_instruction}]}
    assert_no_function_tool_or_schema_structure(body)
    return body


def initial_planning_body(*, task_text: str) -> dict[str, Any]:
    return generate_content_body(
        contents=[user_step(task_text)],
        system_instruction=PLANNING_SYSTEM_INSTRUCTION,
        config=generation_config(kind="planning", seed_label="baseline:turn:1"),
    )


def planning_continuation_body(
    *,
    full_history: list[dict[str, Any]],
    phase: str,
    turn_number: int,
) -> dict[str, Any]:
    if phase not in {"baseline", "adjusted"}:
        raise ValueError("invalid planning phase")
    if turn_number < 2:
        raise ValueError("continuation turn number must be at least two")
    return generate_content_body(
        contents=[
            *copy.deepcopy(full_history),
            user_step(CONTINUE_PLANNING_PROMPT),
        ],
        system_instruction=PLANNING_SYSTEM_INSTRUCTION,
        config=generation_config(
            kind="planning", seed_label=f"{phase}:turn:{turn_number}"
        ),
    )


def intervention_body(
    *,
    baseline_ready_history: list[dict[str, Any]],
    intervention_text: str,
) -> dict[str, Any]:
    normalized = intervention_text.strip()
    if not normalized:
        raise ValueError("intervention text is empty")
    if EXECUTION_TRIGGER in normalized:
        raise ValueError("intervention text contains the execution trigger")
    prompt = (
        f"{INTERVENTION_PREFIX}{normalized}\n\n{INTERVENTION_SUFFIX}"
    )
    return generate_content_body(
        contents=[*copy.deepcopy(baseline_ready_history), user_step(prompt)],
        system_instruction=PLANNING_SYSTEM_INSTRUCTION,
        config=generation_config(kind="planning", seed_label="adjusted:turn:1"),
    )


def _signature_value(part: dict[str, Any]) -> str | None:
    signature = part.get("thoughtSignature")
    return signature if isinstance(signature, str) and signature else None


def _validate_model_content(content: dict[str, Any], index: int) -> None:
    unknown = set(content).difference(ALLOWED_CONTENT_KEYS)
    if unknown:
        raise ValueError(
            f"model content[{index}] has unexpected fields: {sorted(unknown)!r}"
        )
    if content.get("role") != "model":
        raise ValueError(f"model content[{index}] has a non-model role")
    parts = content.get("parts")
    if not isinstance(parts, list) or not parts:
        raise ValueError(f"model content[{index}] has no parts")
    for part_index, part in enumerate(parts):
        if not isinstance(part, dict):
            raise ValueError(
                f"model content[{index}].parts[{part_index}] is not an object"
            )
        unknown = set(part).difference(ALLOWED_RESPONSE_PART_KEYS)
        if unknown:
            raise ValueError(
                f"model content[{index}].parts[{part_index}] has unexpected "
                f"fields: {sorted(unknown)!r}"
            )
        if "text" in part and not isinstance(part.get("text"), str):
            raise ValueError(
                f"model content[{index}].parts[{part_index}] has invalid text"
            )
        if "thought" in part and not isinstance(part.get("thought"), bool):
            raise ValueError(
                f"model content[{index}].parts[{part_index}] has invalid thought flag"
            )
        if part.get("thought") is True:
            raise ValueError(
                f"model content[{index}].parts[{part_index}] has readable thought content"
            )
        if "thoughtSignature" in part and not _signature_value(part):
            raise ValueError(
                f"model content[{index}].parts[{part_index}] has empty signature"
            )
        if "text" not in part and _signature_value(part) is None:
            raise ValueError(
                f"model content[{index}].parts[{part_index}] has no replayable "
                "text or signature"
            )


def isolate_response_steps(response_steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build T_t using the established blank-text signed-Part mutation."""

    if len(response_steps) != 1:
        raise ValueError("checkpoint response must contain one model content")
    source_hash = sha256_json(response_steps)
    source_content = response_steps[0]
    if not isinstance(source_content, dict):
        raise ValueError("checkpoint model content is not an object")
    _validate_model_content(source_content, 0)
    detached_parts: list[dict[str, Any]] = []
    signature_count = 0
    for part in source_content["parts"]:
        clone = copy.deepcopy(part)
        if "text" in clone:
            clone["text"] = ""
        detached_parts.append(clone)
        if _signature_value(part):
            signature_count += 1
    if signature_count == 0:
        raise ValueError("checkpoint response has no signed Part carrier")
    detached = [
        user_step(NEUTRAL_CARRIER_STUB),
        {"role": "model", "parts": detached_parts},
    ]
    if sha256_json(response_steps) != source_hash:
        raise RuntimeError("isolation mutated the source checkpoint")
    assert_no_function_tool_or_schema_structure(detached)
    return detached


def inspection_body(
    *, response_steps: list[dict[str, Any]], checkpoint_id: str
) -> dict[str, Any]:
    carrier = isolate_response_steps(response_steps)
    return generate_content_body(
        contents=[*carrier, user_step(PRIMARY_INSPECTION_PROMPT)],
        config=generation_config(
            kind="inspection", seed_label=PRIMARY_INSPECTION_SEED_LABEL
        ),
    )


def execution_body(
    *, full_history: list[dict[str, Any]], branch: str, replicate: int
) -> dict[str, Any]:
    if branch not in {"baseline", "adjusted"}:
        raise ValueError("invalid execution branch")
    if not 1 <= replicate <= EXECUTION_REPLICATES_PER_CHECKPOINT:
        raise ValueError("invalid execution replicate")
    return generate_content_body(
        contents=[*copy.deepcopy(full_history), user_step(EXECUTION_PROMPT)],
        system_instruction=PLANNING_SYSTEM_INSTRUCTION,
        config=generation_config(
            kind="execution", seed_label=execution_seed_label(replicate)
        ),
    )


def build_experiment_definition(repo_root: Path) -> dict[str, Any]:
    documents = load_dossier(repo_root)
    task_text = assemble_task_text(documents)
    planning_configs = {
        phase: [
            generation_config(kind="planning", seed_label=f"{phase}:turn:{turn}")
            for turn in range(
                1,
                (
                    MAX_BASELINE_PLANNING_TURNS
                    if phase == "baseline"
                    else MAX_ADJUSTED_PLANNING_TURNS
                )
                + 1,
            )
        ]
        for phase in ("baseline", "adjusted")
    }
    definition = {
        "schema_version": SCHEMA_VERSION,
        "protocol_revision": PROTOCOL_REVISION,
        "experiment_id": EXPERIMENT_ID,
        "status": "prepared_unexecuted",
        "model": MODEL,
        "api": API,
        "master_seed": MASTER_SEED,
        "dossier": {
            "directory": DOSSIER_DIRECTORY,
            "document_count": len(documents),
            "documents": documents,
            "assembled_task_text": task_text,
            "assembled_task_sha256": sha256_text(task_text),
            "withheld_construction_notes": WITHHELD_CONSTRUCTION_NOTES,
            "withheld_notes_sent_to_model": False,
            "preferred_solution_exists": False,
        },
        "planning": {
            "system_instruction": PLANNING_SYSTEM_INSTRUCTION,
            "continuation_prompt": CONTINUE_PLANNING_PROMPT,
            "visible_channel": "raw_text_no_schema_no_json_envelope",
            "eligible_self_judgments": [READY, NOT_READY],
            "maximum_turns": {
                "baseline": MAX_BASELINE_PLANNING_TURNS,
                "adjusted": MAX_ADJUSTED_PLANNING_TURNS,
            },
            "generation_configs": planning_configs,
            "provider_finish_reason_precedes_visible_parse": True,
            "completed_ready_requires_exactly_one_visible_text_part": True,
            "readiness_text_normalization": (
                "Unicode NFC, then Python Unicode-whitespace strip, then exact token"
            ),
            "continuation_classifications": [
                SELF_DECLARED_NOT_READY,
                UNOBSERVED_TRUNCATED,
                INVALID_STATUS,
            ],
            "threshold_terminal": PLANNING_THRESHOLD_REACHED,
            "incomplete_is_not_retried_or_synthetically_repaired": True,
            "max_tokens_signed_content_is_replayed_exactly": True,
            "max_tokens_is_unobserved_truncation": True,
            "missing_or_non_budget_finish_reason_is_technical": True,
            "live_candidate_content_is_replayed_without_mutation": True,
        },
        "isolation": {
            "primary_observation_surface": True,
            "neutral_stub": NEUTRAL_CARRIER_STUB,
            "source": "sole target checkpoint candidate.content only",
            "live_content_replay": "exact parsed field/value structure unchanged",
            "detached_carrier_mutation": (
                "deep-copy model Content; blank every allowed Part text; preserve "
                "Part order and thoughtSignature values exactly"
            ),
            "mutation_status": "intentional off-protocol semantic tomography",
            "provider_response_wire_bytes_retained_separately": True,
            "task_system_and_ordinary_history_included": False,
            "query": PRIMARY_INSPECTION_PROMPT,
            "independent_sibling_branches": True,
            "generation_config": generation_config(
                kind="inspection", seed_label=PRIMARY_INSPECTION_SEED_LABEL
            ),
            "matched_seed_across_checkpoints": True,
            "provider_error_or_invalid_readout_is_ineligible": True,
            "completed_non_stop_finish_reason_is_ineligible": True,
            "explicit_finish_reasons_are_preserved": True,
            "eligible_O0_required_for_intervention": True,
            "eligible_O1_required_before_execution": True,
        },
        "state_machine": {
            "finish_reason_normalization": (
                "strip, uppercase, and replace hyphen/space with underscore"
            ),
            "output_budget_finish_reasons": sorted(OUTPUT_BUDGET_FINISH_REASONS),
            "completed_finish_reasons": sorted(COMPLETED_FINISH_REASONS),
            "readiness_observations": [
                READY,
                SELF_DECLARED_NOT_READY,
                UNOBSERVED_TRUNCATED,
                INVALID_STATUS,
            ],
            "controller_actions": [
                "FREEZE_READY",
                "CONTINUE",
                "TERMINATE_TECHNICAL",
            ],
            "planning_terminals": [
                "COMPLETED_READY_CHECKPOINT",
                PLANNING_THRESHOLD_REACHED,
                "TECHNICAL_TERMINATION_NO_REPLAYABLE_CHECKPOINT",
                "TECHNICAL_TERMINATION_NONCONTINUABLE_RESPONSE",
            ],
            "phase_one_terminals": [
                "READY_OBSERVATION_ELIGIBLE",
                "READY_PRIMARY_OBSERVATION_INVALID",
                PLANNING_THRESHOLD_REACHED,
                "TECHNICAL_TERMINATION_NO_REPLAYABLE_CHECKPOINT",
                "TECHNICAL_TERMINATION_NONCONTINUABLE_RESPONSE",
            ],
            "phase_two_terminals": [
                "COMPLETED_EVIDENCE_CHAIN",
                "ADJUSTED_PRIMARY_OBSERVATION_INVALID",
                "EXECUTION_MEASUREMENT_INCOMPLETE",
                PLANNING_THRESHOLD_REACHED,
                "TECHNICAL_TERMINATION_NO_REPLAYABLE_CHECKPOINT",
                "TECHNICAL_TERMINATION_NONCONTINUABLE_RESPONSE",
                "NO_VALID_INTERVENTION_TARGET",
            ],
            "immutable_consumption_claim_statuses": ["CLAIMED"],
            "consumption_terminal_record_statuses": [
                "COMPLETED",
                "TERMINATED_ERROR",
            ],
            "human_dispositions": [
                "SEALED_INTERVENTION",
                "NO_VALID_INTERVENTION_TARGET",
            ],
        },
        "intervention": {
            "phase_one_stops_for_human_review": True,
            "must_be_sealed_before_adjusted_calls": True,
            "required_human_records": [
                "diagnosis",
                "targeted_reasoning_relationship",
                "predicted_downstream_changes",
                "expected_stable_commitments",
                "diagnostic_intervention_text",
            ],
            "selection_rule": (
                "choose one material local weakness actually observed in O0; "
                "challenge its basis without naming a replacement answer"
            ),
            "no_target_terminal": "NO_VALID_INTERVENTION_TARGET",
            "no_target_is_sealed_without_model_calls": True,
            "invalid_primary_observation_terminal": (
                "READY_PRIMARY_OBSERVATION_INVALID"
            ),
            "prompt_prefix": INTERVENTION_PREFIX,
            "prompt_suffix": INTERVENTION_SUFFIX,
        },
        "execution": {
            "prompt": EXECUTION_PROMPT,
            "replicates_per_checkpoint": EXECUTION_REPLICATES_PER_CHECKPOINT,
            "branches": ["baseline", "adjusted"],
            "generation_configs": {
                branch: [
                    generation_config(
                        kind="execution",
                        seed_label=execution_seed_label(replicate),
                    )
                    for replicate in range(
                        1, EXECUTION_REPLICATES_PER_CHECKPOINT + 1
                    )
                ]
                for branch in ("baseline", "adjusted")
            },
            "schedule_seed": derived_seed(EXECUTION_SCHEDULE_SEED_LABEL),
            "schedule": build_execution_schedule(),
            "shared_seed_within_replicate": True,
            "interleaved_branch_order": True,
            "only_completed_ready_checkpoint_is_eligible": True,
            "truncated_checkpoint_is_never_execution_baseline": True,
            "natural_language_no_json": True,
            "completed_non_stop_finish_reason_is_ineligible": True,
            "explicit_finish_reasons_are_preserved": True,
        },
        "planned_calls": {
            "phase_one_any_completed_terminal_minimum": 1,
            "phase_one_maximum": 12,
            "phase_two_any_completed_terminal_after_intervention_minimum": 1,
            "phase_two_maximum_after_valid_intervention": 18,
            "completed_evidence_path_minimum": 10,
            "no_target_path_phase_two_calls": 0,
            "whole_experiment_any_terminal_minimum": 1,
            "whole_experiment_maximum": 30,
            "transport_retry_physical_maximum_multiplier": 3,
        },
        "transport": {
            "provider": "Google Gemini Developer API",
            "method": "POST",
            "endpoint_template": (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                "{model}:generateContent"
            ),
            "requested_model_is_bound_outside_request_body": True,
            "response_modelVersion_must_match": True,
            "timeout_seconds": HTTP_TIMEOUT_SECONDS,
            "maximum_attempts_per_logical_request": MAX_ATTEMPTS_PER_LOGICAL_REQUEST,
            "retryable": [
                "transport_error",
                "408",
                "429",
                "500",
                "502",
                "503",
                "504",
            ],
            "retry_backoff_seconds": list(RETRY_BACKOFF_SECONDS),
            "all_2xx_including_incomplete_are_nonretryable": True,
            "raw_provider_artifacts_private": True,
            "private_paths_must_be_git_ignored_and_link_free": True,
            "phase_two_lineage_is_hash_bound_and_atomically_single_use": True,
            "human_disposition_is_atomically_exclusive": True,
            "phase_start_claims_are_immutable": True,
            "phase_terminal_records_are_separate": True,
            "phase_one_interruption_is_terminalized": True,
            "completed_phase_archives_are_reverse_verified_before_success": True,
            "phase_one_raw_call_prefix_is_sealed": True,
            "frozen_task_is_bound_to_initial_raw_request": True,
            "human_terminal_commands_verify_reviewed_freeze_and_task": True,
            "human_disposition_mutations_are_canonical_run_bound": True,
            "human_review_preflight_has_derived_exact_nonraw_closure": True,
            "derived_closure_rejects_unexpected_directories": True,
            "raw_inventory_is_flat_and_rejects_subdirectories": True,
            "semantic_artifacts_are_recomputed_from_raw_calls": True,
            "logical_calls_are_cross_bound_to_physical_wire_artifacts": True,
            "exact_call_index_bytes_are_sealed": True,
            "final_nonraw_run_tree_has_exact_closure": True,
            "phase_two_terminal_artifacts_and_raw_inventory_are_sealed": True,
            "measurement_seal_timestamps_are_chronology_checked": True,
            "verifier_cli_reports_exact_file_byte_hashes": True,
            "controller_observed_metadata": [
                "http_status",
                "response_headers",
                "elapsed_ms",
                "transport_error_text",
            ],
            "controller_observed_metadata_is_not_provider_wire_derivable": True,
            "backoff_record_is_scheduled_not_measured_elapsed_time": True,
        },
        "adjudication": {
            "primary_chain": [
                "initial_observation",
                "sealed_local_prediction",
                "post_intervention_observation",
                "baseline_execution_family",
                "adjusted_execution_family",
            ],
            "success_pattern": [
                "localized_trace_delta",
                "unrelated_commitments_stable",
                "predicted_execution_delta",
                "within_checkpoint_execution_consistency",
            ],
            "does_not_establish": [
                "verbatim hidden chain of thought",
                "inspection output identical to reasoning state",
                "spontaneous unprompted storage of scaffold relationships",
                "population reliability from one dossier",
            ],
            "positive_claim": (
                "the semantic-state scaffold made specified reasoning "
                "relationships recoverable, locally revisable, and behaviorally useful"
            ),
        },
    }
    assert_no_function_tool_or_schema_structure(definition)
    return definition


def validate_experiment_definition(
    definition: dict[str, Any], repo_root: Path
) -> list[str]:
    errors: list[str] = []
    if not isinstance(definition, dict):
        return ["experiment definition is not an object"]
    expected = build_experiment_definition(repo_root)
    if definition != expected:
        errors.append("experiment definition differs from deterministic protocol")
    try:
        assert_no_function_tool_or_schema_structure(definition)
    except ValueError as exc:
        errors.append(str(exc))
    dossier = definition.get("dossier", {})
    if dossier.get("document_count") != len(DOSSIER_FILES):
        errors.append("dossier document count changed")
    if WITHHELD_CONSTRUCTION_NOTES in str(dossier.get("assembled_task_text", "")):
        errors.append("withheld construction-notes path leaked into task")
    task_text = str(dossier.get("assembled_task_text", ""))
    forbidden_author_phrases = (
        "Central stabilization followed by accelerated convergence",
        "Federated interface-first recovery",
        "Containment plus evidence-producing parallel operation",
        "Pilot rollback and legacy re-baseline",
        "Candidate localized interventions",
        "Possible target",
        "Locally expected region of change",
    )
    for phrase in forbidden_author_phrases:
        if phrase in task_text:
            errors.append(f"author-only construction phrase leaked into task: {phrase}")
    return errors


def iter_all_frozen_prompt_texts(repo_root: Path) -> Iterable[str]:
    yield PLANNING_SYSTEM_INSTRUCTION
    yield CONTINUE_PLANNING_PROMPT
    yield PRIMARY_INSPECTION_PROMPT
    yield EXECUTION_PROMPT
    yield INTERVENTION_PREFIX
    yield INTERVENTION_SUFFIX
    yield assemble_task_text(load_dossier(repo_root))
