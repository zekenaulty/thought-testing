# Native-to-task mutable planning-state transition experiment: frozen specification

## Purpose and decision point

Pilot 05 reproduced candidate registry, utility rank, and post-transition
selected identity in 18/18 planning cells, while explicit rejection and remote
ancestry remained uniformly unavailable. The next experiment should mutate
those replicated components directly. Viability partition and the explicit
pre-selection `known + []` timeline are preregistered exploratory extensions,
not findings already established by pilot 05.

This document specifies one excluded, surgical planning-transition pilot. The
protocol builder, missing-safe scorer, reviewed-freeze verifier, and separately
gated executor are implemented and locally tested. The no-call review package
is prepared at `thoughtlab/stateTransitions/freezes/native_s0_s6_review_01` only
after the source and tests in this specification are final. Neither this
implementation nor that package authorizes an external API call.

## Place in the research program

This pilot is deliberately the **native-to-task, ordinary-instruction baseline**.
It is already a tightly prescribed synthetic planning task; `native` does not
mean unprompted, naturalistic, spontaneous, or human-like cognition. It means
unaugmented by the proposed retention intervention.

Its generation and probe prompts must exclude hermeneutic part/whole language,
metacognitive stages, adversarial alternative preservation, counterfactual-
register instructions, visible staged reasoning, and checkpoint-tool requests.
Adding any of those creates a new protocol and estimand.

Call the recoverability object measured here `R_native`: the preregistered matrix
of checkpoint x field x carrier-arm outcomes, controls, and transition deltas—not
one scalar and not a direct representation of internal state. We need to map and
attack that matrix before trying to enrich it. If a retention scaffold were
added now, recovered alternatives, reversal conditions, or uncertainty would be
confounded with the intervention, and we would no longer know what the frozen
ordinary-instruction process supported on its own.

The intended sequence is:

```text
pilot 05 planning slice
        -> mutable native-to-task S0-S6 pilot
        -> excluded replication/adversarial attack of native dynamics
        -> freeze the native recoverability model and claim boundary
        -> contemporaneous native/neutral/retention scaffold experiment
        -> only then evaluate any downstream system use
```

The later matched experiment compares three contemporaneous recoverability
matrices: `R_native` for the frozen ordinary-instruction condition, `R_neutral`
for an effort-, structure-, placement-, and length-matched neutral procedure,
and `R_retention` for the private hermeneutic/metacognitive retention scaffold.
It preregisters three cellwise, matrix-level behavioral contrasts:

- total package contrast, `Delta R_total`: `R_retention` versus `R_native`;
- retention-specific contrast, `Delta R_retention`: `R_retention` versus
  `R_neutral`; and
- generic procedure/effort diagnostic, `Delta R_procedure`: `R_neutral` versus
  `R_native`.

These are contrasts between observed outcome matrices, not scalar measurements
of a latent state. A two-arm native-versus-retention fallback would be a
separately preregistered package-only study: it could estimate the total package
contrast but could not isolate the retention-specific mechanism. None of these
later experiments is authorized by approval of this plan.

The native model must not be frozen from one sequence. The intervening
replication/attack phase uses independently generated master seeds, opaque-ID
universes, utilities, and task instances under one frozen protocol, with any
request/retry revision reported separately rather than silently pooled.

Terminology matters: the earlier confirmatory proposal was **30 eligible
trials, capped at 40 attempted trials**, not one 30-40-turn conversation. That
confirmatory program remains deferred. The immediate decision is whether to
authorize implementation and preregistration of the excluded transition pilot
below.

## Primary research question

Does a detached latest-response Gemini thought-step bundle support exact,
source-specific, temporally current recovery of a mutable local planning state:

- which opaque candidates are registered;
- their complete relative utility ordering;
- which candidates are viable versus nonviable;
- which candidate, if any, is selected?

The primary claim concerns behavior through a whole signed thought-step bundle.
It does not claim that raw signature bytes encode a database, that the artifact
is a full hidden state, or that chain-of-thought is exposed.

## Synthetic state sequence

