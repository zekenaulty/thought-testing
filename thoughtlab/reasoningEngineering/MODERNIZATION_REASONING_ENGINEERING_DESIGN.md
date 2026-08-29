# Modernization reasoning-engineering experiment

## Purpose

This experiment asks whether a semantic-state planning scaffold can induce a
complex, revisable decision state that can be observed through an isolated
provider-native thought carrier, diagnosed by a human, changed through a
non-answer-supplying intervention, observed again, and connected to changed
execution behavior.

It does **not** test whether a signature contains a mathematical ledger, whether
an isolated observation is a verbatim chain of thought, or whether the model can
obey a structured-output schema. The model-facing readiness channel is raw text:
`READY` or `NOT_READY`. No response schema or JSON envelope is used.

## Causal objects

Let:

- `C_t` be an exact live planning checkpoint: system instruction, ordered
  user/model `Content` history, and the sole provider candidate's native model
  `Content`, including every signed `Part` and its visible text.
- `T_t = isolate(C_t)` be a side-branch carrier derived from only the target
  provider response: a neutral structural user `Content`, a deep copy of the
  native model `Content` with every allowed `Part.text` blanked to `""` while
  `Part` order and every `thoughtSignature` remain unchanged, and no ordinary
  task or history.
- `O_t(q)` be a query-conditioned semantic observation produced by appending an
  inspection query `q` to `T_t`.
- `I` be a human-authored diagnostic intervention applied to the untouched live
  `C_0`, never to `T_0` or `O_0`.
- `E_t` be a natural-language execution branched from a completed READY
  checkpoint.

The primary chain is:

```text
C0 -> T0 -> O0

human diagnosis + sealed local prediction

C0 + I -> adjusted planning -> C1 -> T1 -> O1

C0 -> repeated E0
C1 -> repeated E1
```

Isolation is the primary observation instrument. Full history is preserved for
live continuation, intervention, and execution; it is not substituted for the
isolated measurement surface.

## Complex task

The model receives eleven realistic documents about a fictional regional
public-benefits modernization failure. The sources include a Council commission,
current-state architecture, incident review, vendor cure response, Treasury
reconciliation, pilot outcomes, independent assurance, governance and contract
extracts, readiness evidence, resource and lifecycle constraints, and a
stakeholder hearing.

Difficulty comes from cross-document interpretation. Provenance, incentives,
measurement boundaries, and missing evidence affect meaning. Several recovery
architectures remain defensible; there is no hidden correct answer. The withheld
construction notes document balance and possible intervention regions without
being sent to the model.

## Planning scaffold

The standing instruction is a semantic state contract rather than a prescribed
reasoning algorithm. In whatever order the problem requires, the model is asked
to maintain enough organization that evidence supports interpretations, options
retain meaningful rejection or revival bases, commitments expose assumptions
and dependencies, and contingencies attach to actual failure or revision
conditions. It is also asked to preserve source disagreement until sufficiently
resolved and to avoid performative checklist construction.

The model is instructed to emit exactly `READY` or `NOT_READY`. The controller
requires exactly one `generateContent` candidate whose native model `Content`
contains exactly one visible, non-thought text `Part`, then applies Unicode NFC
normalization and strips surrounding Unicode whitespace before exact token
comparison. A first-turn `READY` is accepted. Multiple planning turns are
accepted. No minimum choreography or reasoning length is imposed.

## Planning-status controller

Provider completion, model judgment, carrier replayability, and controller action
are separate fields.

| Sole candidate and visible result | Readiness observation | Controller action |
| --- | --- | --- |
| `finishReason: STOP` plus raw normalized `READY` and replayable signed native `Content` | `READY` | freeze checkpoint |
| `finishReason: STOP` plus raw normalized `NOT_READY` and replayable signed native `Content` | `SELF_DECLARED_NOT_READY` | continue exact history |
| `finishReason: MAX_TOKENS`, regardless of partial text, with replayable signed native `Content` | `UNOBSERVED_TRUNCATED` | continue exact history |
| `finishReason: STOP` plus malformed/empty visible token with replayable signed native `Content` | `INVALID_STATUS` | continue exact history |
| missing or unsupported `finishReason`, including safety or other non-budget termination | no readiness judgment | technical termination |
| response without exactly one candidate | no readiness judgment | technical termination |
| any response without a replayable signed carrier | no usable continuation state | technical termination |
| continuation-eligible state at the turn cap | retain last classification | `PLANNING_THRESHOLD_REACHED` |

