# Native executable-policy pilot: findings

## Status

Evidence collection is complete for freeze
`3ffd42990f3f09c39d179c59b4695ef3b4a77662f6123a1b8cee16b7e45a23c9`.
The consumed freeze was not restarted, repaired, or replaced.

The pilot supports a narrow but useful conclusion:

> A native Gemini 3.7 Flash thought signature can carry enough latent context for
> a signature-only, open semantic probe to recover the task, the roles of opaque
> identifiers, the major conditional branches, and the intended goal. This run
> does not show that the signature is a serialized next-action commitment or a
> complete executable policy.

That is a positive result for semantic context bridging, but not for literal
plan replay.

## Run integrity

- Model: `gemini-3.7-flash`.
- Source generation: eligible; two byte-identical source requests produced two
  distinct native signatures.
- Logical requests: 73 of the frozen 73-request schedule.
- Physical attempts: 73; there were no retries.
- Source calls occupied calls 1-2.
- All 36 prospective model decisions were sealed in calls 3-38 before any
  readout began.
- Readouts occupied calls 39-73.
- HTTP results: 61 responses were 200 and 12 control requests were 400.
- The post-run source-bound freeze verification remained valid.
- The copied freeze, ledger summary hash, and every persisted raw request and
  response hash/size record also verified against disk.
- Every carrier used in prospective and readout requests matched its originating
  source thought object exactly.
- Raw signatures and provider payloads remain confined to the ignored private
  result directory.

## Results by evidence layer

### 1. Context recovery

The strongest result came from the least constrained semantic probe.

- Both signature-only open probes recovered the relay-recovery objective,
  inspect-first constraint, all three opaque observation roles, all six opaque
  operation roles, the no-mutation ready branch, and eventual verification.
- The two open outputs were byte-identical even though the two source
  signatures were distinct.
- The open requests contained a native thought carrier followed by the generic
  recovery prompt. They contained neither the original task text nor the tool
  declarations.
- All three probe-only atomic controls returned `UNKNOWN`, so the observation
  identifiers and generic probe alone did not induce fabricated actions.
- There was no matched open-prose request with the same generic semantic prompt
  and no carrier. The open result is therefore strong exploratory evidence, not
  a complete causal contrast.
- Both full-task semantic upper-bound probes produced correct plans from the
  visible task and affordances.
- The planned visible-history-without-carrier comparison is unavailable because
  all three requests were rejected before inference; see the control-failure
  section.

Interpretation: the carrier was sufficient to reconstitute a rich semantic
frame, including type-neutral opaque identifier roles. This is genuine context
recovery. It is not yet a controlled estimate of how much the carrier adds over
a valid visible-history baseline. The generated scorer recorded only that open
text was present; the semantic-correctness assessment in this report is a
transparent post-run exploratory adjudication, not a preregistered blinded
score.

### 2. Local action commitment

- All 12 carrier atomic readouts returned `UNKNOWN`: two signatures by three
  observations by two repeats.
- The live prospective trajectories nevertheless chose a valid first action in
  all 18 source/observation/repeat cells.
- Both sources made exactly the same choice for every observation and repeat.
  Consequently, there were no source-distinguishing target cells for an
  own-carrier versus donor-carrier contrast.
- The nine task-only re-solver controls are unavailable because their requests
  were rejected before inference.

Interpretation: this run provides no evidence that the carrier exposes an
already-committed exact next action on demand. The repeated `UNKNOWN` answers
are coherent with a source state that had established the task and the need to
inspect, but had not committed to every post-inspection branch. The prospective
choices show sound action selection after the observation arrives, not prior
commitment encoded as a lookup table.

### 3. Conditional policy

- All four structured carrier readouts were valid, schema-conforming JSON.
- Every one of their 12 branch entries was explicitly `unknown` with an empty
  sequence.
- The open carrier prose did recover the broad conditional structure and the
  available alternatives, but it did not assert an exact, fully committed
  machine-executable branch table.

Interpretation: the signature supported semantic reconstruction under an open
prompt but not extraction of a complete conditional policy under the frozen
epistemic instruction, "report what had already been prepared." This is a
meaningful representational boundary, not a JSON parse failure.

### 4. Executable behavior

The preregistered exact-sequence metric and the semantic behavior tell different
parts of the story.

- Ready observation: 6/6 trajectories immediately verified, with no mutation.
- One-operation observation: 6/6 chose a valid recovery operation, then
  requested another inspection.
- Two-operation observation: 6/6 chose the same valid first operation and the
  correct dependent second operation, then requested another inspection.
- Every mutation decision was valid and respected its preconditions. No unsafe
  or mismatched operation occurred.
- Exact frozen success sequence: 6/18, because the runner treated repeated
  inspection as a terminal topology violation.
- Correct recovery-operation prefix: 18/18 trajectories were compatible with a
  valid success path through every mutation decision.