All identifiers will use the existing type-neutral scheme: `ID_` plus 26 random
Crockford-base32 characters. Candidate, condition, and other roles are recorded
separately and appear where required in generation instructions; identifier
spelling itself never encodes role.
Target and donor trials use disjoint identifier universes, independently
randomized utilities, presentation order, and alias-to-role mappings.
Aliases A-D are report-only and never appear in model requests; generation
prompts use only opaque identifiers plus separately stated roles and utilities.

| Checkpoint | Prescribed current state | Discriminating transition |
|---|---|---|
| S0 | empty planning slate | initialization |
| S1 | candidates A/B/C; all viable; rank A > B > C; none selected | registry acquisition |
| S2 | candidates unchanged; all viable; rank B > A > C; none selected | rank reversal |
| S3 | remove C; candidates A/B; both viable; rank B > A; none selected | membership deletion |
| S4 | add D; candidates A/B/D; all viable; rank B > A > D; none selected | membership addition |
| S5 | keep A/B/D registered; current top-ranked B becomes nonviable under a new local opaque condition; rank remains B > A > D; none selected | viability change without deletion |
| S6 | preserve registry/rank/viability; select the unique highest-ranked viable candidate (ground truth A) | viability-dependent selection transition |

S0 is an explicit epistemic-empty baseline, not missing data: registry and
ranking are `known + []`; viability is `known` with both arrays empty; and
selection is `known + []`. Visible-only and probe-only controls remain
`unknown` with the same empty collection shapes.

Numeric utilities will be deterministic, distinct, and randomly generated
before execution. S2 changes only B's actual utility so it passes A, rather than
restating the candidate set or merely asserting a verbal ordering. D's value is
chosen so the exact S4 order is `B > A > D`. At S5, B remains in
the candidate registry but becomes nonviable; this intentionally distinguishes
removal from nonviability. It also makes S6 depend on the S5 update: without the
viability change B would win, while the correct highest viable choice is A.

The motivating sketch made A nonviable and then selected B. This protocol instead
makes the current leader B nonviable so the selection transition tests whether
viability affects action, not merely whether two independent labels can be
recovered.

Every visible generation response remains exactly `{"ack":true}` and must not
contain any prescribed identifier, utility, role, status, or relation.

## Atomic tomography fields

Each S0-S6 artifact is probed independently with a fresh stateless request for
four strict fields:

1. `candidate_registry`: exact unordered set of registered candidate IDs.
2. `utility_ranking`: exact ordered list of all registered candidates, highest
   to lowest, including a nonviable candidate if still registered.
3. `viability_partition`: exact disjoint `viable_ids` and `nonviable_ids`
   arrays, each scored as an unordered duplicate-free set, whose union equals
   the candidate registry.
4. `selected_candidate`: epistemic `known + []` before S6 and `known + [A]` at
   S6; `unknown + []` remains a different, nonexact answer.

The viability partition avoids forcing the model to use the word `rejected`.
It tests whether B remains represented but becomes unavailable, versus silently
disappearing from the active candidate set.

## Carrier arms

For every checkpoint/field cell:

1. **Target full valid prefix** — documented-valid target task-adherence upper
   bound.
2. **Target latest-response thought bundle** — primary experimental carrier.
3. **Target cumulative thought bundle** — secondary comparison with latest.
4. **Target visible acknowledgement only** — passive visible-output control.
5. **Probe only** — absence-of-carrier control.
6. **Same-checkpoint wrong-trial latest bundle** — source-specific donor
   control, scored against target and donor truth.
7. **Donor full valid prefix** — donor task-adherence upper bound, needed to
   distinguish a donor-generation failure from a detached donor-carrier failure.

Temporal localization does not require an additional eighth API arm. Because
each primary
latest-bundle response uses the same checkpoint-neutral prompt and field schema,
adjacent responses can be cross-scored mechanically against both endpoint
truths. Reissuing the identical prior carrier and probe would be a repeatability
check, not a distinct temporal intervention. This cross-scoring is a derived
localization analysis nested inside endpoint exactness, not an independent
causal control.

The complete matrix contains 196 logical tomography requests:

- 7 checkpoints x 4 fields x 7 arms = 196.

Target and donor generation add 14 logical requests, for 210 logical requests
in a complete eligible run before any physical transport retries.

## Ground-truth and transition scoring

Scoring must report both state exactness and delta exactness.