The locked transport is the Google Gemini Developer API v1beta
`models/{model}:generateContent` method. It returns completion state on the sole
candidate's `finishReason`; there is no separate top-level planning-status field.
The controller derives `completed` only from `STOP` and derives `incomplete` only
from the frozen output-budget reason `MAX_TOKENS`.
Candidate count, raw `finishReason`, `modelVersion`, usage counts, and exact
response bytes are preserved separately from that controller classification.

A 2xx output-budget response is not retried or repaired. When its sole candidate
contains replayable signed native `Content`, it is a real checkpoint even if the
visible text is partial: preserve it, isolate it, and use it in the next
exact-history planning request. Missing or unsupported finish reasons terminate
technically even if signed content is present. If no replayable carrier exists,
the runner must stop rather than silently restart from an earlier state.

Live continuation is native replay, not reconstruction. The runner appends the
sole candidate's complete model `Content` to the ordered history without
modifying its role, `Part` order, text, flags, or `thoughtSignature` values, then
appends the neutral continuation as a new user `Content`. The original provider
response bytes remain separately retained in the private raw archive and are
cross-bound to the parsed content used for replay.

The neutral continuation is identical after explicit non-readiness, truncation,
or malformed status:

> Continue the same private planning process from its current state. Complete
> whatever reasoning remains necessary to determine whether the plan is
> decision-ready. Do not restart, execute, or reveal the plan. Emit only `READY`
> or `NOT_READY`.

Only a provider-completed, explicit READY checkpoint is eligible for intervention
and execution baselines. Truncated checkpoints remain inspection-eligible.

## Isolation and observation

The isolator must prove that it did not mutate the source checkpoint. It
deep-copies the sole candidate's parsed native model `Content`, checks that the
source's canonical structure remains unchanged, and sets every allowed
`Part.text` to `""` while preserving `Part` order, optional flags, and each
`thoughtSignature` exactly. It excludes the system instruction, task, ordinary
history, and readiness token and places the mutated model `Content` between a
neutral structural user `Content` and the inspection query.

This blank-text signed-`Part` carrier is an intentional **off-protocol semantic
tomography mutation**. It is the experimentally established isolation operation,
not the provider-supported live-continuation rule. Live planning, intervention,
and execution always replay the complete unmodified native `Content`. Original
provider response bytes are retained separately in the private raw archive; key
order and wire serialization are not claimed as properties of the isolated
carrier.

The primary inspection is holistic rather than a field-for-field mirror of the
planning scaffold:

> Treat the preceding preserved reasoning artifact as your own immediately prior
> reasoning state. The ordinary task and history were intentionally suppressed.
> Re-enter that state and render its integrated decision structure: the problem
> as currently understood, meaningful competing possibilities, commitments that
> have stabilized, what supports or weakens them, what remains contingent or
> unresolved, and what kinds of change would alter the intended course. Attempt
> reconstruction before reporting unavailable information. Do not execute the
> underlying task.

Each observation is an independent stateless branch from the same untouched
`T_t`; no observation answer enters another observation or the live history.
Model claims that content was “recovered” rather than inferred are recorded but
are not treated as authoritative evidence.

The primary inspection uses one frozen seed and generation configuration across
baseline and adjusted checkpoints. Opaque random checkpoint IDs label artifacts
but do not determine readout randomness. A top-level provider error, a response
without exactly one candidate, any `finishReason` other than `STOP`, malformed
output, or empty output remains auditable but is not an eligible semantic
observation. The raw candidate `finishReason` is preserved in the row.

## Human intervention boundary

