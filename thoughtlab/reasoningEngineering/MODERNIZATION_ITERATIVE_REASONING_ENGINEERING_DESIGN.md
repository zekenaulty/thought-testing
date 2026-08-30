# Iterative Modernization Reasoning-Engineering Design

## Status and purpose

This document specifies a fresh, staged occurrence of the modernization
reasoning-engineering experiment. It retains the proven Gemini Developer API
`generateContent` carrier, the raw `READY`/`NOT_READY` planning boundary, and
the established isolation/mutation technique. It changes the causal design
from one diagnostic intervention to exactly three qualitatively distinct,
examiner-guided and human-sealed diagnostic interventions followed by matched
behavioral continuations.

The primary trajectory is:

```text
C0 -> O0 -> X1/I1 -> C1 -> O1 -> X2/I2 -> C2 -> O2 -> X3/I3 -> C3 -> O3
                                                                       |
                                                              matched executions
                                                              from C0 through C3
```

`C0` through `C3` are completed, signed, decision-ready planning checkpoints.
`O0` through `O3` are query-conditioned observations made by isolating those
checkpoints. `X1` through `X3` are examiner analyses and `I1` through `I3` are
their human-approved diagnostic interventions, sealed before the next planner
call. These labels are analytical notation, not model-facing identifiers.
Stored checkpoint and claim identifiers remain random, opaque, and
type-neutral.

The occurrence asks whether a reasoning state can be observed, deliberately
and locally modified, and then used differently. Those are three different
claims. Evidence for one does not establish the others.

## Corrected premise: isolation/mutation is the tomography operator

Isolation/mutation is the experiment-protocol-defined primary tomography
operator. It is not an accidental corruption path, a degraded substitute for
normal continuation, or something outside this experimental protocol.

The operator is intentionally distinct from live continuation:

- **Live continuation** replays the provider's sole candidate model `Content`
  unchanged. Role, `Part` order, text, optional flags, and every
  `thoughtSignature` are preserved exactly before a new user continuation is
  appended.
- **Tomography** deep-copies the target checkpoint's native model `Content`,
  changes every existing `Part.text` to `""`, and preserves the model role,
  `Part` order, optional flags, and every `thoughtSignature`. It places that
  mutated carrier between a neutral structural user message and the frozen
  inspection query. The planning system instruction, dossier, ordinary
  history, and visible readiness token are withheld.

Exact unmodified replay is the provider-facing rule for maintaining the live
reasoning state. Blank-text isolation is the experiment-facing rule for
querying that state without supplying the ordinary semantic context. Calling
the mutation experimental does not make it external to our protocol; the
mutation is the protocol's central measurement operation.

The resulting observation is written as:

```text
O_t(q) = T(C_t) queried by q
```

where `T` is the frozen isolation/mutation operator and `q` is the frozen
holistic inspection prompt. `O_t(q)` is a semantic projection conditioned on
the carrier and query. It is not asserted to be a verbatim hidden chain of
thought, a complete copy of `C_t`, or an authoritative account of how every
conclusion was formed.

Tomography is always a sibling call. Its response never enters planning,
intervention, or execution history.

## Three claims that must remain separate

### Observability

Observability means that isolation produces specific, integrated, and
checkpoint-sensitive semantic structure: the problem interpretation,
meaningful options, stabilized commitments, evidential bases, assumptions,
dependencies, unresolved conflicts, contingencies, and revision conditions.
An articulate answer alone is insufficient. The observation must contain
relationships that can be compared across checkpoints and connected to later
behavior.

### State modification

State modification means that a sealed local intervention is followed by a
localized and predicted change in those semantic relationships while unrelated
commitments remain substantially stable. A different observation is not, by
itself, proof of controlled modification. Differences may result from sampling,
fresh reconstruction, added planning time, or wholesale re-solving.

### Successful repair

Successful repair is a stronger behavioral claim. It requires the targeted
weakness to be improved in the later reasoning state and for matched execution
families to express the predicted downstream change without unacceptable
collateral degradation. A state can be observable but not controllable; it can
be controllable but modified in the wrong direction; and it can show a
plausible semantic repair without producing a reliable behavioral improvement.

The final report must state these conclusions independently.

## Frozen transport and planning invariants

The occurrence uses the Google Gemini Developer API v1beta
`models/{model}:generateContent` endpoint with `gemini-3.7-flash`. It does not
use Interactions, function calls, tools, response schemas, or a JSON readiness
envelope.

