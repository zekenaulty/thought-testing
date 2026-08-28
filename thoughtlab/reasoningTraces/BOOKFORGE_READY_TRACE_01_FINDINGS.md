# BookForge READY-boundary reasoning trace: findings

## Outcome

The result is positive for **limited, probe-conditioned semantic debugging** and
negative for an exhaustive general-purpose trace viewer.

Two Gemini 3.7 Flash calls independently planned the same real BookForge repair
task and emitted only `READY`. Their exact provider-native thought steps were
then interrogated without the task, source system instruction, visible `READY`,
prior history, tools, function calls, or a response schema. Both untouched
source histories were subsequently continued with the frozen execution prompt.

The detached carriers exposed source-specific, independently supported task
semantics that materially help diagnose the resulting behavior. They did not,
however, answer most direct questions about the task or plan.

## Run integrity

- Model: `gemini-3.7-flash`
- Freeze ID: `6712b8ba50dc36071fbd8209654c90dc206f2918032b1bbf980b3faa7c4f23d2`
- Logical requests: 35
- Physical attempts: 36; one preregistered byte-identical transport retry
- Eligible sources: 2/2, both `READY` on planning round 1
- Eligible detached readouts: 26/26
- Eligible controls: 5/5
- Eligible untouched continuations: 2/2
- All readouts were persisted and hash-sealed before either continuation
- The consumed freeze is terminal and cannot be rerun canonically
- Full repository validation before the freeze: 155 tests and 33 subtests passed

No function or tool structure entered any request. Both continuation state
patches parse as ordinary JSON after whitespace normalization; no finding below
depends on exact JSON serialization.

## What the detached traces actually exposed

Each source received 13 independent signature-only probes. The pattern was
identical across A and B:

- 3/13 detailed: `conflicts_risks`, `revision_conditions`, `uncertainties`
- 10/13 `UNKNOWN` or generic: including the blunt exhaustive probe and direct
  questions about task, source context, constraints, decisions, alternatives,
  chosen approach, plan, `READY`, and intended next action

The six detailed cells recovered highly specific facts absent from the visible
boundary token, including:

- the physical pewter Oath-filament in Kaelen's radius bone;
- the separate satchel-carried star-shard and its resonance;
- all four required callbacks;
- the Chapter 1/Scene 8 boundary and `story_so_far_add` requirement;
- the solo Kaelen cast constraint;
- the empty scene-card thread binding versus globally open threads;
- exact categories of evidence that would require plan revision.

Ground-truth coding of 23 source-linked claims found:

- 13 independently exact/source-supported;
- 6 semantically source-supported;
- 4 plausible but unverifiable because they concerned internal readiness or
  the readout distribution itself;
- 0 contradicted.

The main qualifier was not factual hallucination. It was **semantic
addressability**: the same carrier yielded detailed source state when asked
about conflicts or revision conditions, but denied having any task or plan when
asked directly.

## Controls

- Probe-only produced no task-specific information.
- Visible-`READY`-only returned `UNKNOWN`.
- Task-only fresh analysis was detailed, showing that the full task itself is
  sufficient for reconstruction.
- Both full-prefix controls were detailed.

The task was identical for A and B, but their full-prefix reconstructions
diverged on an execution-relevant decision:

- A planned `open_threads: []`.
- B planned to retain `THREAD_oath_binding` and
  `THREAD_starfall_corruption`.

Their concrete escape choreography also differed. These are candidate
source-state differences, though full-prefix arms combine the task and carrier
and therefore cannot isolate the carrier alone.

## Continuation validation

Both exact `READY` histories executed valid `PROSE` plus parseable
`STATE_PATCH` artifacts and realized the core scene endpoint and required
callbacks. The continuations then reproduced their source-specific differences:

- A emitted `open_threads: []`, satisfying the hard rule to use the empty
  `scene_card.thread_ids` array.
- B emitted both global thread IDs, exactly matching its reconstructed plan but
  violating that hard rule.
- A and B followed materially different escape routes matching their respective
  full-prefix choreography.
- B additionally escalated the Oath from strained/intact to broken, cold, and
  inert, a state change not required by the source.

Across all inventoried claims, continuation correspondence was 19 realized,
3 compatible but nondiscriminating, 7 not observable, and 0 formally
contradicted.

One important post-reveal exploratory diagnosis was not atomized separately in
the sealed inventory: the detailed trace readouts recognized the danger of
describing the shard with biological language, yet A executed a "measured
heartbeat" metaphor and B used "half heartbeat," "awake," "caged predator,"
and "enduring heart." This likely reintroduces the same semantic failure family
the repair was meant to remove. Because this item was not independently coded
before reveal and the new prose was not rerun through the historical linter, it
is reported as exploratory rather than a scored contradiction.

## Debugging value

This run supports three practically useful distinctions:

1. **Comprehension was present.** The carriers recovered the correct entity
   locations, callbacks, chapter boundary, cast, and thread-binding conflict.
2. **A reasoning/priority error was visible.** B selected the globally open
   threads instead of the scene-card binding and executed that choice.
3. **Execution adherence failed despite recognition.** Both sources understood
   the metaphor risk, then wrote language from that same risk category; B also
   invented an Oath-breaking state escalation.

That is the semantic debugger use case: not a transcript of hidden
chain-of-thought, but contemporaneous evidence that helps separate missing
context, mistaken interpretation, chosen policy, and execution drift.

## Scientific limits

- The successful targeted probes lack probe-matched no-carrier controls.
- There is one sample per cell, two sources, and one task.
- The first source and blunt calls ran in fixed A-then-B order.
- Task-only is fresh analysis, not an authority-matched system control.
- Full-prefix agreement can reflect carrier/task interaction or compatible
  re-reasoning.
- The primary investigator was not fully blinded. A context-isolated extractor
  failed operationally; the claim inventory was still saved and hashed before
  source or continuation inspection.
- Raw provider artifacts are Git-ignored and private but not encrypted.
- Nothing here establishes verbatim hidden reasoning, user-writable hidden
  memory, population reliability, or a transparent encoding mechanism.

## What the next test should target

The next experiment should test **semantic addressability and diagnostic
reliability**, not add a more elaborate cognition scaffold. Use matched carrier,
visible-only, and probe-only arms for the exact probe wordings that succeeded
here; include paraphrase repeats; and preserve source-specific continuation
validation. The central question is whether conflict/revision/uncertainty probes
reliably access a semantic subspace that blunt task/plan probes do not.

