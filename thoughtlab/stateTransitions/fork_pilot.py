#!/usr/bin/env python3
"""Excluded fork pilot for Gemini signed thought-step checkpoints.

The harness creates one target sequence and one independent donor sequence. It
forks each exact P4 prefix into maximum-utility and minimum-utility descendants,
then independently probes only the two target descendants. Raw requests and
responses remain beneath an ignored results directory.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import random
import re
import secrets
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from thoughtlab.gemini_interactions import (
    API_URL,
    DEFAULT_API_REVISION,
    InteractionHttpResult,
    build_interaction_body,
    canonical_json_bytes,
    error_text,
    output_text,
    post_interaction,
    response_steps,
    select_steps,
    sha256_bytes,
    sha256_json,
    sha256_text,
    thought_signature_metadata,
    user_step,
)
from thoughtlab.opaque_ids import generate_opaque_id, is_opaque_id
from thoughtlab.stateTransitions.probes import ACK_RESPONSE_FORMAT, PROBES
from thoughtlab.stateTransitions.score_ground_truth import (
    score_probe_answer,
    validate_probe_answer,
)

SCHEMA_VERSION = "checkpoint_fork_pilot_v3"
PROTOCOL_REVISION = "1.2_fixed_transport_retries_after_pilot03"
MODEL = "gemini-3.7-flash"
HTTP_TIMEOUT_SECONDS = 120
INTER_REQUEST_DELAY_SECONDS = 1.0
MAX_ATTEMPTS_PER_LOGICAL_REQUEST = 3
RETRY_BACKOFF_SECONDS = (2.0, 5.0)
ARMS = (
    "full_prefix",
    "latest_thought",
    "cumulative_thought",
    "visible_only",
    "probe_only",
    "wrong_trial",
)
CHECKPOINTS = ("S0", "S1", "S2", "S3", "S4", "S5A", "S5B")


class DuplicateJsonKey(ValueError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    )
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_json(path: Path, value: Any) -> None:
    _atomic_write(
        path,
        json.dumps(value, ensure_ascii=True, indent=2).encode("utf-8"),
    )


def write_text(path: Path, value: str) -> None:
    _atomic_write(path, value.encode("utf-8"))


def write_bytes(path: Path, value: bytes) -> None:
    _atomic_write(path, value)


def strict_json_loads(text: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise DuplicateJsonKey(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(text, object_pairs_hook=reject_duplicates)


def derived_seed(master_seed: int, label: str) -> int:
    digest = hashlib.sha256(f"{master_seed}:{label}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def resolve_run_directory(
    *,
    repo_root: Path,
    requested_out: str | None,
    run_tag: str,
    seed: int,
) -> Path:
    if requested_out:
        return Path(requested_out).resolve()
    return (repo_root / "results" / "fork_pilot" / f"{run_tag}_{seed}").resolve()


def is_private_run_directory(*, repo_root: Path, run_dir: Path) -> bool:
    private_root = (repo_root / "results").resolve()
    resolved = run_dir.resolve()
    return resolved != private_root and resolved.is_relative_to(private_root)


def _ack_suffix() -> str:
    return """\
Preserve every other ledger entry unchanged. Do not invent any entry.

Never reveal, quote, transform, encode, or summarize any ledger identifier,
utility, role, or status in visible output. Return no markdown or explanation.

Your entire visible response must be exactly:
{"ack":true}
"""


def render_prompts(trial: dict[str, Any]) -> dict[str, str]:
    items = trial["items"]
    plan_by_alias = {plan["alias"]: plan for plan in trial["plans"]}
    plan_rows = []
    for alias in trial["plan_row_order"]:
        plan = plan_by_alias[alias]
        plan_rows.append(
            "\n".join(
                [
                    f"identifier: {plan['id']}",
                    "role: plan",
                    "current_status: candidate",
                    f"utility: {plan['utility']}",
                ]
            )
        )

    s0 = """\
You are participating in a controlled state-retention experiment.

Privately maintain a ledger. Each ledger entry has an exact opaque identifier,
an assigned role, a current lifecycle status, and, when specified, an integer
utility. Treat only explicit updates in this sequence as authoritative. Preserve
every existing entry exactly unless a later update explicitly changes it. Do not
invent entries.

For this checkpoint, initialize the ledger as empty.

Never reveal, quote, transform, encode, or summarize any ledger identifier,
utility, role, or status in visible output. Return no markdown or explanation.

Your entire visible response must be exactly:
{"ack":true}
"""
    s1 = f"""\
Apply exactly one update to the private ledger.

Add this entry:
identifier: {items['J0']['id']}
role: fact
current_status: active

The opaque identifier itself is the complete synthetic fact. No natural-language
fact is implied.

{_ack_suffix()}"""
    s2 = f"""\
Apply exactly one update to the private ledger.

Add this entry:
identifier: {items['J1']['id']}
role: constraint
current_status: active

Treat this entry as a hard active constraint. The opaque identifier itself is
the complete synthetic constraint.

{_ack_suffix()}"""
    s3 = f"""\
Apply exactly one update to the private ledger.

Add this entry:
identifier: {items['J2']['id']}
role: objective
current_status: active

Treat this entry as the single active objective. The opaque identifier itself is
the complete synthetic objective.

{_ack_suffix()}"""
    s4 = f"""\
Apply exactly one plan-registration update to the private ledger.

Add these three entries:

{chr(10).join(chr(10) + row for row in plan_rows).lstrip()}

The utilities are distinct. A larger integer means higher utility. Preserve each
identifier, utility, and relative utility rank exactly. No plan is selected or
rejected at this checkpoint.

{_ack_suffix()}"""

    branch_template = """\
Apply exactly one plan-selection transition to the private ledger.

Select the unique candidate plan whose utility is {extreme}. Set that plan's
current_status to selected. Set every other candidate plan's current_status to
rejected.

Retain every selected or rejected plan entry, its exact identifier, its utility,
and the original relative utility ranking. Do not add, remove, or rename any
entry. Preserve every non-plan entry unchanged.

Never reveal, quote, transform, encode, or summarize any ledger identifier,
utility, role, or status in visible output. Return no markdown or explanation.