The preregistered primary state and delta composites use target latest-bundle
rows. Apply the same delta function to target cumulative, target full-prefix,
donor latest, and donor full-prefix rows as separately labeled diagnostics; do
not substitute one arm's success for another's failure.

### State-level exactness

For each checkpoint and field:

- exact target truth;
- exact donor truth when applicable;
- exact adjacent-checkpoint truths through preregistered mechanical
  cross-scoring after collection;
- missing, extra, duplicate, noncanonical, or foreign IDs;
- role-inappropriate IDs: the local condition ID belongs to the source trial
  universe but is always extra in every planning-field collection;
- future-state leakage and stale-state retention;
- `known` versus `unknown` correctness.

Future leakage is source-relative. For target full/latest/cumulative rows, score
against the target timeline; for wrong-trial latest and donor-full rows, score
against the donor timeline. At S0-S5, compare each field only with later truths
that differ from current truth. Record a future-exact hit only when the answer is
current-inexact and exact for such a later state, and separately record every ID
returned before its source-trial introduction. Stable future truths do not count
as leakage. This is the frozen narrow hard-gate definition: zero future-exact
hits and zero premature IDs. Enumerate partial future-aligned membership,
pairwise-order, viability, or selection errors separately as diagnostics, but do
not inconsistently promote them to hard-gate events. They remain current-state
errors. Visible/probe controls are governed by their stricter no-ID gate.

### Prescribed deltas

| Transition | Expected observable delta |
|---|---|
| S0 -> S1 | add A/B/C to registry, rank, and viable set |
| S1 -> S2 | rank changes from A>B>C to B>A>C; membership/viability stable |
| S2 -> S3 | C disappears from registry, rank, and viable set |
| S3 -> S4 | D appears in registry/rank/viability at the lowest rank |
| S4 -> S5 | B moves viable -> nonviable; registry and rank remain stable |
| S5 -> S6 | selected changes known-empty -> the highest-ranked viable candidate A; all other fields stable |

There are 24 adjacent field-pairs across the six transitions. Twelve must
change: S1 registry/rank/viability; S2 rank; S3 registry/rank/viability; S4
registry/rank/viability; S5 viability; and S6 selection. The other 12 must remain
stable. Delta exactness means mechanically deriving each observed add/remove,
reorder, viability move, selection change, or stable retention from the two
normalized endpoint answers and matching that operation to the frozen expected
delta. A pair is delta-exact only when both normalized endpoint answers are
schema-valid and exact for their own source truths and the derived operation is
exact. A missing, unknown, invalid, or source-inexact endpoint makes the pair
nonexact, even if two wrong states would otherwise cancel into the expected
delta. Report all 24 pairs, the 12 changed pairs, and the 12 stable pairs
separately.

The same mechanical delta function is applied to five frozen source arms, so
the complete derived delta matrix has exactly 120 unique
`(transition, field, arm)` rows. Missing, duplicate, extra, or nonmechanically
altered delta rows make that matrix incomplete; row-supplied flags are never
trusted in place of recomputation from the frozen endpoint observations.

## Preregistered gates

The implementation should freeze exact denominators before any API call.
Recommended gates are:

### Common validity gate

- 14/14 generation checkpoints eligible;
- exact target/donor stateless lineages and distinct checkpoint artifacts;
- exactly one row for each of the 196 frozen `(checkpoint, field, arm)` manifest
  keys, with zero duplicate, extra, or malformed keys. Incomplete,
  transport-failed, or schema-invalid outcomes remain at their intended key in
  the denominator as nonexact;
- target full prefix 28/28 exact and donor full prefix 28/28 exact (56/56
  combined task-adherence cells);
- all 56 visible-only/probe-only cells evaluable and schema-valid with
  `knowledge = unknown` and the exact empty collection shape for that field;
- zero raw or parsed ID leakage in controls;
- zero unexplained, duplicate, or noncanonical returned IDs.

### Latest-bundle component gates

- replication-under-history composite: registry S2-S6 5/5 exact, ranking S2-S6
  5/5 exact, and post-transition selected identity at S6 1/1 exact (11/11
  jointly);
- complete registry and rank trajectories, including prompt-sufficient S0/S1:
  registry 7/7 and ranking 7/7 exact;
