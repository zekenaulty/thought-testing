from pathlib import Path

from thoughtlab.historicalTests.bookforge_blunt_probe import (
    ARM_NAMES,
    BLUNT_PROBE,
    arm_part,
    build_schedule,
    request_body,
    sanitized_response,
)
from thoughtlab.historicalTests.capsule import find_signature


def signed_text_part() -> dict:
    return {"text": "visible plan", "thoughtSignature": "secret-signature"}


def test_three_arms_have_intended_information_surfaces() -> None:
    signed = signed_text_part()

    full = arm_part(signed, "full_text_signature")
    text = arm_part(signed, "full_text_only")
    signature = arm_part(signed, "signature_only")

    assert full == signed
    assert full is not signed
    assert text == {"text": "visible plan"}
    assert signature["text"] == ""
    assert find_signature(signature) == ("thoughtSignature", "secret-signature")


def test_request_with_carrier_withholds_original_prompt() -> None:
    body = request_body(historical_part=signed_text_part(), max_output_tokens=1234)

    assert [item["role"] for item in body["contents"]] == ["user", "model", "user"]
    assert body["contents"][-1]["parts"][0]["text"] == BLUNT_PROBE
    assert body["generationConfig"]["maxOutputTokens"] == 1234
    assert "BookForge System Prompt" not in str(body)


def test_schedule_runs_calibration_before_randomized_remainder() -> None:
    paths = [Path("calibration.json"), Path("large.json"), Path("plan.json")]
    schedule = build_schedule(paths, seed=7)

    assert schedule[:4] == [
        (paths[0], "full_text_signature"),
        (paths[0], "signature_only"),
        (paths[0], "full_text_only"),
        (None, "probe_only"),
    ]
    assert len(schedule) == 1 + len(paths) * len(ARM_NAMES)
    assert set(schedule[4:]) == {
        (path, arm) for path in paths[1:] for arm in ARM_NAMES
    }


def test_sanitized_response_excludes_provider_thought_parts() -> None:
    payload = {
        "modelVersion": "gemini-3.7-flash",
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {
                    "parts": [
                        {"thought": True, "text": "private generated thought"},
                        {"text": "visible readout"},
                    ]
                },
            }
        ],
    }

    result = sanitized_response(
        status=200,
        payload=payload,
        raw_response_sha256="a" * 64,
    )

    assert result["visible_text"] == "visible readout"
    assert "private generated thought" not in str(result)