Planning retains the established scaffold: build a whole-problem
interpretation, keep plausible options live until evidence distinguishes them,
preserve the bases for selection and rejection, represent assumptions and
dependencies, test contrary evidence, and attach fallbacks to meaningful
failure or revision conditions. Source provenance, incentives, reliability,
scope, disagreement, and missing evidence remain material. The instruction
continues to prohibit checklist theater.

During planning, the visible response must be one raw token:

```text
READY
```

or:

```text
NOT_READY
```

Provider completion and the visible model judgment remain separate. The sole
candidate's `finishReason` is classified before visible text is parsed:

- `STOP` plus normalized exact `READY` freezes a completed checkpoint.
- `STOP` plus normalized exact `NOT_READY` records
  `SELF_DECLARED_NOT_READY` and continues.
- `STOP` plus malformed or empty status records `INVALID_STATUS` and
  continues if the signed carrier is replayable.
- `MAX_TOKENS` records `UNOBSERVED_TRUNCATED`, regardless of partial visible
  text. It is not converted into a model judgment.
- A missing, safety, or other unsupported finish reason is a technical
  termination.
- A response without exactly one candidate or without a replayable signed
  carrier is a technical termination.

For `NOT_READY`, `INVALID_STATUS`, and replayable `MAX_TOKENS`, the next request
contains the exact complete prior model `Content` followed by the same neutral
continuation prompt. A truncated checkpoint may be tomographically inspected
and may become scientifically valuable, but it is never promoted to a
decision-ready intervention or execution baseline. If the next exact-history
turn quickly emits `READY`, that later completed checkpoint is eligible. If the
planning-turn threshold is reached first, the terminal is
`PLANNING_THRESHOLD_REACHED`, with the last classification retained separately.

An inspection or execution response ending in `MAX_TOKENS` remains auditable,
including its partial visible text, but is ineligible as a completed semantic
observation or execution measurement. It is not silently repaired or promoted.

## Participant topology and epistemic asymmetry

Participant count and role separation are frozen experimental variables:

- **Planner:** Gemini 3.7 Flash receives the dossier and semantic-state planning
  contract. It never receives the examination charter, fault atlas, scoring
  rubric, observations, or reviewer prose.
- **Examiner:** `gpt-5.6-sol` at `xhigh` in the ChatGPT harness receives the
  dossier, the current sanitized observation, the stage-specific examination
  charter, and a private generic fault atlas. It never receives a privileged
  correct architecture and may not prescribe one.
- **Human adjudicator:** the researcher inspects the artifacts, records an
  independent review, reconciles it with the examiner output, and alone
  authorizes the exact model-facing intervention.

This is three participant roles and two model agents. Each review artifact binds
its exact sanitized input hash and provenance. The examiner produces exactly
three recorded examination turns. No fourth examination is permitted.

The private fault atlas names general failure classes only: evidence/inference
conflation, provenance misweighting, unsupported commitment, favorable-bound
selection, resource or calendar collision, authority mismatch, dependency
cycle, unbounded critical uncertainty, fallback without trigger, trigger
without actionable fallback, prematurely discarded alternative, and local
consistency with global inconsistency. It contains no dossier-specific defect or
preferred solution.

The examinations escalate rather than repeat:

1. **X1 — epistemic hinge audit.** Identify one consequential relationship that
   carries substantial downstream structure and test whether its evidentiary
   authority is earned. Distinguish source evidence from inference.
2. **X2 — adversarial alternative/falsification audit.** Identify the strongest
   materially plausible competing interpretation or course and test whether
   the current commitment defeated it or merely stopped considering it.
3. **X3 — global reintegration/joint-feasibility audit.** Treat the revised plan
   as one coupled system and identify the strongest remaining conflict across
   resources, timing, authority, dependencies, uncertainty, and contingencies.

Each examiner may select one challenge, identify the downstream region expected
to change, and identify commitments expected to remain stable. It may not tell
the planner which architecture to choose.

## Primary staged trajectory

### Stage 0: construct and observe C0

Gemini receives the frozen modernization dossier and planning instruction. It
continues until the first completed `READY` checkpoint or a frozen terminal.
Every replayable planning checkpoint is independently isolated so truncation
and pre-readiness development remain observable. The eligible observation of
the completed READY checkpoint is `O0`. If C0 or O0 is unavailable, the primary
trajectory stops.

### Examination/gate 1: X1 and sealed I1

The examiner performs the epistemic-hinge audit on O0. The human stream is
recorded independently, then the human adjudicator reconciles both streams and
seals one adaptive intervention. Before any further planner call the package
binds the observed evidence, targeted relationship, predicted O0-to-O1 local
delta, expected downstream effects, stable commitments, exact intervention,
review provenance, and all input hashes. If no valid hinge exists, the
occurrence terminates with zero later calls.