- exploratory viability extension: partition 7/7 exact;
- exploratory no-selection extension: S0-S5 `known + []` 6/6 exact;
- joint mutable-planning-state composite: 28/28 exact;
- history-dependent subset: all 20 S2-S6 latest-bundle cells exact. The eight
  S0/S1 cells are current-prompt-sufficient and must be reported separately,
  not promoted as evidence of persistence beyond the current update;
- adjacent delta composite: 24/24 exact, with 12/12 changed and 12/12 stable
  field-pairs reported separately.

The component gates must remain reportable even if the 28/28 joint gate fails.
In particular, a viability, known-empty, S0, or prompt-sufficient S1 failure must
not be reported as a failure of the 11/11 replication-under-history composite.

### Causal-specificity gates

- wrong-trial latest bundles: 28/28 donor-exact; on the 19 cells where target
  and donor truth differ, 19/19 donor-exact and target-inexact. The four S0
  empty-state fields and five S1-S5 `selected_candidate = known + []` fields are
  excluded from the specificity denominator because target and donor truth
  coincide;
- adjacent-checkpoint cross-score diagnostic: on all 12 changed field-pairs, the
  preceding artifact is preceding-exact/current-inexact and the new artifact is
  current-exact/preceding-inexact. This localizes changes but is not counted as
  evidence independent of the 28/28 current-state gate;
- zero future-exact hits and zero premature IDs at every source checkpoint under
  the narrow preregistered definition above;
- all target and donor full-prefix cells exact, so a detached or donor failure
  cannot be blamed on an impossible task or incorrect source truth;
- zero IDs from the wrong trial universe in target arms, zero target IDs in
  donor-source arms, zero IDs from either universe in controls, and zero
  role-inappropriate condition IDs in any planning-field answer. Intended donor
  IDs are target-foreign diagnostics, not unexplained foreign IDs.

### Secondary latest-versus-cumulative comparison

Report per-field agreement and exactness without making cumulative superiority
part of the primary gate. Pilot 05 produced identical latest and cumulative
answers; this experiment asks whether that remains true across actual mutations.
At S0, latest and cumulative carriers are carrier-identical by construction
because only one generation response exists. Those four calls are balanced
repeatability cells and must be excluded from any latest-versus-cumulative
agreement or superiority inference.

All cell and delta denominators are correlated completeness checks within one
target/donor chain. They are not 28 or 24 independent replications and do not
estimate population reliability. Likewise, the 56 control rows include request
bodies that repeat across checkpoints by design; report row outcomes without
describing them as 56 independent controls.

## Execution discipline

Before execution:

- implement strict schemas and missing-safe mechanical scorers;
- keep schemas structural and identical across checkpoints/arms: require exact
  keys, no extras, types, and the `known`/`unknown` enum, while explicitly
  allowing empty collections. Put `unknown => empty` in the probe instruction
  and local validator/scorer rather than relying on conditional provider JSON
  Schema support. Enforce truth-specific cardinality, duplicate, partition,
  disjointness, and union rules only in the scorer so schemas do not leak truth;
- deterministically generate and validate all target/donor truths;
- freeze prompts, response formats, code hashes, model/configuration, task order,
  seeds, and carrier construction;
- use minimal delta-only generation updates after S1: S2 supplies only B's new
  utility and does not state the derived order; S3 names only the
  removal; S4 names only D and its utility; S5 names only B and the new blocking
  condition; and S6 gives only the selection rule, never the ground-truth winner.
  Unaffected registry, rank, viability, and selection state must not be
  restated;
- keep each field's probe text, response schema, generation configuration, and
  matched best-effort API seed identical across checkpoints and carrier arms so
  carrier content is the intended changing input;
- deterministically randomize the complete tomography task order before freezing
  it, so arm/checkpoint effects are not confounded with a monotonic run order;
- prepare without API calls and independently audit the frozen manifest;
- define bounded transport-retry and pre-tomography replacement/semantic
  stopping policies, embed their exact hashes and copies in the preregistration,
  and freeze the endpoint, request envelope, local schema-epoch label, and
  presence or absence of an `Api-Revision` header. The schema-epoch label is an
  audit description, not a provider revision pin.

During execution:

