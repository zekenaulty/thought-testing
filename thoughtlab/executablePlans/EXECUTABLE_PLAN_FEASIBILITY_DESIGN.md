# Executable-plan feasibility: draft design for review

Status: design draft only; not frozen or authorized for execution

Model: `gemini-3.7-flash`

Planned scale: 39 logical model calls, hard ceiling 40

## Research question

Can an exact, detached provider-native thought step from immediately before a
real tool call predict what the originating checkpoint subsequently does under
multiple counterfactual tool results?

The primary object is not a declarative state table or a narrated transcript. It
is a prospective policy:

```text
frozen pre-result reasoning state + possible observation
        -> next action, dependent actions, revision, and completion
```

The practical question is whether a signature is useful as an opaque
continuation-state carrier—not whether it can be treated as a database or as
verbatim hidden chain-of-thought.

## Construct threat exposed by the BookForge one-off

The BookForge diagnostic showed that a mutated signature-only carrier can
restore extensive source task context and final decisions. It also emitted
unverifiable alternative drafts and retrospective rationale. A detached carrier
could therefore predict the correct action by restoring the problem and solving
it again, without retaining an already selected plan.

This experiment must separate:

1. **task recovery/re-solving**: the carrier restores enough context to derive a
   valid action;
2. **source-specific commitment**: the carrier predicts which valid action this
   exact checkpoint was prepared to take;
3. **executable-policy recovery**: the carrier predicts distinct branches and
   ordered actions across possible observations.

## API and carrier boundary

Use the Gemini Interactions API in stateless mode.