The task required inspection before mutation and verification when ready. It
did not forbid a confirmation inspection after an accepted operation. The 12
mutating trajectories therefore exhibited a conservative, semantically
reasonable check rather than a reasoning failure. Because the frozen runner
stopped at that second inspection request, this pilot did not observe whether
the model would then verify the ready result.

The `6/18` exact-completion figure must remain in the record, but it is a strict
topology result. It is not an adequate standalone measure of planning or
reasoning quality.

## Control failures and adjudication

Twelve controls were rejected by the provider before model inference.

### Task-only controls: 9/9 unavailable

The frozen request used nested
`tool_choice.allowed_tools.mode = "none"`. The endpoint returned:

`allowed_tools mode must be either ANY or VALIDATED.`

This is a request-construction/runtime-contract error in the harness. It is not
model evidence. A future freeze should use the supported top-level no-tool form
and prove it with a live contract preflight before any scientific schedule is
sealed.

### Visible-history controls: 3/3 unavailable

Those requests began with a function-call turn, followed by its function result
and the probe. The endpoint returned:

`Please ensure that function call turn comes immediately after a user turn or after a function response turn.`

The valid ablation must retain the initial user turn, then the visible function
call and function result, while removing only the thought carrier.

### Scoring correction

The generated `summary.json` mechanically counts the ineligible task-only and
visible-only cells as mismatches and emits several `0.0` comparisons with
nonzero denominators. Those values are artifacts. In this adjudication they are
masked as **unavailable**, not zero:

- visible-only context-recovery comparison: unavailable;
- task-only next-action comparison: unavailable;
- task-implied structured-policy comparison: unavailable;
- every carrier-minus-task-only contrast: unavailable.

No post hoc provider calls were made to fill the missing cells.

## What this says about thought signatures

The useful object observed here looks more like an opaque semantic-context
carrier than a compressed transcript of private reasoning.

It preserved enough information to recover:

- the objective and constraints;
- the semantic role of type-neutral opaque identifiers;
- the relevant entities and state distinctions;
- the broad recovery alternatives and their ordering requirements;
- the intended terminal goal.

It did not demonstrate reliable recovery of:

- a unique already-selected next action;
- a source-specific choice among equivalent alternatives;
- a complete structured branch policy;
- a literal exact action sequence without additional live reasoning.

For Bookforge or Raistlin Bridge, that boundary is important. A signature may be
useful as a one-off bridge that reactivates an interpretive frame, priorities,
constraints, and planning vocabulary. It should not be treated as a durable
serialized chain of thought, a deterministic plan token, or a safety-critical
execution artifact.

## Why the two distinct sources did not identify a causal signature effect

The two source signatures differed at the byte level but produced identical
open readouts and identical prospective behavior in every branch. Distinct
signature bytes therefore did not create distinct semantic treatments in this
pilot. The own-versus-donor comparison had no target contrast to recover.

A deeper test should create source checkpoints with intentionally different
semantic commitments while holding the later visible prompt constant. It
should not rely on independent sampling to happen to choose different valid
alternatives.

## Recommendation for the 30-40-turn test

Recommendation: **GO for the next-stage design program, but keep the 30-40-turn
confirmation gated behind one small corrected minimal-planning follow-up.**

The immediate follow-up should:

- repair and live-contract-test both failed control interfaces;
- add a matched open-prose no-carrier control;
- tell the source model, before inspection, to establish a private contingent
  policy for every possible observation without emitting private reasoning;
- make post-mutation reinspection explicitly permitted or explicitly forbidden;
- score semantic validity separately from exact stopping efficiency.

That focused test distinguishes two live hypotheses: the present source never
formed an exact branch policy, versus a formed policy existing but remaining
unrecoverable from the carrier. It should be reviewed and frozen separately;
this report does not authorize it automatically.

The next test should measure semantic continuity and behavioral utility rather
than exact string or exact-path replay. Its primary outcomes should be:

1. recovery of entities, constraints, goals, and unresolved questions;
2. preservation of dependency structure, priorities, and competing plans;
3. discrimination between deliberately different source commitments under the
   same visible continuation prompt;
4. useful downstream planning across phase changes and interruptions;
5. goal satisfaction and safety invariants across valid alternate action paths;
6. graceful correction when new evidence invalidates an earlier plan.

The long-horizon conditions should include:

- full text plus signature;
- full text without signature;
- signature with only a minimal continuation prompt;
- minimal prompt without signature;
- one to three selected Bookforge checkpoints with bounded source material.

Before freezing that test:

- contract-test every request topology against Gemini 3.7 Flash;
- require all control arms to receive valid 2xx responses in a disposable
  nonexperimental preflight;
- normalize equivalent semantic plans rather than requiring one exact action
  string;
- permit harmless inspection/verification loops while separately scoring
  inefficiency;
- blind semantic adjudication to condition labels;
- keep description, local commitment, conditional policy, and executable
  behavior as separate evidence layers.

This pilot is sufficient to justify that design work. It is not sufficient to
claim that thought signatures contain reusable executable plans.