- use Gemini 3.7 Flash through the frozen Interactions endpoint and request
  envelope recorded under the local schema-epoch label, without implying that a
  provider transport revision is observable or pinned;
- carry forward the pilot 05 request settings unless a separately frozen local
  feasibility revision is required: stateless full-input requests,
  `store = false`, `stream = false`, `background = false`, high thinking, no
  thinking summaries, `max_output_tokens = 8192`, and no `temperature`, `top_p`,
  or `top_k`;
- retain exact stateless prefixes for generation;
- use one fresh stateless request per tomography cell;
- preserve every physical attempt and byte hash privately;
- use at most three byte-identical physical attempts per logical request, with
  frozen 2- and 5-second backoffs, only for transport errors or HTTP
  408/429/500/502/503/504;
- never retry an unfavorable, incomplete, malformed, or scientifically negative
  2xx response;
- stop after the first generation-eligible run enters tomography and accept its
  semantic outcome.

The proposed execution-level stopping rule allows at most two planned run
attempts total. A second run is permitted only if the first fails generation
eligibility before any tomography request. The first run that enters tomography
is final regardless of missingness or semantic outcome; an unfavorable result
never authorizes a rerun.

The frozen request budget should record both logical and physical ceilings. One
complete eligible run has 210 logical requests and at most 630 physical
attempts. Across the two-run stopping policy, the worst case is 14 generation
requests in a pre-tomography failed run plus one complete run: 224 logical
requests and at most 672 physical attempts.

Pilot artifacts remain excluded. Results from different frozen request or retry
revisions are reported separately rather than naively pooled.

## Downstream matched scaffold experiment

Only after native-to-task planning dynamics replicate should a separate,
contemporaneous matched experiment test whether the pattern of model-mediated
recoverability can be deliberately changed. A future scaffold run must not use
this historical pilot as its sole control because model/API drift would be
confounded with condition.

The intervention arm would privately require a hybrid metacognitive-hermeneutic
procedure before the unchanged acknowledgement:

1. orient to the whole problem without committing;
2. maintain several genuinely viable paths;
3. evaluate each path's evidence, weaknesses, consequences, and uncertainty;
4. revisit the whole in light of the parts and the parts in light of the revised
   whole;
5. make a provisional choice while retaining the strongest alternatives;
6. make the strongest case against the primary and for the best alternative;
7. retain reversal conditions and unresolved discriminating evidence as a
   counterfactual register;
8. commit to the primary continuation without deleting that register.

The strongest design is a contemporaneous three-arm study:

1. a fresh execution of the frozen native-to-task condition;
2. a length-, structure-, placement-, and effort-matched neutral procedural
   scaffold that does not require retaining alternatives or reversal conditions;
3. the metacognitive-hermeneutic retention scaffold.

This separates the total scaffold-package effect from a more specific effect of
the retention procedure. If only two arms are feasible, preregister that as a
separate fallback; its result estimates the assigned package as a whole, not a
uniquely hermeneutic mechanism.

Randomize at the complete target/donor-sequence level and interleave matched
conditions. Each condition needs its own same-condition donor. Hold constant the
underlying problem graph, utilities/evidence, state transitions, final choice
rule, visible output `{"ack":true}`, model/API envelope, best-effort seeds,
probe schemas and text, carrier arms, task-order policy, transport/stopping
rules, and scorer. Use separate opaque-ID universes linked only by a frozen
offline bijection.

Apply the treatment during state generation and keep all tomography probes
neutral and identical. Scaffolding only the probe changes the readout estimand;
scaffolding both formation and readout is a third factorial condition. A visible
staged-output version is also a separate experiment because emitted stages join
the autoregressive prefix and may not be represented in the preceding thought
artifact.

Existing history-dependent planning fields and carrier-specific donor/control
behavior should remain the primary contrast, preventing the treatment from
winning merely because it explicitly introduced new vocabulary. New
continuation-relevant fields—current primary path, strongest live alternatives,
viability, reversal conditions, unresolved uncertainty, and discriminating
evidence—are secondary until their opaque, mechanically scoreable truths are
frozen for every arm.

The legitimate positive claim would be behavioral:

> Under this configuration, the assigned scaffold package changed which
> preregistered semantic distinctions model-mediated probes recovered through
> whole signed thought-step carriers.

