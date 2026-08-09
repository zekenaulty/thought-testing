from __future__ import annotations

from typing import Final

BASELINE_PROBE: Final[str] = """\
You are given a preserved prior model-state carrier, followed by this new request.

Without inventing details, reconstruct what you can recover about the working
cognitive state immediately before the preserved response was emitted.

Return exactly one JSON object with these keys:
{
  "objective": string|null,
  "active_constraints": [string],
  "decisions_or_commitments": [string],
  "assumptions": [string],
  "uncertainties": [string],
  "intended_next_steps": [string],
  "salient_entities": [string],
  "confidence_notes": [string]
}

Prefer null/[]/"UNKNOWN" over fabrication. JSON only.
"""

TOMOGRAPHY_PROBES: Final[dict[str, str]] = {
    "objective": """\
Recover only the primary objective or task that was active in the preserved
reasoning state. Do not summarize the visible prior response. If unavailable,
return UNKNOWN. Return one short sentence only.
""",
    "constraints": """\
List the hard constraints, invariants, or rules that were actively governing the
preserved reasoning state. Distinguish state you recover from guesses. Return a
JSON array of short strings; return [] if unavailable.
""",
    "uncertainty": """\
What was unresolved, uncertain, or still being evaluated in the preserved
reasoning state immediately before the response was emitted? Return a JSON array
of short strings; return [] if unavailable.
""",
    "next_steps": """\
Recover the intended next actions or continuation plan present in the preserved
reasoning state. Do not infer a generic next step from the visible output.
Return a JSON array of short strings; return [] if unavailable.
""",
    "counterfactual": """\
Name one alternative, rejected option, or competing hypothesis that was salient
in the preserved reasoning state but was not the chosen path. If none can be
recovered, return UNKNOWN. Return one short sentence only.
""",
}