### Stage 1: apply I1, construct C1, and observe O1

I1 is appended to exact unmodified `C0.full_history`; O0 and all review prose
are excluded. Gemini plans to C1 or a frozen terminal, and every replayable
checkpoint is independently isolated. The eligible READY observation is O1.

### Examination/gate 2: X2 and sealed I2

The examiner performs the adversarial-alternative/falsification audit on O1.
The human-approved package additionally states which O0-to-O1 changes should
persist, reverse, or remain unaffected. I2 is sealed before any C2 call. It may
challenge only one falsification relationship and may not recommend the
alternative itself.

### Stage 2: apply I2, construct C2, and observe O2

I2 is appended to exact unmodified `C1.full_history`; no observation or review
output enters the history. Gemini plans to C2 or a frozen terminal, followed by
independent tomography of every replayable checkpoint and designation of O2.

### Examination/gate 3: X3 and sealed I3

The examiner performs the global reintegration/joint-feasibility audit on O2.
The package records which prior changes should persist, reverse, or remain
unaffected and seals one system-level concern without prescribing a solution.
No fourth examination can be opened.

### Stage 3: apply I3, construct C3, and observe O3

I3 is appended to exact unmodified `C2.full_history`; O0 through O2 and every
review artifact remain sibling-only. Gemini plans to C3 or a frozen terminal,
followed by independent tomography. The human researcher then seals the O3
six-dimension rubric, hard-contradiction judgment, and final I1/I2/I3 target
states before seeing execution outputs. This is a measurement gate, not X4: it
creates no examiner turn, intervention, or planner call. Matched execution
begins only if C3 is a completed READY checkpoint, O3 is eligible, and that
human assessment is sealed.

## Matched execution families

The behavioral measurement uses four checkpoint families: C0, C1, C2, and C3.
Each receives the same execution instruction asking it to render the recovery
plan already established at that checkpoint. The complete unmodified parent
history is replayed; no observation text, reviewer diagnosis, or execution from
another branch is supplied.

There are three replicates per checkpoint. Within each replicate, C0 through C3
use the same frozen seed. A master-seed-derived schedule randomizes and
interleaves the four branches within replicate blocks. All twelve continuations
are independent siblings.

An execution row is eligible only when the sole candidate ends in `STOP` and
contains non-whitespace ordinary text. `MAX_TOKENS`, safety termination,
transport failure, malformed content, or empty output remains preserved but
ineligible. The completed evidence chain requires all twelve prespecified rows;
missing rows are not replaced after results are seen.

## Convergence versus sophisticated rationalization

Repeatedly coherent observations can indicate convergence, but they can also
be sophisticated rationalization: a model may construct a persuasive account
that explains its latest answer without preserving or repairing the intended
reasoning relationships.

Evidence favoring controlled convergence includes:

- the predeclared local relationship changes in the predicted direction;
- the basis, dependency, contingency, or revision structure changes with the
  targeted commitment rather than merely changing terminology;
- unrelated commitments remain stable across O0 through O3;
- each gate's predicted persistence, reversal, and new-change regions are
  observed;
- execution families show the corresponding incremental C0-to-C1, C1-to-C2,
  and C2-to-C3 differences; and
- replicate variation is smaller than the targeted between-checkpoint change.

Evidence favoring rationalization or wholesale re-solving includes:

- observations that mainly paraphrase the intervention;
- global architectural rewrites after a narrowly targeted challenge;
- polished explanations without preserved rejection, dependency, or fallback
  bases;
- post hoc coherence not anticipated in the sealed prediction;
- unstable unrelated commitments;
- execution families that remain behaviorally unchanged, vary incoherently, or
  fail to express the predicted delta; and
- reviewers needing to invent an explanatory story after seeing all outputs.

Neither agreement between reviewers nor eloquence of the model is sufficient.
The adjudication concerns predicted relational change and behavioral
correspondence.

## Semantic and relational adjudication

The primary analysis is semantic and relational, not an exact-state or
mathematical identity test. Byte hashes establish artifact integrity and causal
lineage; they do not measure whether two reasoning states mean the same thing.
Token counts describe resource use; they do not measure reasoning quality.

Every O0-through-O3 adjudication uses the same human semantic rubric. Each
dimension receives 0, 1, or 2 with cited evidence:

| Dimension | 0 | 1 | 2 |
| --- | --- | --- | --- |
| Defect recognition | missed | acknowledged | precisely represented |
| Resolution | unresolved or rationalized | bounded | actually resolved |
| Dependency propagation | absent | partial | coherent downstream update |
| Locality | wholesale re-solve | mixed | unrelated commitments stable |
| Evidentiary discipline | unsupported | mixed | appropriately grounded or bounded |
| Joint coherence | contradiction remains | uncertain | jointly feasible |