That is the operational meaning of `reasoning-state engineering` in this
program: alter the originating procedure, then measure a controlled difference
in recoverability. It does not mean mutating or decoding signature bytes.

It would **not** show that the scaffolded alternatives arose spontaneously. We
caused the procedure to keep them live. It would not prove that the prescribed
stages occurred internally, reveal pre-existing authentic beliefs or identity,
establish direct access to a contemporaneous self-record, expose hidden chain-
of-thought, or serialize complete latent state.

A later refinement may insert a checkpoint with **no prescribed semantic state
change** immediately before commitment and compare its carrier with the post-
commitment carrier. The identical checkpoint operation must appear in every
matched condition, and the report must acknowledge that requesting a checkpoint
can itself alter reasoning state. That study could test whether recoverable
counterfactual structure contracts across commitment, but it must not be folded
into the native S0-S6 baseline.

## Raistlin Bridge relevance and boundary

Raistlin Bridge is a downstream application context, not part of this pilot's
ground truth or success gate. The research can inform it in two distinct ways:

- **Original-turn receipts on the live path.** An ordinary interaction can
  retain input, the exact approved context/prompt receipt, visible output,
  model/configuration provenance, and the whole provider response/signed
  thought-step artifact without another interpretive model invocation. These are
  sensitive contemporaneous generation records, not identity truth or a readable
  self-record; capture, validation, secure storage, and transport still cost
  time and resources.
- **Derived reflection on the cold path.** Expensive hermeneutic/metacognitive
  forks, counterfactual analysis, and merge/adjudication can run asynchronously
  over canonical evidence after the live response is committed.

All cold-path forks descend from one root turn. They increase analytical
resolution but remain one evidence lineage, not multiple independent witnesses.
Their outputs must be labeled `derived_reflection` and retain root-turn ID,
parent links, scaffold version, and evidence-lineage ID. If a governed process
later promotes a derived conclusion into live context, record that promotion
explicitly and never recount it as new primary evidence.

For self-authorship, the permissible intervention is an epistemic method—keep
competing interpretations live, preserve what would reverse a provisional
judgment, and track uncertainty—not identity content or a prescribed conclusion.
The scaffold shapes the microscope; it does not decide what the system must see.

No result in this repository automatically justifies putting an eight-stage
deliberation on every live turn. The hot path should preserve the original
receipt, perform only required cheap validation, and deliver; optional identity
work belongs after commitment. Any live cognitive-contract change must first
show a controlled recovery/quality benefit and instrumented segment-level p50/p95
latency, cost, concurrency, storage, and security impact. A minimal conditional
instruction may eventually be justified; universal high-reasoning deliberation
is not the default architecture implied by this work.

## Interpretation decision tree

```text
registry/rank/selected identity persist under mutation
and the viability extension succeeds
                         |
                         v
replicate and adversarially attack native dynamics
                         |
                         v
freeze R_native and its claim boundary
                         |
                         v
run contemporaneous native/neutral/retention scaffold study
                         |
                         v
choose the exact confirmatory claim and any Bridge evaluation

partial replication
       |
       v
narrow R_native to the exact distinctions that survive,
then replicate before adding a scaffold

failure with sound full-prefix and controls
       |
       v
reconsider the carrier model before broader state or BookForge work
```

The later 30-eligible/40-attempt confirmatory protocol is no longer the automatic
next step after one successful mutable pilot. Its outcome variable must be
chosen after native replication and the three-arm scaffold design—or a
separately preregistered package-only fallback—clarifies whether the claim
concerns native-state reliability, scaffold-induced enrichment, or both.
It must not inherit ancestry, objective, constraint, or explicit rejected-
lifecycle gates unless an excluded experiment first demonstrates those fields.

## Approval boundary

Approval of this specification authorized implementation, local tests, a
no-call manifest dry run, and a frozen preregistration for review. Review of the
resulting freeze must not be treated as advance authorization for external API
execution or for the later
native replication, any scaffold experiment (three-arm or two-arm fallback),
checkpoint-tool experiment, visible-stage experiment, Raistlin Bridge/Nyx
cognitive-contract change, or 30/40 confirmatory program.