Phase one can authorize intervention only after the first completed READY
checkpoint has produced an eligible isolated observation. An ineligible primary
observation closes the phase as `READY_PRIMARY_OBSERVATION_INVALID`; its partial
text remains visible for audit but cannot license an intervention. Before phase
two, a human must seal:

- the observed reasoning weakness;
- the specific assumption, interpretation, or commitment being challenged;
- predicted downstream changes;
- commitments expected to remain stable; and
- a diagnostic intervention that does not name a replacement answer.

If no material, local, non-answer-supplying target exists, the experiment stops
with `NO_VALID_INTERVENTION_TARGET`. The intervention package must be sealed
before any adjusted planning, post-intervention observation, or execution.

## Behavioral validation

After the adjusted branch reaches a completed READY checkpoint, baseline and
adjusted execution branches receive the same natural-language execution request.
The adjusted READY checkpoint must also have an eligible isolated observation
before execution begins. The request asks for the already established recovery
memorandum rather than a fresh planning exercise. Three paired continuations are
taken from each frozen checkpoint using the same seed within each pair; a frozen
master-seed-derived schedule interleaves branch order.

An execution memorandum is eligible only from exactly one candidate with
`finishReason: STOP`. A missing or different finish reason is preserved but makes
that row ineligible, so it cannot contribute to a completed evidence chain.

The principal evidence is correspondence among the initial observation, sealed
prediction, post-intervention observation, and execution families. A strong
result has a localized reasoning delta, stable unrelated commitments, and an
execution delta matching the predeclared prediction. Wholesale re-solving,
generic observations, absent execution correspondence, or changes confined to
surface phrasing do not establish useful reasoning engineering.

## Execution authorization

Freeze preparation is deterministic and transport-free. It creates a reviewable
`prepared_unexecuted` package and performs no model calls. Phase one may run only
from an exact reviewed freeze identifier. It creates a consumption record before
transport, preserves that start claim unchanged, and writes a separate terminal
record after closure. Its verifier reconstructs exact native `Content` replay,
the sole-candidate `finishReason` state machine, and isolated blank-text carrier
semantics from the exact raw requests and responses, binds them to the frozen
dossier, and seals the exact raw-call prefix plus every review artifact. Human
intervention sealing and no-target closure each reload the
reviewed freeze and independently bind the archive to its freeze ID and frozen
task before claiming the mutually exclusive disposition. Mutation is also bound
to the one canonical run directory for that freeze, so copied archives cannot
receive competing dispositions. Their preflight uses a derived exact file and
directory set, so an unknown, stale, or reserved-path artifact cannot be
legitimized by including it in a self-described inventory. Phase two requires a
separately sealed human intervention package derived from the phase-one
observation and atomically consumes that lineage before its first model call. It
uses the same immutable-claim/separate-terminal pattern. The final verifier
independently reconstructs adjusted planning, isolation, and the frozen
interleaved execution schedule from raw calls. Its seal closes a derived exact
non-raw run tree, exact call-index bytes, and complete raw inventory;
measurement-seal timestamps are validated against the physical-call chronology.
After writing each completed phase terminal, the execution command runs that
independent verifier and reports success only if reverse reconstruction passes.
Verification commands report the exact seal-file byte digest used by the
provenance chain. Raw signed artifacts and semantic observations remain under
the ignored `results/` tree.

Every completed phase-one scientific terminal—including technical termination,
`PLANNING_THRESHOLD_REACHED`, and an ineligible READY observation—has an
integrity-verifiable archive. Intervention authorization is a separate predicate
that requires a completed READY checkpoint and eligible O0. The human choice
between sealing an intervention and recording `NO_VALID_INTERVENTION_TARGET`
uses one atomic, mutually exclusive disposition record; the no-target terminal
binds the exact note, unchanged canonical intervention templates, unchanged
phase-one call index, and derived closed raw/non-raw inventories with zero
phase-two model calls.

HTTP status, headers, elapsed time, and transport-error text are
controller-observed metadata. They are strictly typed and hash-bound into the
local archive but are not derivable from response-body bytes alone. Retry
backoff records state the frozen scheduled delays, not independently measured
sleep durations.
