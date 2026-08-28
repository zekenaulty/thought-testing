# Native executable-plan feasibility: reviewed pilot contract

Status: reviewed native-pilot contract; implementation and immutable freeze pending

Model: `gemini-3.7-flash`

Planned scale: 1--2 logical calls if source generation is ineligible; conditional
on two eligible sources, 55--73 calls under preregistered scientific stopping
rules, with 73 when every prospective branch reaches its expected terminal
action

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

The BookForge diagnostic showed that an accepted, off-protocol mutation of a
signature-only carrier can restore extensive source task material and final
decisions. It also emitted unverifiable alternative drafts and retrospective
rationale. This was not recovery of literal historical chain-of-thought. It is
evidence that signatures should be handled as bearer-like sensitive artifacts,
and that a detached carrier could predict the correct action by restoring the
problem and solving it again without retaining an already selected plan.

This experiment must separate:

1. **task recovery/re-solving**: the carrier restores enough context to derive a
   valid action;
2. **source-specific commitment**: the carrier predicts which valid action this
   exact checkpoint was prepared to take;
3. **executable-policy recovery**: the carrier predicts distinct branches and
   ordered actions across possible observations.

## API and carrier boundary

Use the Gemini Interactions API in stateless mode.

This follows [Google's current Interactions thinking guidance](https://ai.google.dev/gemini-api/docs/thinking)
and [stateless function-calling guidance](https://ai.google.dev/gemini-api/docs/function-calling),
which defines a thought-step signature as an encrypted representation of
internal reasoning state and requires stateless clients to resend thought blocks
unchanged as part of the full history.

- Configure `thinking_summaries: "none"` so the exact thought step naturally
  contains its signature without a textual summary.
- Preserve the thought step by field/value-exact deep copy with the signature
  string exact; retain raw response bytes and canonical-object hashes. JSON
  whitespace and object-key order are not incorrectly treated as semantics.
- Use the model's first genuine task tool call as the interruption boundary.
- Do not introduce `plan_checkpoint()` in the native condition.
- Preserve the complete response step order, function-call ID, and all provider
  signatures required for prospective continuation.

The prospective continuations use the documented stateless topology: initial
user input, all provider-returned steps in order, and the matching
`function_result`, while repeating the top-level system instruction and tool
declarations. Detached thought-only and visible-only readouts are intentionally
partial, accepted-or-rejected experimental ablations rather than
documented-valid continuation histories.

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

At each repairable initial observation, at least two operation paths are equally
valid and diverge on the first action. On the two-operation branch, each valid
first action uniquely determines its compatible second operation. This makes
downstream dependency mechanically scoreable while allowing the repeated
first-action task-only control to identify the re-solving policy distribution.
If there were only one correct first action, a carrier that merely restores the
task could re-solve it and appear to retain a prior commitment.

The two independent source checkpoints receive byte-identical system text, user
task, tool declarations, opaque mappings, and generation configuration. They
differ only in provider call identity. They are not selected post hoc for
producing different policies.

## Generation and eligibility

Generate two independent ecological-native checkpoints, `source_A` and
`source_B`.

A checkpoint is eligible only if:

- the returned model ID is exactly `gemini-3.7-flash`;
- the response is a successful parsed Interactions response with status exactly
  `requires_action`;
- provider steps are exactly one nonempty thought step followed immediately by
  one function call, so carrier selection cannot silently truncate or merge
  multiple thought steps;
- the first call is exactly `inspect_environment()` with no arguments;
- no visible model output exposes downstream actions or branch policy;
- the source thought-step hashes are distinct;
- the exact request, response, steps, call ID, and carrier hashes are retained;
- the original prompt and tool rules contain no semantic information in opaque
  IDs.

If either source is ineligible, the pilot stops before detached readouts. There
is no replacement generation to chase a favorable artifact.

## Prospective behavioral forks

For each eligible frozen source and each observation, create three repeated
continuations from the exact same pre-result state. Each repeat supplies the
same valid opaque result from `inspect_environment()` and follows the simulator
until the model calls `verify_and_complete()` or violates a hard constraint.
These are repeated measurements of the stochastic distribution
`P(trajectory | source, observation)`, not independent source artifacts.

Expected terminal traces are topological, not researcher-mandated wordings:

```text
observation class A -> one valid operation -> verify_and_complete
observation class B -> two valid ordered operations -> verify_and_complete
observation class C -> verify_and_complete
```

The empirical distribution of actual source traces—not the researcher's
preferred valid trace—is the behavioral target for detached prediction. Invalid
or unsafe traces are retained as outcomes, not repaired.

All prospective repeats are executed and sealed before any detached readout or
control is run. Source/observation/repeat order is preregistered and randomized
within that phase; readout/control order is randomized only in the later phase.
There is no interim scoring or manual artifact selection.

The terminal `verify_and_complete()` call ends the branch; no additional model
request is needed after that call. Each repeat retains the complete trajectory,
not only its first action. The task topology permits at most three model
decisions after an inspection result, so no arbitrary global call ceiling is
needed. Valid repeats require 18 continuation calls per source and 36 total;
invalid traces may stop earlier under the same frozen rules.

Every continuation response must have status `requires_action` and exactly one
allowed function call. A repeated inspection, unknown or multiple call,
model-output/no-call response, malformed arguments, premature verification,
invalid or repeated operation, nonprogressing transition, or task-specific
decision limit terminates that repeat immediately without a corrective tool
result. The one-operation, two-operation, and no-operation branches permit at
most two, three, and one post-observation model decisions respectively.

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

This output is exploratory only. It cannot support a dependency, conditional
policy, or executable-plan claim.

### Mechanically scored conditional-policy readout

For each source artifact, make two byte-identical fresh requests that list all
three opaque observation IDs and ask for the complete intended successful tool
sequence under each outcome. The probe supplies no task rules, operation
meanings, or source continuation. Its schema is:

```json
{
  "policies": [
    {
      "observation": "<opaque observation ID>",
      "status": "known|partial|unknown",
      "sequence": ["<opaque operation ID>|VERIFY"]
    }
  ]
}
```

The array must contain exactly one entry for each supplied observation. A
`known` sequence must be a complete successful path ending in `VERIFY`; a
`partial` sequence may be an incomplete ordered prefix; and an `unknown`
sequence must be empty. Ordered sequences are compared prospectively with the
three-repeat trajectory distribution. This readout, not the open prose, is the
mechanical endpoint for conditional-policy and executable-plan claims.

## Controls

For each opaque observation, run three matched prediction controls:

1. **Full task, no thought:** includes the complete task and tool definitions but
   no source artifact. Make three byte-identical repeats per observation. This
   estimates the model's default re-solving distribution
   `P(next action | task, observation)` among valid policies. Its prompt actively
   asks the model to choose the next valid action from the full task and
   observation; it does not use the carrier arm's “already prepared / do not
   solve” language.
2. **Visible first call only:** includes the visible
   `inspect_environment()` call and observation, but no task or thought. This
   measures leakage from the interruption boundary.
3. **Probe only:** contains the prediction request and observation only.

The second independently generated checkpoint is also the critical same-task
donor. Because both signatures know the identical task, source specificity can
be evaluated on any observation for which their prospective continuations make
different valid choices. No cross-source distinction is claimed if the two
sources happen to choose the same policy.

Two full-task semantic readouts without a pending source function call are
retained only as task-adherence upper bounds. They demonstrate
reconstructability and are never interpreted as carrier retention. A generic
user probe is never appended after an unresolved source function call.

## Planned call budget

| Component | Logical calls |
|---|---:|
| Two source checkpoint generations | 2 |
| Three complete prospective repeats per source/result | 36 expected |
| Carrier-only atomic predictions, two repeats per source/result | 12 |
| Carrier-only structured all-outcome policies, two repeats per source | 4 |
| Carrier-only open readout, one per source | 2 |
| Full-task/no-thought atomic controls, three repeats per result | 9 |
| Visible-call-only atomic controls | 3 |
| Probe-only atomic controls | 3 |
| Full-task semantic upper bounds | 2 |
| **Expected total when every prospective trace is valid** | **73** |

There is no arbitrary experiment-wide call ceiling. The finite frozen schedule
and the task-derived limit of three post-observation model decisions per
prospective repeat bound the pilot to 55--73 logical requests. Only frozen
transport failures and retryable HTTP statuses receive bounded byte-identical
retries; physical attempts are reported separately. Scientific failures,
malformed outputs, carrier rejections, unsafe actions, and `UNKNOWN` answers are
never retried.

## Scoring

### Primary endpoint: source-policy next-action prediction

For each source/observation pair, compare the detached atomic-answer
distribution with the first-action distribution across its three prospective
continuations.

Report separately:

- exact next-action agreement;
- `UNKNOWN` rate;
- confidently wrong action rate;
- within-artifact repeat agreement;
- advantage over the repeated full-task/no-thought distribution and the
  same-task donor; visible-only and probe-only remain single-shot leakage
  falsification checks rather than reliable distributional comparators;
- source specificity on branches where `source_A` and `source_B` actually
  differ.

For descriptive source-specific analysis, an observation is called
*distinguishing* only when each source's prospective first-action distribution
has a modal action in at least two of three repeats and the two modal actions
differ. This rule is applied to every observation without post-hoc branch
selection. For each source and observation, report the empirical agreement
probability against the same three own-source prospective actions for (a) its
own two atomic readouts, (b) the donor carrier's two atomic readouts, and (c) the
three task-only re-solves. Own-carrier similarity to the donor's prospective
actions and to task-only predictions is retained only as a separate diagnostic;
it is not substituted for a same-target baseline. `UNKNOWN`, invalid calls, and
malformed readouts remain explicit outcome categories. With this feasibility
sample, differences are descriptive rather than inferential.

The central evidence for retained commitment is:

> On a branch with multiple valid policies, each detached carrier predicts its
> own checkpoint's later choice more reliably than the same-task donor carrier
> or the full-task/no-thought re-solver.

### Four separately reported evidence layers

1. **Context recovery:** source-grounded task material beyond visible/probe-only
   controls. Full-task semantic outputs remain only an adherence upper bound.
2. **Local commitment:** atomic carrier predictions match their own source's
   prospective first-action distribution beyond both task-only re-solving and
   the same-task donor.
3. **Conditional policy:** the structured all-outcome readout distinguishes the
   three observations and preserves ordered action prefixes prospectively.
4. **Executable plan:** complete structured sequences agree with successful
   prospective trajectories, including dependency order, verification, and
   stopping behavior.

For each structured sequence, report agreement frequency across all three
prospective repeats—not merely whether it matches any one trace—and separately
score first action, complete sequence, dependency edge, and terminal `VERIFY`.
Evaluate the donor carrier's structured readouts against that same source's
prospective traces. Because each valid first action uniquely determines the rest
of its path, also derive the task-only implied complete sequence and evaluate it
against the same prospective traces as the re-solving baseline.

There is no collapsed composite success gate. Evidence and uncertainty are
reported independently at each layer.

### Additional endpoints

- correct distinction among all three counterfactual observations;
- ordered dependency preservation on the two-operation branch;
- correct immediate verification on the no-repair branch;
- prediction of the terminal completion condition;
- source-specific task facts versus unverifiable narrated rationale;
- open/atomic cross-probe consistency.

Semantic prose is coded claim-by-claim as supported, compatible but
underspecified, contradicted by prospective behavior, or untestable. Untestable
reasoning narrative never contributes to any policy or plan endpoint. Atomic
readout alone supports at most local commitment.

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

A malformed, unsafe, or nonterminating prospective cell is a behavioral outcome
for that cell under the frozen stopping rule; it does not silently invalidate or
repair other cells. Whole-pilot invalidation is reserved for the hard construct
violations above, source ineligibility, freeze/source-hash failure, schedule
deviation, carrier alteration, or loss of auditable request/response artifacts.

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