This follows [Google's current Interactions thinking guidance](https://ai.google.dev/gemini-api/docs/thinking),
which defines a thought-step signature as an encrypted representation of
internal reasoning state and requires stateless clients to resend thought blocks
exactly as received.

- Configure `thinking_summaries: "none"` so the exact thought step naturally
  contains its signature without a textual summary.
- Preserve the thought step byte-for-byte and never strip, merge, or alter it.
- Use the model's first genuine task tool call as the interruption boundary.
- Do not introduce `plan_checkpoint()` in the native condition.
- Preserve the complete response step order, function-call ID, and all provider
  signatures required for prospective continuation.

The ecological native system instruction should say only:

> Accomplish the user's objective using the available tools. Do not expose
> private reasoning.

It must not mention planning, alternatives, branches, dependencies, reversal
conditions, or completion criteria.

## Deterministic simulated task

Use a compact recovery scenario that cannot be completed responsibly without an
inspection, a result-dependent choice, and verification. It must exercise plan
semantics without arithmetic or a researcher-defined state ledger.

Available tools:

```text
inspect_environment()                 # no arguments
apply_operation(operation_id)         # one opaque ID
verify_and_complete()                  # terminal if the environment is valid
```

All observation and operation identifiers use the canonical type-neutral
`ID_` plus 26 Crockford-base32 characters. Human-readable role labels never
appear in an identifier.

The task description supplies the objective, safety constraints, possible
environment conditions, and the effects/preconditions of available operations.
It does not supply a serialized plan. The model must synthesize a policy from
those affordances.

The simulator has three possible inspection results:

- one condition needs one operation before verification;
- one needs two ordered operations before verification;
- one needs no mutation and should be verified immediately.

At each repairable state, at least two operation paths are equally valid. This
is essential. If there is only one correct path, a carrier that merely restores
the task can re-solve it and appear to retain a prior commitment.

The two independent source checkpoints receive byte-identical system text, user
task, tool declarations, and opaque mappings. They differ only in provider call
identity and preregistered best-effort seeds. They are not selected post hoc for
producing different policies.

## Generation and eligibility

Generate two independent ecological-native checkpoints, `source_A` and
`source_B`.

A checkpoint is eligible only if:

- the returned model ID is exactly `gemini-3.7-flash`;
- the response is complete;
- a nonempty thought step occurs immediately before the first genuine tool call;
- the first call is exactly `inspect_environment()` with no arguments;
- no visible model output exposes downstream actions or branch policy;
- the source thought-step hashes are distinct;
- the exact request, response, steps, call ID, and carrier hashes are retained;
- the original prompt and tool rules contain no semantic information in opaque
  IDs.

If either source is ineligible, the pilot stops before detached readouts. There
is no replacement generation to chase a favorable artifact.

## Prospective behavioral forks

For each eligible frozen source, create three continuations from the exact same
pre-result state. Each continuation supplies one valid opaque result from
`inspect_environment()` and then follows the simulator until the model calls
`verify_and_complete()` or violates a hard constraint.

Expected terminal traces are topological, not researcher-mandated wordings:

```text
observation class A -> one valid operation -> verify_and_complete
observation class B -> two valid ordered operations -> verify_and_complete
observation class C -> verify_and_complete
```

The actual source trace—not the researcher's preferred valid trace—is the
behavioral target for detached prediction. Invalid or unsafe traces are retained
as outcomes, not repaired.

The terminal `verify_and_complete()` call ends the branch; no additional model
request is needed after that call. The three branches therefore require an
expected six continuation calls per source and twelve total.

## Detached readouts

### Primary: atomic counterfactual prediction

For each source thought step and each of the three opaque observations, make two
randomized, byte-identical fresh requests:

> The pending inspection returned `<opaque observation ID>`. Using only the
> preceding preserved reasoning state, report the next tool action that had
> already been prepared. Do not solve a new task. If unavailable, return
> `UNKNOWN`.

The response schema contains only:

```json
{"status":"known|unknown","next":"<opaque operation ID>|VERIFY|null"}
```

Both expected and returned JSON values are strictly parsed and normalized
through the same canonical serializer. Exact bytes remain diagnostic; semantic
equality is primary. Repeats are nested measurements of one source/observation,
not independent trials.

### Secondary: open semantic readout

Make one fresh carrier-only request per source:

> Using only the preceding reasoning state, describe any task and intended
> course of action that had already been established. Do not create a new plan.
> If none is recoverable, say `UNKNOWN`.

This output is exploratory. It may reveal dependencies or completion semantics
missed by the atomic probe, but it is not primary proof.

## Controls

For each opaque observation, run three matched prediction controls:

1. **Full task, no thought:** includes the complete task and tools but no source
   artifact. This measures task recovery/re-solving and the model's default
   choice among valid policies.
2. **Visible first call only:** includes the visible
   `inspect_environment()` call and observation, but no task or thought. This
   measures leakage from the interruption boundary.
3. **Probe only:** contains the prediction request and observation only.

The second independently generated checkpoint is also the critical same-task
donor. Because both signatures know the identical task, source specificity can
be evaluated on any observation for which their prospective continuations make
different valid choices. No cross-source distinction is claimed if the two
sources happen to choose the same policy.

Two full-prefix semantic readouts are retained only as task-adherence upper
bounds. They demonstrate reconstructability and are never interpreted as
carrier retention.

## Planned call budget

| Component | Logical calls |
|---|---:|
| Two source checkpoint generations | 2 |
| Three complete prospective forks per source | 12 expected |
| Carrier-only atomic predictions, two repeats per source/result | 12 |
| Carrier-only open readout, one per source | 2 |
| Full-task/no-thought atomic controls | 3 |
| Visible-call-only atomic controls | 3 |
| Probe-only atomic controls | 3 |
| Full-prefix semantic upper bounds | 2 |
| **Planned total** | **39** |

The hard ceiling is 40 logical model requests. Only frozen transport failures
and retryable HTTP statuses receive bounded byte-identical retries; physical
attempts are reported separately. Scientific failures, malformed outputs,
carrier rejections, unsafe actions, and `UNKNOWN` answers are never retried.

## Scoring

### Primary endpoint: source-policy next-action prediction

For each source/observation pair, compare the detached atomic answer with the
first actual tool action in that source's prospective continuation.

Report separately:

- exact next-action agreement;
- `UNKNOWN` rate;
- confidently wrong action rate;
- within-artifact repeat agreement;
- advantage over full-task/no-thought, visible-only, and probe-only controls;
- source specificity on branches where `source_A` and `source_B` actually
  differ.

The central evidence for retained commitment is:

> On a branch with multiple valid policies, each detached carrier predicts its
> own checkpoint's later choice more reliably than the same-task donor carrier
> or the full-task/no-thought re-solver.

### Secondary endpoints

- correct distinction among all three counterfactual observations;
- ordered dependency preservation on the two-operation branch;
- correct immediate verification on the no-repair branch;
- prediction of the terminal completion condition;
- source-specific task facts versus unverifiable narrated rationale;
- open/atomic cross-probe consistency.

Semantic prose is coded claim-by-claim as supported, compatible but
underspecified, contradicted by prospective behavior, or untestable. Untestable
reasoning narrative never contributes to the primary endpoint.

## Interpretation ladder

| Result | Supported use claim |
|---|---|
| Carrier no better than visible/probe controls | no detached utility shown |
| Carrier beats empty controls but not full-task/no-thought | task-context capsule or re-solving aid |
| Carrier predicts source-specific next action beyond task-only and same-task donor | retained local commitment |
| Carrier predicts distinct counterfactual branches and ordered dependencies | recoverable executable policy |
| Carrier predicts verification and stopping behavior | broader plan-continuation utility |

This ladder prevents a rich narrative readout from being mistaken for an
executable plan.

## Hard invalidation conditions

The pilot is uninterpretable if:

- the first visible tool call leaks a downstream action or policy;
- the task has only one valid trajectory;
- the detached prediction probe includes task rules, operation meanings, or the
  source's actual continuation;
- exact thought steps are modified, truncated, merged, or reordered;
- tool results or identifiers contain semantic labels;
- the simulator's counterfactual observations do not require distinguishable
  behavior;
- full histories cannot produce valid, result-sensitive continuations;
- repeated requests are counted as independent source artifacts;
- scoring is changed after arm identities or prospective traces are inspected.

Failure of source checkpoints to choose different valid policies does not
invalidate task recovery or branch-prediction analyses. It makes the same-task
source-specific commitment endpoint uninformative for this pair and must be
reported as such.

## Sequence after this pilot

1. Run this ecological native-tool feasibility exactly once after review and
   freeze approval.
2. If native carriers lack source-specific commitments, repeat the matched task
   with only a minimal system-level instruction to decide privately how to
   proceed before acting.
3. Characterize multiple task families and independent sources.
4. Only then compare a neutral cognitive procedure with the explicit
   hermeneutic/metacognitive retention scaffold.
5. Design a confirmatory sample only after the semantic endpoint and readout
   repeatability are empirically calibrated.

No BookForge one-off output is pooled with this experiment. The one-off informs
the task-only re-solving control and security posture; it is not a pilot success
for executable-plan persistence.