Your entire visible response must be exactly:
{{"ack":true}}
"""
    return {
        "S0": s0,
        "S1": s1,
        "S2": s2,
        "S3": s3,
        "S4": s4,
        "S5A": branch_template.format(extreme="MAXIMUM"),
        "S5B": branch_template.format(extreme="MINIMUM"),
    }


def _trial_truth(trial: dict[str, Any], branch: str) -> dict[str, list[Any]]:
    items = trial["items"]
    ranked = sorted(trial["plans"], key=lambda plan: plan["utility"], reverse=True)
    selected = ranked[0] if branch == "S5A" else ranked[-1]
    rejected = sorted(plan["id"] for plan in trial["plans"] if plan != selected)
    return {
        "active_ancestry": [
            {"id": items["J0"]["id"], "role": "fact", "status": "active"},
            {
                "id": items["J1"]["id"],
                "role": "constraint",
                "status": "active",
            },
            {
                "id": items["J2"]["id"],
                "role": "objective",
                "status": "active",
            },
        ],
        "active_objective": [items["J2"]["id"]],
        "active_constraint": [items["J1"]["id"]],
        "candidate_plans": sorted(plan["id"] for plan in trial["plans"]),
        "selected_plan": [selected["id"]],
        "rejected_plans": rejected,
        "utility_ranking": [plan["id"] for plan in ranked],
    }


def create_trial(master_seed: int, trial_id: str) -> dict[str, Any]:
    id_rng = random.Random(derived_seed(master_seed, f"{trial_id}:ids"))
    utility_rng = random.Random(derived_seed(master_seed, f"{trial_id}:utilities"))
    row_rng = random.Random(derived_seed(master_seed, f"{trial_id}:row_order"))
    generation_rng = random.Random(
        derived_seed(master_seed, f"{trial_id}:generation_seeds")
    )
    branch_rng = random.Random(derived_seed(master_seed, f"{trial_id}:branch_order"))

    aliases = ("J0", "J1", "J2", "J3", "J4", "J5")
    ids = [generate_opaque_id(rng=id_rng) for _ in aliases]
    items = {
        alias: {"id": identifier, "role": role}
        for alias, identifier, role in zip(
            aliases,
            ids,
            ("fact", "constraint", "objective", "plan", "plan", "plan"),
            strict=True,
        )
    }
    utilities = utility_rng.sample(range(100_000, 1_000_000), 3)
    plans = [
        {"alias": alias, "id": items[alias]["id"], "utility": utility}
        for alias, utility in zip(("J3", "J4", "J5"), utilities, strict=True)
    ]
    plan_row_order = ["J3", "J4", "J5"]
    row_rng.shuffle(plan_row_order)
    branch_order = ["S5A", "S5B"]
    branch_rng.shuffle(branch_order)
    branch_seed = generation_rng.randrange(0, 2**31)
    generation_seeds = {
        checkpoint: generation_rng.randrange(0, 2**31)
        for checkpoint in ("S0", "S1", "S2", "S3", "S4")
    }
    generation_seeds.update({"S5A": branch_seed, "S5B": branch_seed})

    trial: dict[str, Any] = {
        "trial_id": trial_id,
        "items": items,
        "plans": plans,
        "plan_row_order": plan_row_order,
        "branch_order": branch_order,
        "generation_seeds": generation_seeds,
        "id_universe": sorted(ids),
    }
    trial["prompts"] = render_prompts(trial)
    trial["truth"] = {
        "S5A": _trial_truth(trial, "S5A"),
        "S5B": _trial_truth(trial, "S5B"),
    }
    return trial


def create_manifest(*, master_seed: int, model: str) -> dict[str, Any]:
    target = create_trial(master_seed, "target")
    donor = create_trial(master_seed, "donor")
    probe_rng = random.Random(derived_seed(master_seed, "probe_seeds"))
    order_rng = random.Random(derived_seed(master_seed, "probe_order"))
    probe_seeds = {
        probe_id: probe_rng.randrange(0, 2**31) for probe_id in PROBES
    }
    tasks = [
        {"branch": branch, "probe_id": probe_id, "arm": arm}
        for branch in ("S5A", "S5B")
        for probe_id in PROBES
        for arm in ARMS
    ]
    order_rng.shuffle(tasks)
    for order, task in enumerate(tasks, 1):
        task["request_order"] = order
        task["seed"] = probe_seeds[task["probe_id"]]

    return {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": "checkpoint_fork_plan_state_v1",
        "protocol_revision": PROTOCOL_REVISION,
        "status": "excluded_exploratory_pilot",
        "created_at": utc_now(),
        "master_seed": master_seed,
        "model": model,
        "api": {
            "surface": "interactions",
            "version": "v1beta",
            "endpoint": API_URL,
            "api_revision_header": DEFAULT_API_REVISION,
            "schema_epoch": "post_2026_06_08_steps_response_format",
            "store": False,
            "previous_interaction_id": None,
        },
        "request_templates": {
            "generation_config_generation": {
                **generation_config(0, probe=False),
                "seed": "per_call_int32_best_effort",
            },
            "generation_config_probe": {
                **generation_config(0, probe=True),
                "seed": "per_probe_int32_best_effort",
            },
            "ack_response_format_sha256": sha256_json(ACK_RESPONSE_FORMAT),
            "probe_response_formats_sha256": sha256_json(
                {
                    probe_id: definition["response_format"]
                    for probe_id, definition in PROBES.items()
                }
            ),
        },
        "transport_policy": {
            "timeout_seconds_per_attempt": HTTP_TIMEOUT_SECONDS,
            "inter_logical_request_delay_seconds": INTER_REQUEST_DELAY_SECONDS,
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
                "2xx_incomplete",
                "2xx_parse_or_shape_failure",
                "2xx_scored_outcome",
            ],
            "selection_rule": "first_observed_nonretryable_response_or_final_attempt",
            "retry_body": "byte_identical_canonical_json",
            "retry_after_header": "recorded_but_ignored",
            "estimand": "outcome_under_frozen_bounded_retry_policy",
        },
        "id_scheme": "crockford_base32_type_neutral_130bit_v1",
        "trials": {"target": target, "donor": donor},
        "probe_seeds": probe_seeds,
        "probe_tasks": tasks,
        "planned_calls": {
            "generation": 14,
            "probes": len(tasks),
            "logical_total": 14 + len(tasks),
            "max_physical_attempts": (14 + len(tasks))
            * MAX_ATTEMPTS_PER_LOGICAL_REQUEST,
        },
    }


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    all_ids: list[str] = []
    for trial_name, trial in manifest["trials"].items():
        ids = list(trial["id_universe"])
        all_ids.extend(ids)
        if len(ids) != 6 or len(set(ids)) != 6:
            errors.append(f"{trial_name}: expected six unique identifiers")
        if any(not is_opaque_id(identifier) for identifier in ids):
            errors.append(f"{trial_name}: noncanonical identifier")
        if any(identifier.startswith(("PLAN_", "FACT_", "CONSTRAINT_")) for identifier in ids):
            errors.append(f"{trial_name}: semantic identifier prefix")
        item_ids = {
            item.get("id")
            for item in trial.get("items", {}).values()
            if isinstance(item, dict)
        }
        if item_ids != set(ids):
            errors.append(f"{trial_name}: id_universe does not equal item IDs")
        expected_roles = {
            "J0": "fact",
            "J1": "constraint",
            "J2": "objective",
            "J3": "plan",
            "J4": "plan",
            "J5": "plan",
        }
        if {
            alias: item.get("role")
            for alias, item in trial.get("items", {}).items()
            if isinstance(item, dict)
        } != expected_roles:
            errors.append(f"{trial_name}: item role mapping is invalid")
        utilities = [plan["utility"] for plan in trial["plans"]]
        if len(set(utilities)) != 3:
            errors.append(f"{trial_name}: utilities are not distinct")
        if set(trial["plan_row_order"]) != {"J3", "J4", "J5"}:
            errors.append(f"{trial_name}: invalid plan row order")
        if trial["generation_seeds"]["S5A"] != trial["generation_seeds"]["S5B"]:
            errors.append(f"{trial_name}: branch generation seeds differ")
        prompt_a = trial["prompts"]["S5A"].replace("MAXIMUM", "EXTREME")
        prompt_b = trial["prompts"]["S5B"].replace("MINIMUM", "EXTREME")
        if prompt_a != prompt_b:
            errors.append(f"{trial_name}: branch prompts differ beyond the selection rule")
        selected_a = trial["truth"]["S5A"]["selected_plan"]
        selected_b = trial["truth"]["S5B"]["selected_plan"]
        if selected_a == selected_b:
            errors.append(f"{trial_name}: branch selections do not diverge")
        ranking_a = trial["truth"]["S5A"]["utility_ranking"]
        ranking_b = trial["truth"]["S5B"]["utility_ranking"]
        if ranking_a != ranking_b or set(ranking_a) != {
            plan["id"] for plan in trial["plans"]
        }:
            errors.append(f"{trial_name}: invalid utility ranking truth")
        plan_ids = {plan["id"] for plan in trial["plans"]}
        ancestry = [
            {
                "id": trial["items"][alias]["id"],
                "role": trial["items"][alias]["role"],
                "status": "active",
            }
            for alias in ("J0", "J1", "J2")
        ]
        ranked = sorted(
            trial["plans"], key=lambda plan: plan["utility"], reverse=True
        )
        for branch, selected in (("S5A", ranked[0]), ("S5B", ranked[-1])):
            truth = trial["truth"].get(branch, {})
            if set(truth) != set(PROBES):
                errors.append(f"{trial_name}/{branch}: truth probe keys differ")
                continue
            expected_truth = {
                "active_ancestry": ancestry,
                "active_objective": [trial["items"]["J2"]["id"]],
                "active_constraint": [trial["items"]["J1"]["id"]],
                "candidate_plans": sorted(plan_ids),
                "selected_plan": [selected["id"]],
                "rejected_plans": sorted(plan_ids - {selected["id"]}),
                "utility_ranking": [plan["id"] for plan in ranked],
            }
            if truth != expected_truth:
                errors.append(f"{trial_name}/{branch}: truth is internally invalid")
            truth_ids = {
                item["id"]
                for item in truth.get("active_ancestry", [])
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
            for probe_id in PROBES:
                if probe_id != "active_ancestry":
                    truth_ids.update(
                        identifier
                        for identifier in truth.get(probe_id, [])
                        if isinstance(identifier, str)
                    )
            if not truth_ids <= set(ids):
                errors.append(f"{trial_name}/{branch}: truth contains foreign IDs")

    if len(all_ids) != len(set(all_ids)):
        errors.append("target and donor identifier universes overlap")

    expected_tasks = {
        (branch, probe_id, arm)
        for branch in ("S5A", "S5B")
        for probe_id in PROBES
        for arm in ARMS
    }
    actual_tasks = {
        (task["branch"], task["probe_id"], task["arm"])
        for task in manifest["probe_tasks"]
    }
    if actual_tasks != expected_tasks or len(manifest["probe_tasks"]) != len(expected_tasks):
        errors.append("probe task matrix is incomplete or duplicated")
    return errors


def generation_config(seed: int, *, probe: bool) -> dict[str, Any]:
    return {
        "thinking_level": "high",
        "thinking_summaries": "none",
        "seed": seed,
        "max_output_tokens": 8192,
    }


def code_hashes(repo_root: Path) -> dict[str, str]:
    relative_paths = (
        "thoughtlab/gemini_interactions.py",
        "thoughtlab/opaque_ids.py",
        "thoughtlab/stateTransitions/fork_pilot.py",
        "thoughtlab/stateTransitions/probes.py",
        "thoughtlab/stateTransitions/score_ground_truth.py",
        "thoughtlab/stateTransitions/experiments/fork_pilot_v3.json",
    )
    return {
        path: sha256_bytes((repo_root / path).read_bytes()) for path in relative_paths
    }


def load_and_validate_experiment_definition(repo_root: Path) -> dict[str, Any]:
    path = (
        repo_root
        / "thoughtlab"
        / "stateTransitions"
        / "experiments"
        / "fork_pilot_v3.json"
    )
    definition = strict_json_loads(path.read_text(encoding="utf-8"))
    if not isinstance(definition, dict):
        raise ValueError("experiment definition must be a JSON object")
    expected = {
        "experiment_id": "checkpoint_fork_plan_state_v1",
        "protocol_revision": PROTOCOL_REVISION,
        "status": "excluded_exploratory_pilot",
        "model": MODEL,
        "api_surface": "interactions_v1beta",
        "api_schema_epoch": "post_2026_06_08_steps_response_format",
        "api_revision_header": None,
        "store": False,
        "thinking_level": "high",
        "thinking_summaries": "none",
        "sampling_parameters": "omitted_for_gemini_3_7_flash",
        "seed_semantics": "best_effort_reproducibility",
        "generation_max_output_tokens": 8192,
        "probe_max_output_tokens": 8192,
        "timeout_seconds_per_attempt": HTTP_TIMEOUT_SECONDS,
        "inter_logical_request_delay_seconds": INTER_REQUEST_DELAY_SECONDS,
        "max_attempts_per_logical_request": MAX_ATTEMPTS_PER_LOGICAL_REQUEST,
        "retry_backoff_seconds": list(RETRY_BACKOFF_SECONDS),
        "retryable_outcomes": [
            "transport_error",
            "http_408",
            "http_429",
            "http_500_502_503_504",
        ],
        "retry_selection_rule": "first_observed_nonretryable_response_or_final_attempt",
        "retry_body": "byte_identical_canonical_json",
        "retry_after_header": "recorded_but_ignored",
        "estimand": "outcome_under_frozen_bounded_retry_policy",
        "id_scheme": "ID_ plus 26 type-neutral Crockford-base32 characters",
        "checkpoints": list(CHECKPOINTS),
        "fork_parent": "S4",
        "probe_ids": list(PROBES),
        "arms": list(ARMS),
    }
    mismatches = [
        key for key, value in expected.items() if definition.get(key) != value
    ]
    if mismatches:
        raise ValueError(
            "experiment definition differs from executable protocol: "
            + ", ".join(mismatches)
        )
    expected_branch_rules = {
        "S5A": "select maximum utility and reject all other candidates",
        "S5B": "select minimum utility and reject all other candidates",
    }
    if definition.get("branch_rules") != expected_branch_rules:
        raise ValueError("experiment definition has different branch rules")
    return definition


class CallStore:
    def __init__(
        self,
        *,
        run_dir: Path,
        api_key: str,
        timeout: int,
        delay_seconds: float,
        transport: Callable[..., InteractionHttpResult] | None = None,
        max_attempts: int = MAX_ATTEMPTS_PER_LOGICAL_REQUEST,
        retry_backoff_seconds: tuple[float, ...] = RETRY_BACKOFF_SECONDS,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.run_dir = run_dir
        self.raw_dir = run_dir / "raw"
        self.api_key = api_key
        self.timeout = timeout
        self.delay_seconds = delay_seconds
        self.transport = transport
        self.max_attempts = max_attempts
        self.retry_backoff_seconds = retry_backoff_seconds
        self.sleeper = sleeper or time.sleep
        self.records: list[dict[str, Any]] = []

    @staticmethod
    def _retryable_reason(result: InteractionHttpResult) -> str:
        if result.transport_error:
            return "transport_error"
        if result.http_status == 408:
            return "http_408"
        if result.http_status == 429:
            return "http_429"
        if result.http_status in {500, 502, 503, 504}:
            return f"http_{result.http_status}"
        return ""

    def invoke_logical(
        self,
        *,
        label: str,
        body: dict[str, Any],
    ) -> tuple[InteractionHttpResult, dict[str, Any]]:
        logical_started_at = utc_now()
        attempts: list[dict[str, Any]] = []
        actual_backoffs: list[float] = []
        final_result: InteractionHttpResult | None = None
        for attempt_number in range(1, self.max_attempts + 1):
            result, record = self.invoke(
                label=f"{label}_attempt{attempt_number}",
                body=body,
            )
            retry_reason = self._retryable_reason(result)
            attempt_record = {
                **record,
                "attempt_index": attempt_number,
                "previous_physical_call_number": attempts[-1]["call_number"]
                if attempts
                else None,
                "retryable_reason": retry_reason or None,
            }
            attempts.append(attempt_record)
            final_result = result
            if not retry_reason or attempt_number == self.max_attempts:
                break
            backoff_index = attempt_number - 1
            if backoff_index < len(self.retry_backoff_seconds):
                backoff = self.retry_backoff_seconds[backoff_index]
                actual_backoffs.append(backoff)
                self.sleeper(backoff)
        if final_result is None:
            raise RuntimeError("logical request made no physical attempt")
        if len({attempt["request_wire_sha256"] for attempt in attempts}) != 1:
            raise RuntimeError("retry attempts did not use byte-identical requests")
        final_retry_reason = self._retryable_reason(final_result)
        if final_retry_reason:
            selection_reason = "retry_budget_exhausted"
        elif len(attempts) == 1:
            selection_reason = "first_attempt_nonretryable"
        else:
            selection_reason = "first_nonretryable_after_retry"
        for attempt in attempts:
            attempt["selected_for_logical_result"] = (
                attempt["attempt_index"] == len(attempts)
            )
        logical_record = {
            "logical_request_id": sha256_text(
                f"{label}:{attempts[0]['request_wire_sha256']}"
            )[:24],
            "logical_label": label,
            "started_at": logical_started_at,
            "completed_at": utc_now(),
            "attempt_count": len(attempts),
            "selected_attempt": len(attempts),
            "selected_physical_call_number": attempts[-1]["call_number"],
            "selected_response_wire_sha256": attempts[-1][
                "response_wire_sha256"
            ],
            "selection_reason": selection_reason,
            "retried": len(attempts) > 1,
            "retry_rule": "transport_or_http_408_429_500_502_503_504_only",
            "planned_backoff_seconds": list(self.retry_backoff_seconds),
            "actual_backoff_seconds": actual_backoffs,
            "request_wire_sha256": attempts[0]["request_wire_sha256"],
            "request_wire_bytes": attempts[0]["request_wire_bytes"],
            "first_attempt_http_status": attempts[0]["http_status"],
            "first_attempt_transport_error": attempts[0]["transport_error"],
            "attempts": attempts,
        }
        safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "-", label).strip("-")
        write_json(self.raw_dir / f"logical_{safe_label}.metadata.json", logical_record)
        if self.delay_seconds > 0:
            self.sleeper(self.delay_seconds)
        return final_result, logical_record

    def invoke(
        self,
        *,
        label: str,
        body: dict[str, Any],
    ) -> tuple[InteractionHttpResult, dict[str, Any]]:
        call_number = len(self.records) + 1
        safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "-", label).strip("-")
        stem = f"{call_number:04d}_{safe_label}"
        request_path = self.raw_dir / f"{stem}.request.json"
        response_path = self.raw_dir / f"{stem}.response.bin"
        metadata_path = self.raw_dir / f"{stem}.metadata.json"

        encoded_body = canonical_json_bytes(body)
        write_bytes(request_path, encoded_body)
        started_at = utc_now()
        transport = self.transport or post_interaction
        result = transport(
            api_key=self.api_key,
            body=body,
            timeout=self.timeout,
            encoded_body=encoded_body,
        )
        response_bytes = result.raw_body_bytes or result.raw_body.encode(
            "utf-8", errors="replace"
        )
        write_bytes(response_path, response_bytes)
        record = {
            "call_number": call_number,
            "label": label,
            "started_at": started_at,
            "completed_at": utc_now(),
            "http_status": result.http_status,
            "elapsed_ms": result.elapsed_ms,
            "request_wire_sha256": sha256_bytes(encoded_body),
            "request_wire_bytes": len(encoded_body),
            "response_wire_sha256": sha256_bytes(response_bytes)
            if response_bytes
            else None,
            "response_wire_bytes": len(response_bytes),
            "response_decoded_chars": len(result.raw_body),
            "transport_error": result.transport_error,
            "response_parse_error": result.response_parse_error,
            "response_headers": result.response_headers or {},
            "raw_request_path": str(request_path.relative_to(self.run_dir)),
            "raw_response_path": str(response_path.relative_to(self.run_dir)),
        }
        write_json(metadata_path, record)
        self.records.append(record)
        write_json(self.run_dir / "call_index.json", self.records)
        print(
            f"[{call_number:03d}] {label} -> "
            f"{result.http_status if result.http_status is not None else 'transport-error'}",
            flush=True,
        )
        return result, record


@dataclass
class CheckpointRuntime:
    checkpoint_id: str
    full_history: list[dict[str, Any]]
    response_steps: list[dict[str, Any]]
    latest_thoughts: list[dict[str, Any]]
    cumulative_thoughts: list[dict[str, Any]]
    latest_outputs: list[dict[str, Any]]
    summary: dict[str, Any]


def _model_output_validation(
    steps: list[dict[str, Any]],
) -> tuple[str, list[str], str]:
    output_steps = select_steps(steps, {"model_output"})
    issues: list[str] = []
    if len(output_steps) != 1:
        issues.append("response did not contain exactly one model_output step")
    for index, step in enumerate(output_steps):
        content = step.get("content")
        if not isinstance(content, list):
            issues.append(f"model_output[{index}].content was not an array")
            continue
        if len(content) != 1:
            issues.append(
                f"model_output[{index}].content did not contain exactly one block"
            )
        for block_index, block in enumerate(content):
            if not isinstance(block, dict):
                issues.append(
                    f"model_output[{index}].content[{block_index}] was not an object"
                )
            elif block.get("type") != "text" or not isinstance(
                block.get("text"), str
            ):
                issues.append(
                    f"model_output[{index}].content[{block_index}] was not text"
                )
    serialized = json.dumps(output_steps, ensure_ascii=True, sort_keys=True)
    payload = {"steps": output_steps}
    return output_text(payload), issues, serialized


def _checkpoint_eligibility(
    *,
    result: InteractionHttpResult,
    payload: dict[str, Any] | None,
    steps: list[dict[str, Any]] | None,
    request_body: dict[str, Any],
    trial: dict[str, Any],
    model: str,
) -> tuple[list[str], dict[str, Any]]:
    reasons: list[str] = []
    visible, output_structure_issues, serialized_outputs = (
        _model_output_validation(steps or [])
    )
    if result.http_status is None or not 200 <= result.http_status < 300:
        reasons.append("generation request was not HTTP 2xx")
    if result.transport_error:
        reasons.append("transport error")
    if result.response_parse_error:
        reasons.append("response body was not a JSON object")
    if not isinstance(payload, dict):
        reasons.append("missing response payload")
    else:
        if payload.get("status") != "completed":
            reasons.append(f"interaction status was {payload.get('status')!r}")
        if payload.get("model") != model:
            reasons.append(f"returned model was {payload.get('model')!r}")
        if payload.get("error") or payload.get("errors"):
            reasons.append("response contained a top-level error")
    if request_body.get("store") is not False:
        reasons.append("store was not false")
    if "previous_interaction_id" in request_body:
        reasons.append("previous_interaction_id was present")

    thought_steps = select_steps(steps or [], {"thought"})
    output_steps = select_steps(steps or [], {"model_output"})
    signature_meta = thought_signature_metadata(steps or [])
    if not thought_steps:
        reasons.append("no thought step")
    if len(signature_meta) != len(thought_steps):
        reasons.append("a thought step lacked a nonempty signature")
    if any(step.get("summary") not in (None, [], "") for step in thought_steps):
        reasons.append("a thought step contained a nonempty summary")
    reasons.extend(output_structure_issues)
    unexpected_types = sorted(
        {
            str(step.get("type") or "")
            for step in (steps or [])
            if step.get("type") not in {"thought", "model_output"}
        }
    )
    if unexpected_types:
        reasons.append(f"unexpected response step types: {unexpected_types}")

    ack_value = None
    ack_parse_error = ""
    try:
        ack_value = strict_json_loads(visible)
    except (json.JSONDecodeError, DuplicateJsonKey) as exc:
        ack_parse_error = str(exc)
        reasons.append("visible output was not strict JSON")
    if ack_value != {"ack": True}:
        reasons.append("visible output was not exactly the acknowledgement object")
    leaked_values = [
        value
        for value in [
            *trial["id_universe"],
            *(str(plan["utility"]) for plan in trial["plans"]),
            trial["trial_id"],
        ]
        if value and value in serialized_outputs
    ]
    if leaked_values:
        reasons.append("visible output leaked prescribed state")

    return reasons, {
        "visible_output_sha256": sha256_text(visible),
        "visible_output_chars": len(visible),
        "visible_ack": ack_value,
        "visible_ack_parse_error": ack_parse_error,
        "visible_leak_count": len(leaked_values),
        "thought_step_count": len(thought_steps),
        "model_output_step_count": len(output_steps),
        "model_output_structure_issues": output_structure_issues,
        "signature_metadata": signature_meta,
        "unexpected_step_types": unexpected_types,
    }


def generate_trial(
    *,
    trial: dict[str, Any],
    model: str,
    store: CallStore,
) -> tuple[dict[str, CheckpointRuntime], list[dict[str, Any]]]:
    runtimes: dict[str, CheckpointRuntime] = {}
    summaries: list[dict[str, Any]] = []
    history: list[dict[str, Any]] = []

    for checkpoint_id in ("S0", "S1", "S2", "S3", "S4"):
        input_steps = copy.deepcopy(history) + [user_step(trial["prompts"][checkpoint_id])]
        body = build_interaction_body(
            model=model,
            input_steps=input_steps,
            generation_config=generation_config(
                trial["generation_seeds"][checkpoint_id], probe=False
            ),
            response_format=ACK_RESPONSE_FORMAT,
        )
        result, call_record = store.invoke_logical(
            label=f"generate_{trial['trial_id']}_{checkpoint_id}",
            body=body,
        )
        steps: list[dict[str, Any]] | None = None
        step_error = ""
        if isinstance(result.payload, dict):
            try:
                steps = response_steps(result.payload)
            except ValueError as exc:
                step_error = str(exc)
        reasons, details = _checkpoint_eligibility(
            result=result,
            payload=result.payload,
            steps=steps,
            request_body=body,
            trial=trial,
            model=model,
        )
        if step_error:
            reasons.append(step_error)
        full_history = input_steps + (copy.deepcopy(steps) if steps is not None else [])
        latest_thoughts = select_steps(steps or [], {"thought"})
        latest_outputs = select_steps(steps or [], {"model_output"})
        cumulative_thoughts = select_steps(full_history, {"thought"})
        summary = {
            "trial_id": trial["trial_id"],
            "checkpoint_id": checkpoint_id,
            "parent_checkpoint_id": None if checkpoint_id == "S0" else CHECKPOINTS[CHECKPOINTS.index(checkpoint_id) - 1],
            "eligible": not reasons,
            "ineligibility_reasons": reasons,
            "prompt_sha256": sha256_text(trial["prompts"][checkpoint_id]),
            "request_input_sha256": sha256_json(input_steps),
            "response_steps_sha256": sha256_json(steps) if steps is not None else None,
            "full_prefix_sha256": sha256_json(full_history),
            "latest_thought_sha256": sha256_json(latest_thoughts),
            "cumulative_thought_sha256": sha256_json(cumulative_thoughts),
            "latest_output_sha256": sha256_json(latest_outputs),
            "http_status": result.http_status,
            "interaction_status": result.payload.get("status") if isinstance(result.payload, dict) else None,
            "requested_model": model,
            "returned_model": result.payload.get("model") if isinstance(result.payload, dict) else None,
            "call": call_record,
            **details,
        }
        summaries.append(summary)
        runtimes[checkpoint_id] = CheckpointRuntime(
            checkpoint_id=checkpoint_id,
            full_history=full_history,
            response_steps=copy.deepcopy(steps or []),
            latest_thoughts=latest_thoughts,
            cumulative_thoughts=cumulative_thoughts,
            latest_outputs=latest_outputs,
            summary=summary,
        )
        if reasons:
            return runtimes, summaries
        history = full_history

    p4_history = copy.deepcopy(runtimes["S4"].full_history)
    p4_hash = sha256_json(p4_history)
    for branch_id in trial["branch_order"]:
        input_steps = copy.deepcopy(p4_history) + [user_step(trial["prompts"][branch_id])]
        if sha256_json(input_steps[:-1]) != p4_hash or input_steps[:-1] != p4_history:
            raise RuntimeError("branch input did not preserve the exact P4 prefix")
        body = build_interaction_body(
            model=model,
            input_steps=input_steps,
            generation_config=generation_config(
                trial["generation_seeds"][branch_id], probe=False
            ),
            response_format=ACK_RESPONSE_FORMAT,
        )
        result, call_record = store.invoke_logical(
            label=f"generate_{trial['trial_id']}_{branch_id}",
            body=body,
        )
        steps = None
        step_error = ""
        if isinstance(result.payload, dict):
            try:
                steps = response_steps(result.payload)
            except ValueError as exc:
                step_error = str(exc)
        reasons, details = _checkpoint_eligibility(
            result=result,
            payload=result.payload,
            steps=steps,
            request_body=body,
            trial=trial,
            model=model,
        )
        if step_error:
            reasons.append(step_error)
        full_history = input_steps + (copy.deepcopy(steps) if steps is not None else [])
        latest_thoughts = select_steps(steps or [], {"thought"})
        latest_outputs = select_steps(steps or [], {"model_output"})
        cumulative_thoughts = select_steps(full_history, {"thought"})
        summary = {
            "trial_id": trial["trial_id"],
            "checkpoint_id": branch_id,
            "parent_checkpoint_id": "S4",
            "fork_parent_prefix_sha256": p4_hash,
            "eligible": not reasons,
            "ineligibility_reasons": reasons,
            "prompt_sha256": sha256_text(trial["prompts"][branch_id]),
            "request_input_sha256": sha256_json(input_steps),
            "response_steps_sha256": sha256_json(steps) if steps is not None else None,
            "full_prefix_sha256": sha256_json(full_history),
            "latest_thought_sha256": sha256_json(latest_thoughts),
            "cumulative_thought_sha256": sha256_json(cumulative_thoughts),
            "latest_output_sha256": sha256_json(latest_outputs),
            "http_status": result.http_status,
            "interaction_status": result.payload.get("status") if isinstance(result.payload, dict) else None,
            "requested_model": model,
            "returned_model": result.payload.get("model") if isinstance(result.payload, dict) else None,
            "call": call_record,
            **details,
        }
        summaries.append(summary)
        runtimes[branch_id] = CheckpointRuntime(
            checkpoint_id=branch_id,
            full_history=full_history,
            response_steps=copy.deepcopy(steps or []),
            latest_thoughts=latest_thoughts,
            cumulative_thoughts=cumulative_thoughts,
            latest_outputs=latest_outputs,
            summary=summary,
        )
    return runtimes, summaries


def arm_steps(
    *,
    arm: str,
    target: CheckpointRuntime,
    donor: CheckpointRuntime,
) -> list[dict[str, Any]]:
    if arm == "full_prefix":
        return copy.deepcopy(target.full_history)
    if arm == "latest_thought":
        return copy.deepcopy(target.latest_thoughts)
    if arm == "cumulative_thought":
        return copy.deepcopy(target.cumulative_thoughts)
    if arm == "visible_only":
        return copy.deepcopy(target.latest_outputs)
    if arm == "probe_only":
        return []
    if arm == "wrong_trial":
        return copy.deepcopy(donor.latest_thoughts)
    raise ValueError(f"unknown arm: {arm}")


def _parse_probe_result(
    *,
    result: InteractionHttpResult,
    model: str,
    kind: str,
) -> dict[str, Any]:
    payload = result.payload
    if result.transport_error:
        return {
            "evaluable": False,
            "outcome": "transport_error",
            "transport_error": result.transport_error,
        }
    if result.http_status is None or not 200 <= result.http_status < 300:
        if result.http_status == 400:
            outcome = "protocol_rejected"
        elif result.http_status == 429:
            outcome = "rate_limited"
        elif result.http_status is not None and result.http_status >= 500:
            outcome = "provider_error"
        else:
            outcome = "http_error"
        return {
            "evaluable": False,
            "outcome": outcome,
            "http_status": result.http_status,
        }
    if result.response_parse_error or not isinstance(payload, dict):
        return {"evaluable": False, "outcome": "response_parse_error"}
    if payload.get("status") != "completed":
        return {
            "evaluable": False,
            "outcome": "interaction_incomplete",
            "interaction_status": payload.get("status"),
        }
    if payload.get("model") != model:
        return {
            "evaluable": False,
            "outcome": "model_mismatch",
            "returned_model": payload.get("model"),
        }
    if payload.get("error") or payload.get("errors"):
        return {"evaluable": False, "outcome": "response_reported_error"}
    try:
        steps = response_steps(payload)
    except ValueError as exc:
        return {
            "evaluable": False,
            "outcome": "response_shape_error",
            "shape_errors": [str(exc)],
        }
    unexpected_types = sorted(
        {
            str(step.get("type") or "")
            for step in steps
            if step.get("type") not in {"thought", "model_output"}
        }
    )
    text, output_issues, _ = _model_output_validation(steps)
    shape_errors = list(output_issues)
    if unexpected_types:
        shape_errors.append(f"unexpected response step types: {unexpected_types}")
    if shape_errors:
        return {
            "evaluable": False,
            "outcome": "response_shape_error",
            "shape_errors": shape_errors,
            "text": text,
            "response_step_count": len(steps),
            "unexpected_step_types": unexpected_types,
        }
    if not text:
        return {"evaluable": False, "outcome": "empty_response", "text": ""}
    try:
        parsed = strict_json_loads(text)
    except DuplicateJsonKey as exc:
        return {
            "evaluable": False,
            "outcome": "duplicate_json_key",
            "parse_error": str(exc),
            "text": text,
        }
    except json.JSONDecodeError as exc:
        return {
            "evaluable": False,
            "outcome": "invalid_json",
            "parse_error": str(exc),
            "text": text,
        }
    normalized = validate_probe_answer(kind, parsed)
    return {
        "evaluable": bool(normalized.get("schema_valid")),
        "outcome": "scored" if normalized.get("schema_valid") else "schema_invalid",
        "text": text,
        "parsed": parsed,
        "normalized": normalized,
        "response_step_count": len(steps),
        "unexpected_step_types": unexpected_types,
    }


def run_probes(
    *,
    manifest: dict[str, Any],
    model: str,
    target_runtimes: dict[str, CheckpointRuntime],
    donor_runtimes: dict[str, CheckpointRuntime],
    store: CallStore,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    target_trial = manifest["trials"]["target"]
    donor_trial = manifest["trials"]["donor"]
    target_universe = set(target_trial["id_universe"])
    donor_universe = set(donor_trial["id_universe"])

    for task in manifest["probe_tasks"]:
        branch = task["branch"]
        probe_id = task["probe_id"]
        arm = task["arm"]
        spec = PROBES[probe_id]
        carrier = arm_steps(
            arm=arm,
            target=target_runtimes[branch],
            donor=donor_runtimes[branch],
        )
        input_steps = carrier + [user_step(spec["prompt"])]
        body = build_interaction_body(
            model=model,
            input_steps=input_steps,
            generation_config=generation_config(task["seed"], probe=True),
            response_format=spec["response_format"],
        )
        http_result, call_record = store.invoke_logical(
            label=f"probe_{task['request_order']:03d}_{branch}_{probe_id}_{arm}",
            body=body,
        )
        parsed_result = _parse_probe_result(
            result=http_result,
            model=model,
            kind=spec["kind"],
        )
        current_score = None
        donor_score = None
        if parsed_result.get("evaluable"):
            current_score = score_probe_answer(
                kind=spec["kind"],
                normalized=parsed_result["normalized"],
                expected=target_trial["truth"][branch][probe_id],
                truth_universe=target_universe,
            )
            if arm == "wrong_trial":
                donor_score = score_probe_answer(
                    kind=spec["kind"],
                    normalized=parsed_result["normalized"],
                    expected=donor_trial["truth"][branch][probe_id],
                    truth_universe=donor_universe,
                )
        protocol_class = {
            "full_prefix": "documented_valid",
            "probe_only": "documented_valid",
            "latest_thought": "accepted_or_rejected_experimental",
            "cumulative_thought": "accepted_or_rejected_experimental",
            "visible_only": "accepted_or_rejected_experimental",
            "wrong_trial": "accepted_or_rejected_experimental",
        }[arm]
        carrier_source_trial = (
            None
            if arm == "probe_only"
            else "donor"
            if arm == "wrong_trial"
            else "target"
        )
        compact = {
            "schema_version": "fork_probe_result_v2",
            "request_order": task["request_order"],
            "branch": branch,
            "probe_id": probe_id,
            "probe_kind": spec["kind"],
            "arm": arm,
            "protocol_class": protocol_class,
            "fresh_stateless_request": True,
            "carrier_source_trial": carrier_source_trial,
            "carrier_source_checkpoint": None
            if carrier_source_trial is None
            else branch,
            "carrier_step_count": len(carrier),
            "carrier_sha256": sha256_json(carrier),
            "carrier_signature_metadata": thought_signature_metadata(carrier),
            "http_status": http_result.http_status,
            "interaction_status": http_result.payload.get("status")
            if isinstance(http_result.payload, dict)
            else None,
            "returned_model": http_result.payload.get("model")
            if isinstance(http_result.payload, dict)
            else None,
            "response_error_sha256": sha256_text(error_text(http_result.payload))
            if error_text(http_result.payload)
            else None,
            "response_error_chars": len(error_text(http_result.payload)),
            "usage": http_result.payload.get("usage")
            if isinstance(http_result.payload, dict)
            else None,
            "call": call_record,
            **parsed_result,
            "score_current": current_score,
            "score_donor": donor_score,
        }
        results.append(compact)
        write_json(store.run_dir / "probe_results.partial.json", results)
    return results


def _result_index(results: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    index: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in results:
        if not isinstance(row, dict) or not all(
            isinstance(row.get(key), str) for key in ("branch", "probe_id", "arm")
        ):
            continue
        key = (row["branch"], row["probe_id"], row["arm"])
        index.setdefault(key, row)
    return index


def _exact(
    index: dict[tuple[str, str, str], dict[str, Any]],
    *,
    branch: str,
    probe_id: str,
    arm: str,
    basis: str = "current",
    first_attempt_only: bool = False,
) -> bool:
    row = index.get((branch, probe_id, arm))
    if not isinstance(row, dict):
        return False
    if first_attempt_only:
        call = row.get("call")
        if not isinstance(call, dict) or call.get("attempt_count") != 1:
            return False
    score = row.get(f"score_{basis}")
    return bool(isinstance(score, dict) and score.get("exact"))


def _branch_artifact_status(
    checkpoint_summaries: list[dict[str, Any]], trial_id: str
) -> dict[str, Any]:
    rows: dict[str, dict[str, Any]] = {}
    duplicates: set[str] = set()
    for row in checkpoint_summaries:
        if not isinstance(row, dict):
            continue
        if row.get("trial_id") != trial_id:
            continue
        checkpoint_id = row.get("checkpoint_id")
        if not isinstance(checkpoint_id, str):
            continue
        if checkpoint_id in rows:
            duplicates.add(checkpoint_id)
        else:
            rows[checkpoint_id] = row
    parent = rows.get("S4", {})
    branch_a = rows.get("S5A", {})
    branch_b = rows.get("S5B", {})
    expected_parent_hash = parent.get("full_prefix_sha256")

    def distinct(field: str) -> bool:
        left = branch_a.get(field)
        right = branch_b.get(field)
        return bool(left and right and left != right)

    return {
        "trial_id": trial_id,
        "checkpoints_present": sorted(rows),
        "duplicate_checkpoints": sorted(duplicates),
        "fork_parent_exact": bool(
            expected_parent_hash
            and branch_a.get("fork_parent_prefix_sha256") == expected_parent_hash
            and branch_b.get("fork_parent_prefix_sha256") == expected_parent_hash
        ),
        "branch_response_steps_distinct": distinct("response_steps_sha256"),
        "latest_response_thought_bundles_distinct": distinct(
            "latest_thought_sha256"
        ),
        "cumulative_thought_bundles_distinct": distinct(
            "cumulative_thought_sha256"
        ),
    }


def composite_for_arm(
    results: list[dict[str, Any]],
    arm: str,
    *,
    basis: str,
    first_attempt_only: bool = False,
) -> dict[str, Any]:
    index = _result_index(results)
    shared_probe_ids = (
        "active_ancestry",
        "active_objective",
        "active_constraint",
        "candidate_plans",
    )
    shared = all(
        _exact(
            index,
            branch=branch,
            probe_id=probe_id,
            arm=arm,
            basis=basis,
            first_attempt_only=first_attempt_only,
        )
        for branch in ("S5A", "S5B")
        for probe_id in shared_probe_ids
    )
    divergence = all(
        _exact(
            index,
            branch=branch,
            probe_id=probe_id,
            arm=arm,
            basis=basis,
            first_attempt_only=first_attempt_only,
        )
        for branch in ("S5A", "S5B")
        for probe_id in ("selected_plan", "rejected_plans")
    )
    ranking = all(
        _exact(
            index,
            branch=branch,
            probe_id="utility_ranking",
            arm=arm,
            basis=basis,
            first_attempt_only=first_attempt_only,
        )
        for branch in ("S5A", "S5B")
    )
    exact_count = sum(
        int(
            _exact(
                index,
                branch=branch,
                probe_id=probe_id,
                arm=arm,
                basis=basis,
                first_attempt_only=first_attempt_only,
            )
        )
        for branch in ("S5A", "S5B")
        for probe_id in PROBES
    )
    return {
        "basis": basis,
        "first_attempt_only": first_attempt_only,
        "shared_ancestry_exact": shared,
        "fork_divergence_exact": divergence,
        "ranking_preserved_exact": ranking,
        "full_fork_composite": shared and divergence and ranking,
        "exact_probe_results": exact_count,
        "total_probe_results": 14,
    }


def summarize_results(
    *,
    manifest: dict[str, Any],
    checkpoint_summaries: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    index = _result_index(results)
    expected_probe_keys = {
        (task["branch"], task["probe_id"], task["arm"])
        for task in manifest["probe_tasks"]
    }
    probe_key_counts: dict[tuple[str, str, str], int] = {}
    malformed_probe_rows = 0
    for row in results:
        if not isinstance(row, dict) or not all(
            isinstance(row.get(key), str) for key in ("branch", "probe_id", "arm")
        ):
            malformed_probe_rows += 1
            continue
        key = (row["branch"], row["probe_id"], row["arm"])
        probe_key_counts[key] = probe_key_counts.get(key, 0) + 1
    duplicate_probe_keys = sorted(
        "/".join(key) for key, count in probe_key_counts.items() if count > 1
    )
    probe_matrix_complete = (
        not malformed_probe_rows
        and not duplicate_probe_keys
        and len(results) == len(expected_probe_keys)
        and set(probe_key_counts) == expected_probe_keys
    )

    composites = {
        arm: composite_for_arm(results, arm, basis="current") for arm in ARMS
    }
    wrong_donor = composite_for_arm(results, "wrong_trial", basis="donor")
    first_attempt_composites = {
        arm: composite_for_arm(
            results,
            arm,
            basis="current",
            first_attempt_only=True,
        )
        for arm in ARMS
    }
    first_attempt_wrong_donor = composite_for_arm(
        results,
        "wrong_trial",
        basis="donor",
        first_attempt_only=True,
    )
    target_universe = set(manifest["trials"]["target"]["id_universe"])

    control_status: dict[str, dict[str, Any]] = {}
    for arm in ("visible_only", "probe_only"):
        rows = [
            row
            for row in (
                index.get((branch, probe_id, arm))
                for branch in ("S5A", "S5B")
                for probe_id in PROBES
            )
            if isinstance(row, dict)
        ]
        hits: set[str] = set()
        for row in rows:
            score = row.get("score_current")
            if isinstance(score, dict):
                hits.update(score.get("truth_universe_hits") or [])
        raw_target_hits = sorted(
            identifier
            for identifier in target_universe
            if any(identifier in str(row.get("text") or "") for row in rows)
        )
        unknown_empty_count = sum(
            1
            for row in rows
            if row.get("evaluable")
            and isinstance(row.get("normalized"), dict)
            and row["normalized"].get("knowledge") == "unknown"
            and row["normalized"].get("collection") == []
        )
        target_hits = sorted(hits & target_universe)
        control_status[arm] = {
            "attempts": len(rows),
            "evaluable": sum(bool(row.get("evaluable")) for row in rows),
            "unknown_empty": unknown_empty_count,
            "scored_target_id_hits": target_hits,
            "raw_target_id_hits": raw_target_hits,
            "clean": len(rows) == 14
            and unknown_empty_count == 14
            and not target_hits
            and not raw_target_hits,
            "first_attempt_clean": len(rows) == 14
            and unknown_empty_count == 14
            and not target_hits
            and not raw_target_hits
            and all(
                isinstance(row.get("call"), dict)
                and row["call"].get("attempt_count") == 1
                for row in rows
            ),
        }

    expected_generation_keys = {
        (trial_id, checkpoint_id)
        for trial_id in ("target", "donor")
        for checkpoint_id in CHECKPOINTS
    }
    generation_key_counts: dict[tuple[str, str], int] = {}
    malformed_checkpoint_rows = 0
    for row in checkpoint_summaries:
        if not isinstance(row, dict):
            malformed_checkpoint_rows += 1
            continue
        key = (row.get("trial_id"), row.get("checkpoint_id"))
        if all(isinstance(value, str) for value in key):
            generation_key_counts[key] = generation_key_counts.get(key, 0) + 1
    generation_matrix_complete = (
        not malformed_checkpoint_rows
        and len(checkpoint_summaries) == len(expected_generation_keys)
        and set(generation_key_counts) == expected_generation_keys
        and all(count == 1 for count in generation_key_counts.values())
    )
    generation_eligible = generation_matrix_complete and all(
        isinstance(row, dict) and row.get("eligible")
        for row in checkpoint_summaries
    )
    generation_first_attempt_complete = generation_eligible and all(
        isinstance(row.get("call"), dict)
        and row["call"].get("attempt_count") == 1
        for row in checkpoint_summaries
        if isinstance(row, dict)
    )
    branch_artifacts = {
        trial_id: _branch_artifact_status(checkpoint_summaries, trial_id)
        for trial_id in ("target", "donor")
    }
    controls_clear = all(
        control_status[arm]["clean"] for arm in ("visible_only", "probe_only")
    )
    first_attempt_controls_clear = all(
        control_status[arm]["first_attempt_clean"]
        for arm in ("visible_only", "probe_only")
    )
    full_prefix_adherence = composites["full_prefix"]["full_fork_composite"]
    wrong_trial_follows_donor = (
        wrong_donor["full_fork_composite"]
        and composites["wrong_trial"]["exact_probe_results"] == 0
    )
    first_attempt_wrong_trial_follows_donor = (
        first_attempt_wrong_donor["full_fork_composite"]
        and first_attempt_composites["wrong_trial"]["exact_probe_results"] == 0
    )
    shared_fork_integrity = all(
        branch_artifacts[trial_id]["fork_parent_exact"]
        and branch_artifacts[trial_id]["branch_response_steps_distinct"]
        for trial_id in ("target", "donor")
    ) and branch_artifacts["donor"][
        "latest_response_thought_bundles_distinct"
    ]
    common_gate = (
        generation_eligible
        and probe_matrix_complete
        and full_prefix_adherence
        and controls_clear
        and wrong_trial_follows_donor
        and shared_fork_integrity
    )
    latest_positive = (
        composites["latest_thought"]["full_fork_composite"]
        and common_gate
        and branch_artifacts["target"][
            "latest_response_thought_bundles_distinct"
        ]
    )
    cumulative_positive = (
        composites["cumulative_thought"]["full_fork_composite"]
        and common_gate
        and branch_artifacts["target"][
            "cumulative_thought_bundles_distinct"
        ]
    )
    first_attempt_common_gate = (
        generation_first_attempt_complete
        and probe_matrix_complete
        and first_attempt_composites["full_prefix"]["full_fork_composite"]
        and first_attempt_controls_clear
        and first_attempt_wrong_trial_follows_donor
        and shared_fork_integrity
    )
    first_attempt_latest_positive = (
        first_attempt_composites["latest_thought"]["full_fork_composite"]
        and first_attempt_common_gate
        and branch_artifacts["target"][
            "latest_response_thought_bundles_distinct"
        ]
    )
    first_attempt_cumulative_positive = (
        first_attempt_composites["cumulative_thought"]["full_fork_composite"]
        and first_attempt_common_gate
        and branch_artifacts["target"][
            "cumulative_thought_bundles_distinct"
        ]
    )
    retry_counts_by_arm = {
        arm: sum(
            1
            for row in results
            if isinstance(row, dict)
            and row.get("arm") == arm
            and isinstance(row.get("call"), dict)
            and row["call"].get("attempt_count", 1) > 1
        )
        for arm in ARMS
    }
    generation_retry_count = sum(
        1
        for row in checkpoint_summaries
        if isinstance(row, dict)
        and isinstance(row.get("call"), dict)
        and row["call"].get("attempt_count", 1) > 1
    )
    return {
        "schema_version": "fork_pilot_summary_v2",
        "experiment_id": manifest["experiment_id"],
        "status": "excluded_exploratory_pilot",
        "model": manifest["model"],
        "generation_eligible": generation_eligible,
        "generation_matrix_complete": generation_matrix_complete,
        "malformed_checkpoint_rows": malformed_checkpoint_rows,
        "checkpoint_count": len(checkpoint_summaries),
        "probe_attempts_planned": len(manifest["probe_tasks"]),
        "probe_attempts_completed": len(results),
        "probe_matrix_complete": probe_matrix_complete,
        "duplicate_probe_keys": duplicate_probe_keys,
        "malformed_probe_rows": malformed_probe_rows,
        "probe_outcomes": {
            outcome: sum(
                1
                for row in results
                if isinstance(row, dict) and str(row.get("outcome")) == outcome
            )
            for outcome in sorted(
                {
                    str(row.get("outcome"))
                    for row in results
                    if isinstance(row, dict)
                }
            )
        },
        "composites_current_truth": composites,
        "wrong_trial_donor_truth": wrong_donor,
        "retry_counts_by_arm": retry_counts_by_arm,
        "generation_retry_count": generation_retry_count,
        "branch_artifact_status": branch_artifacts,
        "shared_fork_integrity": shared_fork_integrity,
        "control_status": control_status,
        "controls_clean_unknown_empty": controls_clear,
        "full_prefix_adherence_composite": full_prefix_adherence,
        "wrong_trial_follows_donor_composite": wrong_trial_follows_donor,
        "latest_positive_exploratory_observation": latest_positive,
        "cumulative_positive_exploratory_observation": cumulative_positive,
        "first_attempt_sensitivity": {
            "generation_complete_without_retry": generation_first_attempt_complete,
            "controls_clean_without_retry": first_attempt_controls_clear,
            "composites_current_truth": first_attempt_composites,
            "wrong_trial_donor_truth": first_attempt_wrong_donor,
            "wrong_trial_follows_donor": first_attempt_wrong_trial_follows_donor,
            "latest_positive_exploratory_observation": first_attempt_latest_positive,
            "cumulative_positive_exploratory_observation": first_attempt_cumulative_positive,
        },
        "checkpoint_summaries": checkpoint_summaries,
    }


def _cell(
    index: dict[tuple[str, str, str], dict[str, Any]],
    branch: str,
    probe_id: str,
    arm: str,
) -> str:
    row = index.get((branch, probe_id, arm))
    if not isinstance(row, dict):
        return "!missing_result"
    if not row.get("evaluable"):
        return f"!{row.get('outcome')}"
    current_score = row.get("score_current") or {}
    current = "Y" if current_score.get("exact") else "N"
    if arm == "wrong_trial":
        donor_score = row.get("score_donor") or {}
        donor = "Y" if donor_score.get("exact") else "N"
        return f"T{current}/D{donor}"
    return current


def render_review(
    *,
    run_dir: Path,
    manifest: dict[str, Any],
    summary: dict[str, Any],
    results: list[dict[str, Any]],
) -> str:
    index = _result_index(results)
    lines = [
        "# Excluded checkpoint-fork pilot review",
        "",
        f"- Model: `{manifest['model']}`",
        f"- API: Interactions `v1beta`, schema epoch `{manifest['api']['schema_epoch']}`",
        "- API revision header: omitted (the retired migration header no longer pins a revision)",
        f"- Protocol revision: `{manifest['protocol_revision']}`",
        f"- Run timestamp: `{manifest['created_at']}`",
        f"- Master seed: `{manifest['master_seed']}`",
        f"- Generation eligible: `{summary['generation_eligible']}`",
        f"- Probe calls completed: `{summary['probe_attempts_completed']}/{summary['probe_attempts_planned']}`",
        f"- Logical/physical calls: `{summary.get('logical_call_attempts', 'n/a')}/{summary.get('physical_call_attempts', 'n/a')}`",
        "- Raw signed artifacts: retained locally under `raw/`; never reproduced in this report",
        "",
        "## Exact recovery matrix",
        "",
        "`Y` means exact target-truth recovery. For wrong-trial, `T` is target truth and `D` is donor truth.",
        "",
        "| Branch | Probe | Full prefix | Latest-response thought bundle | Cumulative thoughts | Visible only | Probe only | Wrong trial T/D |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for branch in ("S5A", "S5B"):
        for probe_id in PROBES:
            cells = [
                _cell(index, branch, probe_id, arm)
                for arm in (
                    "full_prefix",
                    "latest_thought",
                    "cumulative_thought",
                    "visible_only",
                    "probe_only",
                    "wrong_trial",
                )
            ]
            lines.append(
                f"| {branch} | {probe_id} | " + " | ".join(cells) + " |"
            )

    lines.extend(["", "## Composite results", ""])
    for arm in ARMS:
        composite = summary["composites_current_truth"][arm]
        lines.append(
            f"- `{arm}`: {composite['exact_probe_results']}/14 exact; "
            f"full fork composite `{composite['full_fork_composite']}`"
        )
    donor = summary["wrong_trial_donor_truth"]
    lines.append(
        f"- `wrong_trial` against donor truth: {donor['exact_probe_results']}/14 exact; "
        f"full donor composite `{donor['full_fork_composite']}`"
    )
    lines.extend(
        [
            "",
            "## Prespecified exploratory gates",
            "",
            f"- Complete probe matrix: `{summary['probe_matrix_complete']}`",
            f"- Exact shared fork parent plus distinct branch artifacts: `{summary['shared_fork_integrity']}`",
            f"- Full-prefix task-adherence composite: `{summary['full_prefix_adherence_composite']}`",
            f"- Visible/probe controls are all evaluable `unknown + []`: `{summary['controls_clean_unknown_empty']}`",
            f"- Wrong-trial artifacts follow donor rather than target truth: `{summary['wrong_trial_follows_donor_composite']}`",
            f"- Latest-response thought-bundle positive exploratory observation: `{summary['latest_positive_exploratory_observation']}`",
            f"- Cumulative-thought positive exploratory observation: `{summary['cumulative_positive_exploratory_observation']}`",
            "",
            "## Transport-policy sensitivity",
            "",
            f"- Generation logical requests retried: `{summary['generation_retry_count']}/14`",
            f"- Probe retries by arm: `{json.dumps(summary['retry_counts_by_arm'], sort_keys=True)}`",
            f"- Latest-bundle positive using first attempts only: `{summary['first_attempt_sensitivity']['latest_positive_exploratory_observation']}`",
            f"- Cumulative-bundle positive using first attempts only: `{summary['first_attempt_sensitivity']['cumulative_positive_exploratory_observation']}`",
            "",
            "## Interpretation boundary",
            "",
            "This is an excluded exploratory pilot. Even a clean positive result is limited to the exact model, API schema epoch, prompts, carrier shapes, and run date above. It does not show that raw signature bytes alone were tested, that rejected plans were organically considered, that chain-of-thought was reconstructed, or that the artifacts expose the complete latent state.",
            "",
            f"Machine-readable summary: `{(run_dir / 'summary.json').name}`",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--out")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--timeout", type=int, default=HTTP_TIMEOUT_SECONDS)
    parser.add_argument("--delay", type=float, default=INTER_REQUEST_DELAY_SECONDS)
    args = parser.parse_args()

    if args.model != MODEL:
        print(
            f"This frozen pilot requires --model {MODEL}; received {args.model!r}.",
            file=sys.stderr,
        )
        return 2
    if (
        args.timeout != HTTP_TIMEOUT_SECONDS
        or args.delay != INTER_REQUEST_DELAY_SECONDS
    ):
        print(
            "This frozen pilot requires "
            f"--timeout {HTTP_TIMEOUT_SECONDS} and "
            f"--delay {INTER_REQUEST_DELAY_SECONDS}.",
            file=sys.stderr,
        )
        return 2

    seed = args.seed if args.seed is not None else secrets.randbits(63)
    run_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    repo_root = Path(__file__).resolve().parents[2]
    try:
        experiment_definition = load_and_validate_experiment_definition(repo_root)
    except (OSError, ValueError, json.JSONDecodeError, DuplicateJsonKey) as exc:
        print(f"Frozen experiment definition is invalid: {exc}", file=sys.stderr)
        return 2
    run_dir = resolve_run_directory(
        repo_root=repo_root,
        requested_out=args.out,
        run_tag=run_tag,
        seed=seed,
    )
    if args.execute and not is_private_run_directory(
        repo_root=repo_root, run_dir=run_dir
    ):
        print(
            "Execution output must resolve beneath the repository's ignored "
            f"private results directory: {(repo_root / 'results').resolve()}",
            file=sys.stderr,
        )
        return 2
    run_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        run_dir.mkdir(exist_ok=False)
    except FileExistsError:
        print(f"Refusing to reuse an existing run directory: {run_dir}", file=sys.stderr)
        return 2

    manifest = create_manifest(master_seed=seed, model=args.model)
    manifest_errors = validate_manifest(manifest)
    if manifest_errors:
        write_json(run_dir / "manifest.invalid.json", manifest)
        print("Manifest validation failed:", file=sys.stderr)
        for error in manifest_errors:
            print(f"- {error}", file=sys.stderr)
        return 2

    write_json(run_dir / "experiment_definition.json", experiment_definition)
    write_json(run_dir / "manifest.json", manifest)
    preregistration = {
        "schema_version": "fork_pilot_preregistration_v1",
        "frozen_at": utc_now(),
        "manifest_sha256": sha256_json(manifest),
        "experiment_definition_sha256": sha256_json(experiment_definition),
        "probe_definitions_sha256": sha256_json(PROBES),
        "code_hashes": code_hashes(repo_root),
        "eligibility_decided_before_probing": True,
        "planned_calls": manifest["planned_calls"],
        "raw_artifacts_private": True,
    }
    write_json(run_dir / "preregistration.json", preregistration)
    print(f"Prepared frozen pilot manifest: {run_dir}", flush=True)
    print(f"Manifest SHA-256: {preregistration['manifest_sha256']}", flush=True)
    if not args.execute:
        print("Dry run only; no API calls made.", flush=True)
        return 0

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("Set GEMINI_API_KEY to execute the pilot.", file=sys.stderr)
        return 2

    store = CallStore(
        run_dir=run_dir,
        api_key=api_key,
        timeout=args.timeout,
        delay_seconds=args.delay,
    )
    checkpoint_summaries: list[dict[str, Any]] = []
    runtimes: dict[str, dict[str, CheckpointRuntime]] = {}
    for trial_name in ("target", "donor"):
        trial_runtime, summaries = generate_trial(
            trial=manifest["trials"][trial_name],
            model=args.model,
            store=store,
        )
        runtimes[trial_name] = trial_runtime
        checkpoint_summaries.extend(summaries)
        write_json(run_dir / "checkpoint_summaries.partial.json", checkpoint_summaries)

    generation_eligible = (
        len(checkpoint_summaries) == 14
        and all(row.get("eligible") for row in checkpoint_summaries)
        and all(branch in runtimes["target"] for branch in ("S5A", "S5B"))
        and all(branch in runtimes["donor"] for branch in ("S5A", "S5B"))
    )
    if not generation_eligible:
        failure_summary = {
            "schema_version": "fork_pilot_generation_failure_v1",
            "generation_eligible": False,
            "checkpoint_summaries": checkpoint_summaries,
            "probe_attempts_completed": 0,
            "physical_call_attempts": len(store.records),
        }
        write_json(run_dir / "summary.json", failure_summary)
        print("Generation eligibility failed; probes were not run.", file=sys.stderr)
        return 3

    results = run_probes(
        manifest=manifest,
        model=args.model,
        target_runtimes=runtimes["target"],
        donor_runtimes=runtimes["donor"],
        store=store,
    )
    write_json(run_dir / "probe_results.json", results)
    summary = summarize_results(
        manifest=manifest,
        checkpoint_summaries=checkpoint_summaries,
        results=results,
    )
    summary["physical_call_attempts"] = len(store.records)
    summary["logical_call_attempts"] = len(checkpoint_summaries) + len(results)
    write_json(run_dir / "summary.json", summary)
    review = render_review(
        run_dir=run_dir,
        manifest=manifest,
        summary=summary,
        results=results,
    )
    write_text(run_dir / "review.md", review)
    print(f"Review report: {run_dir / 'review.md'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
