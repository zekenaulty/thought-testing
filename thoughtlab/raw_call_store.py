"""Transport-neutral exact request/response archive with bounded retries."""

from __future__ import annotations

import copy
import json
import os
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from thoughtlab.gemini_generate_content import (
    canonical_json_bytes,
    sha256_bytes,
    sha256_text,
)


class HttpResultLike(Protocol):
    http_status: int | None
    raw_body: str
    raw_body_bytes: bytes
    transport_error: str
    response_parse_error: str
    elapsed_ms: int
    response_headers: dict[str, str] | None


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
        replace_delays = (0.01, 0.05, 0.1, 0.25, 0.5)
        for retry_index in range(len(replace_delays) + 1):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if retry_index == len(replace_delays):
                    raise
                time.sleep(replace_delays[retry_index])
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def write_json(path: Path, value: Any) -> None:
    _atomic_write(
        path,
        json.dumps(value, ensure_ascii=True, indent=2).encode("utf-8"),
    )


def write_text(path: Path, value: str) -> None:
    _atomic_write(path, value.encode("utf-8"))


def write_bytes(path: Path, value: bytes) -> None:
    _atomic_write(path, value)


def bounded_storage_label(label: str, *, max_chars: int = 56) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", label).strip("-") or "call"
    if len(safe) <= max_chars:
        return safe
    digest = sha256_text(label)[:16]
    prefix_chars = max_chars - len(digest) - 1
    return f"{safe[:prefix_chars]}-{digest}"


class RawCallStore:
    def __init__(
        self,
        *,
        run_dir: Path,
        api_key: str,
        timeout: int,
        delay_seconds: float,
        transport: Callable[..., HttpResultLike],
        max_attempts: int,
        retry_backoff_seconds: tuple[float, ...],
        request_target: dict[str, str],
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
        expected_target_keys = {"api", "method", "endpoint", "model"}
        if set(request_target) != expected_target_keys or any(
            not isinstance(value, str) or not value
            for value in request_target.values()
        ):
            raise ValueError(
                "request_target must contain nonempty api, method, endpoint, "
                "and model strings"
            )
        if request_target["method"] != "POST":
            raise ValueError("request_target method must be POST")
        self.request_target = copy.deepcopy(request_target)
        self.sleeper = sleeper or time.sleep
        self.records: list[dict[str, Any]] = []

    @staticmethod
    def _retryable_reason(result: HttpResultLike) -> str:
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
    ) -> tuple[HttpResultLike, dict[str, Any]]:
        logical_started_at = utc_now()
        attempts: list[dict[str, Any]] = []
        actual_backoffs: list[float] = []
        final_result: HttpResultLike | None = None
        for attempt_number in range(1, self.max_attempts + 1):
            result, record = self.invoke(
                label=f"{label}_attempt{attempt_number}",
                body=body,
            )
            retry_reason = self._retryable_reason(result)
            attempt_record = {
                **record,
                "attempt_index": attempt_number,
                "previous_physical_call_number": (
                    attempts[-1]["call_number"] if attempts else None
                ),
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
            "request_target": copy.deepcopy(self.request_target),
            "attempts": attempts,
        }
        safe_label = bounded_storage_label(label)
        write_json(
            self.raw_dir / f"logical_{safe_label}.metadata.json",
            logical_record,
        )
        if self.delay_seconds > 0:
            self.sleeper(self.delay_seconds)
        return final_result, logical_record

    def invoke(
        self,
        *,
        label: str,
        body: dict[str, Any],
    ) -> tuple[HttpResultLike, dict[str, Any]]:
        call_number = len(self.records) + 1
        safe_label = bounded_storage_label(label)
        stem = f"{call_number:04d}_{safe_label}"
        request_path = self.raw_dir / f"{stem}.request.json"
        response_path = self.raw_dir / f"{stem}.response.bin"
        metadata_path = self.raw_dir / f"{stem}.metadata.json"

        encoded_body = canonical_json_bytes(body)
        write_bytes(request_path, encoded_body)
        record = {
            "call_number": call_number,
            "label": label,
            "started_at": utc_now(),
            "completed_at": None,
            "attempt_state": "request_persisted_transport_outcome_unknown",
            "http_status": None,
            "elapsed_ms": None,
            "request_wire_sha256": sha256_bytes(encoded_body),
            "request_wire_bytes": len(encoded_body),
            "response_wire_sha256": None,
            "response_wire_bytes": None,
            "response_decoded_chars": None,
            "transport_error": None,
            "response_parse_error": None,
            "response_headers": {},
            "raw_request_path": str(request_path.relative_to(self.run_dir)),
            "raw_response_path": str(response_path.relative_to(self.run_dir)),
            "request_target": copy.deepcopy(self.request_target),
        }
        self.records.append(record)
        write_json(metadata_path, record)
        write_json(self.raw_dir / "call_index.json", self.records)
        try:
            result = self.transport(
                api_key=self.api_key,
                body=body,
                timeout=self.timeout,
                encoded_body=encoded_body,
            )
            response_bytes = result.raw_body_bytes or result.raw_body.encode(
                "utf-8", errors="replace"
            )
            write_bytes(response_path, response_bytes)
        except BaseException:
            record["completed_at"] = utc_now()
            record["attempt_state"] = "transport_interrupted_outcome_unknown"
            try:
                write_json(metadata_path, record)
                write_json(self.raw_dir / "call_index.json", self.records)
            except OSError:
                pass
            raise
        record.update(
            {
                "completed_at": utc_now(),
                "attempt_state": "transport_result_persisted",
                "http_status": result.http_status,
                "elapsed_ms": result.elapsed_ms,
                "response_wire_sha256": (
                    sha256_bytes(response_bytes) if response_bytes else None
                ),
                "response_wire_bytes": len(response_bytes),
                "response_decoded_chars": len(result.raw_body),
                "transport_error": result.transport_error,
                "response_parse_error": result.response_parse_error,
                "response_headers": result.response_headers or {},
            }
        )
        write_json(metadata_path, record)
        write_json(self.raw_dir / "call_index.json", self.records)
        print(
            f"[{call_number:03d}] {label} -> "
            f"{result.http_status if result.http_status is not None else 'transport-error'}",
            flush=True,
        )
        return result, record