The 0–12 sum is descriptive, never the sole stopping or success rule. A known
hard contradiction blocks a repair finding regardless of total score.

Each targeted defect also receives one categorical state:

```text
UNRECOGNIZED | RECOGNIZED | BOUNDED | RESOLVED | RATIONALIZED
```

`RATIONALIZED` means the state now discusses the defect intelligently while
preserving the incompatible commitment. It is not collapsed into partial
success. The ordered sequence of these labels is a primary result because it
distinguishes convergence from increasingly sophisticated explanation of an
unrepaired defect. Each assessment records the state of every previously
targeted defect that can be evaluated in that observation; the final O3
assessment therefore records separate states for the I1, I2, and I3 targets.

Two declared review streams independently evaluate sanitized artifacts before
human-approved reconciliation. At least one stream is the human researcher;
the provenance and harness/model of any model-assisted stream are recorded.
Execution outputs should be branch-anonymized and order-randomized for initial
review where practical. Each review stream records:

- the problem interpretation and material competing possibilities;
- stabilized commitments and their support;
- assumptions, dependencies, and unresolved conflicts;
- rejected or deferred options and conditions for reopening them;
- contingencies and revision triggers;
- the predicted local delta at each intervention;
- stability or collateral movement outside the target region;
- whether execution expresses the predicted incremental change; and
- evidence of convergence, rationalization, or fresh re-solving.

The human researcher reconciles disagreements with explicit reference to the
artifacts and records approval. The final report retains both independent
judgments and the reconciled assessment. It reports observability,
modification, and successful repair separately and states where evidence is
ambiguous.

## Private raw artifacts and shareable records

Raw provider request and response bytes, full replay histories, signed
`Content`, and raw `thoughtSignature` values remain private under the ignored
results tree. They are retained for exact verification but never copied into a
shareable report.

Shareable records may contain observation and execution prose, opaque IDs,
finish reasons, eligibility reasons, token counts, sizes, and cryptographic
hashes. Signature metadata may include only count, length, and hash, never the
raw value. The call index binds every physical and logical request to:

- the Google Gemini Developer API;
- HTTP `POST`;
- the exact v1beta `generateContent` endpoint;
- `gemini-3.7-flash`;
- exact request and response byte hashes;
- retry selection and timing; and
- transport and parse outcomes.

Each model-call stage begins with an immutable consumption claim and ends with
a separate terminal record. Each human disposition is atomic and single-use.
Before a later stage begins, the verifier reconstructs and seals the complete
prior call-index prefix and non-raw closure. The final seal binds the freeze,
dossier, all four checkpoints and observations, all three examination and
intervention locks, participant provenance, the execution schedule, all
terminal records, and the final raw and non-raw inventories.

## Prespecified bounds and terminals

With the current six-turn planning threshold, tomography of every replayable
checkpoint, four planning stages, and three execution replicates for each of
four checkpoints:

- the completed Gemini-path minimum is 20 logical calls when each stage reaches
  READY on turn one: four planning calls, four inspections, and twelve
  executions;
- the Gemini-path maximum is 60 logical calls: up to 48 planning and
  inspection calls plus twelve executions;
- with at most three transport attempts per logical call, the Gemini physical
  hard cap is 180; and
- the separate examiner path is exactly three recorded Sol/ChatGPT examination
  turns, one at each gate.

Human review and sealing make the occurrence intentionally discontinuous. No
stage proceeds automatically across any examination gate.

Terminals distinguish model judgment from experimental termination. They
include completed evidence, planning threshold reached, technical termination,
invalid READY observation at any stage, no valid intervention target at any
gate, and incomplete execution measurement. A truncated planning turn is
recorded as `UNOBSERVED_TRUNCATED`; it is never mislabeled `NOT_READY` or used as
an execution baseline.

## Interpretation boundary

A strong result would show that the isolated carrier yields meaningful
checkpoint-sensitive observations, that the fixed hinge, falsification, and
reintegration examinations produce three predicted and bounded semantic deltas,
and that four matched execution families express the corresponding incremental
behavioral changes.

Even that result would not establish verbatim access to hidden chain of thought,
perfect state reconstruction, universal controllability, or population-level
reliability. It would establish something narrower and practically important:
under this frozen task, model, carrier, tomography operator, and intervention
procedure, selected semantic reasoning relationships were observable,
iteratively adjustable, and behaviorally consequential.
