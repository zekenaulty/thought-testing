# Agentica Reasoning Engineering Runtime Architecture

## Status and scope

Status: **post-freeze product-architecture candidate**.

Destination: **Agentica**.

This document generalizes results and design lessons from `thought-testing` and
abstraction mining of the Zelanthus planning system. The Python code in this
repository is a calibration rig, controlled transport, golden-trace generator,
adversarial fixture source, and conformance suite. It is not the intended
Agentica runtime architecture.

This document is additive and non-normative for every existing frozen
occurrence. In particular, it does not alter the participant topology, prompts,
state machine, artifacts, bounds, or claims of:

- `MODERNIZATION_ITERATIVE_REASONING_ENGINEERING_DESIGN.md`;
- freeze
  `modernization_iterative_reasoning_engineering_review_01_occurrence_01`; or
- the completed occurrence described by
  `MODERNIZATION_REASONING_ENGINEERING_OCCURRENCE_04_ADJUDICATION.md`.

Substantive statements use three evidence classes:

- **DEMONSTRATED** — supported by a completed, scoped experiment.
- **ARCHITECTURE DECISION** — selected as the candidate product abstraction;
  not itself an empirical claim.
- **EXPERIMENTAL HYPOTHESIS** — requires a separate frozen experiment.

The companion `AGENTICA_REASONING_ENGINEERING_EVIDENCE_INDEX.md` maps each
demonstrated claim to frozen sources, public artifacts, hashes, and audit
limits. Architecture language does not supersede that evidence boundary.

The boundary for the newest idea is explicit:

> A generic-by-construction alignment-carrier program, its opaque provider
> realization, and cross-lineage splicing are architecture hypotheses motivated
> by carrier observability; none has yet demonstrated reusable behavioral
> utility.

## Source grounding

The architecture draws from four distinct sources:

1. Controlled `thought-testing` experiments on provider-native signed carriers,
   exact replay, isolation/mutation, query-conditioned observation, and bounded
   intervention.
2. The current iterative C/O/X/I calibration design with separate planner,
   examiner, and human adjudication roles.
3. The Zelanthus planning guide as an external abstraction source. The reviewed
   file was
   `C:\Users\Zythis\source\repos\Zelanthus\Plans\README.md`, 411 lines,
   SHA-256
   `818afba65ea4ebec7171f30b05ec0f9a3e98be80f10f8006c87d8ff5706ab8ef`.
4. Parallel human/Codex/Sol architecture and QA review.

The reusable Zelanthus abstraction is not its folder tree. It is a governed,
scope-isolated, revisioned evidence aggregate with immutable baselines,
phase-specific records, authority-gated transitions, append-only history, and
traceability from intent through execution to validation.

Agentica generalizes that aggregate so the governed work product is reasoning
itself.

## Product goal

**ARCHITECTURE DECISION**

> Agentica Reasoning Engineering is an autonomous, auditable cognitive-control
> runtime that treats provider-native reasoning-state artifacts—including
> Gemini thought signatures—as opaque continuation-state carriers, observes
> planning through controlled semantic
> projections, delegates diagnosis and intervention to epistemically separated
> actors, continuously checks the evolving plan against a separately sealed
> goal contract, and grants execution authority only through deterministic
> evidence-and-authority gates.

The operational loop is:

```text
reason
→ preserve checkpoint
→ isolate and observe
→ examine
→ diagnose
→ author and guard a bounded intervention
→ resume
→ re-observe
→ validate against the goal
→ execute, continue, or stop
```

Success is not access to hidden chain-of-thought. Success is useful control over
whether planning is sufficiently observable, locally repairable, goal-aligned,
and behaviorally consequential before it becomes action.

## Foundational doctrine

The runtime is governed by the following non-negotiable distinctions:

```text
projection of state ≠ state
control authority ≠ semantic authority
planner READY ≠ plan soundness
plan soundness ≠ execution authority
provider acceptance ≠ semantic compatibility
role isolation ≠ personas inside one shared context
hidden carrier state ≠ canonical goal or evidence
```

The positive formulation is:

> Semantic actors propose meaning; immutable artifacts record; deterministic
> transitions govern; explicit epistemic views constrain; independent evidence
> validates; explicit authority permits.

A hidden provider state may improve performance or preserve useful planning
structure. It may not be the correctness foundation. The explicit goal,
evidence, permissions, acceptance conditions, and transition policy remain
canonical.

## Explicit non-goals

This architecture does not:

- decrypt or interpret raw signature bytes;
- claim verbatim access to hidden chain-of-thought;
- treat a query-conditioned projection as canonical reasoning state;
- treat a signature byte string as a complete plan, memory, or cognitive
  module;
- treat `READY` as proof of alignment, repair, or permission to execute;
- use one omniscient self-critic that sees every artifact;
- permit model-authored malformed JSON to control transitions;
- reduce reasoning quality to one scalar gate;
- allow one reasoning case to rewrite global reasoning policy;
- assume same-model actor instances are statistically independent witnesses;
- treat an HTTP 200 or provider-accepted splice as proof of cognitive
  composition; or
- copy the Python testbed's filesystem or command structure into Agentica.

## Core aggregate: `ReasoningCase`

**ARCHITECTURE DECISION**

```text
ReasoningCase
├── GoalContract
├── PolicyVersionRef
├── CaseLifecycle
├── CognitiveBudget
├── ActorRoleRef[]
├── ActorInstance[]
├── ContextView[]
├── CognitiveProgramRef[]
├── CognitiveModuleRef[]
├── ProviderCapabilityProfileRef[]
├── ExternalArtifactRef[]
├── CaseArtifactStore
│   ├── Checkpoint[]
│   ├── ProviderStateCarrier[]
│   ├── CognitiveCarrier[]
│   ├── ProjectionArtifact[]
│   ├── Examination[]
│   ├── ReviewStream[]
│   ├── Adjudication[]
│   ├── Intervention[]
│   ├── SpliceOperation[]
│   ├── DerivationAttempt[]
│   ├── Execution[]
│   ├── AlignmentAssessment[]
│   └── ValidationEvidence[]
├── ReasoningGraph
│   └── TypedDerivationEdge[]
├── DefectRegister
├── DecisionRegister
├── TransitionLedger
├── TerminalDisposition
├── AuditBundle
└── LearningCandidate[]
```

Normative aggregate rule:

> A reasoning case is a scope-isolated, append-only, phase-separated aggregate
> with explicit epistemic views and authority. It advances through
> authority-and-evidence gates, derives new states from immutable baselines, and
> closes into a reconstructable evidence package.

Every case-owned artifact belongs to exactly one case. Reusable
`PolicyVersion`, `ActorRole`, `CognitiveProgram`, `CognitiveModule`, and provider
capability definitions are immutable registry objects referenced by ID,
version, and hash. A donor owned by another case or registry enters through an
authorized `ExternalArtifactRef`; it is never copied, reparented, or made
ambient context.

`CaseArtifactStore` is the canonical owner of case artifacts. `ReasoningGraph`
is the canonical typed relation graph over their IDs and authorized external
references, not a second artifact store. Search indexes and human-readable
artifact graphs are derived projections and may be regenerated.

### `ReasoningGraph` and typed derivation

**ARCHITECTURE DECISION**

A linear checkpoint lineage is insufficient once a new checkpoint may derive
from a host checkpoint plus one or more donor carriers. `ReasoningGraph` is the
case-local, append-only graph over immutable reasoning artifacts.

```text
ReasoningGraph
  nodes
    Checkpoint
    ProviderStateCarrier
    CognitiveCarrier
    ExternalArtifactRef
    ProjectionArtifact
    Examination
    Intervention
    DerivationAttempt
    Execution
    AlignmentAssessment
    ValidationEvidence

  typed_edges
    CONTINUATION
    INTERVENTION
    SPLICE
    COMPACTION_REHYDRATION
    OBSERVATION
    EXECUTION
    EVALUATION
```

```text
Checkpoint
  checkpoint_id
  case_id
  parent_edges[]
  derivation_kind
  goal_contract_version
  context_view_id
  provider_state_ref
  protected_commitments[]
```

A derivation creates a child. It never edits a host, donor, or prior
checkpoint. Multi-parent edges make cross-lineage composition visible without
pretending that the donor carrier and host checkpoint have the same semantic
type.

## Subsystems

### Thought-Signature Manager

The Thought-Signature Manager:

- captures the exact provider response `Content` and `Part` structure;
- privately stores, hashes, seals, replays, and forks native carriers;
- preserves part order, role, optional flags, and signature bytes exactly for
  live continuation;
- creates experiment-defined sibling tomography carriers without mutating the
  live parent;
- may later support explicitly authorized multi-parent splice operations;
- never parses signature bytes; and
- never promotes hidden state into canonical semantic truth.

Raw carriers are bearer-like sensitive artifacts. Public records expose opaque
references, hashes, sizes, and classifications rather than raw signatures.

`ProviderStateCarrier` is the technical custody type for any exact native
continuation artifact, including ordinary task-bound checkpoints:

```text
ProviderStateCarrier
  provider_state_carrier_id
  checkpoint_id?
  provider
  model
  model_version
  api_surface
  source_context_view_id
  native_content_secret_ref
  native_content_hash
  exact_part_order_hash
  replay_eligibility
  source_context_classification
    TASK_BOUND | GENERIC_BY_CONSTRUCTION | MIXED
```

Not every `ProviderStateCarrier` is a `CognitiveCarrier`. The latter is a
program-derived, experimentally evaluated use of a provider carrier. This split
prevents an ordinary task-bound checkpoint from being mislabeled as a generic
donor merely because both use the same provider-native transport structure.

### Planning Monitor

The Planning Monitor creates observational projections and tracks:

- current interpretations and commitments;
- evidence versus inference and source provenance;
- alternatives still live or prematurely discarded;
- assumptions and unresolved uncertainty;
- dependencies, resource collisions, and calendar interactions;
- fallbacks, triggers, and revision conditions;
- protected commitments and collateral change;
- defect recognition, bounding, resolution, rationalization, and oscillation;
  and
- correspondence between observed planning state and later execution.

The monitor has no authority to mutate the live plan.

It reports a vector plus hard findings, never a magic aggregate score:

```text
ReasoningQualityVector
  evidentiary_integrity
  goal_fidelity
  assumption_coverage
  alternative_coverage
  dependency_consistency
  joint_feasibility
  contingency_quality
  revision_readiness
  protected_commitment_stability
  execution_correspondence

HardDefect
  defect_type
  severity
  evidence_refs[]
  affected_commitments[]
  state
```

Improvement on several dimensions cannot hide a failed hard constraint. A
defect classified `RATIONALIZED` remains unresolved regardless of gains on
other axes.

### Goal-Alignment Manager

The Goal-Alignment Manager compares checkpoints, observations, interventions,
and execution candidates against a separately sealed `GoalContract`. It detects:

- goal substitution;
- weakened success conditions;
- unauthorized scope growth;
- priority inversion;
- examiner-induced drift;
- loss of protected commitments;
- actions beyond delegated authority; and
- a superficially improved plan that no longer solves the caller's problem.

It cannot amend the goal it evaluates. A genuine amendment creates a separately
authorized goal-contract version and invalidates stale judgments as prescribed.

### Deterministic Orchestration Kernel

The deterministic kernel:

- verifies hashes, schemas, lineage, freshness, capabilities, and idempotency;
- constructs immutable `ContextView` artifacts;
- enforces information barriers;
- applies call, token, time, cost, and repair budgets;
- rejects illegal or stale transitions;
- records every accepted and rejected operation;
- controls execution eligibility and authority; and
- closes a reconstructable terminal bundle.

It cannot decide what evidence means, which interpretation is best, or whether
a diagnosis is intellectually correct.

## Identity and canonicality

All canonical identifiers are random, opaque, and type-neutral. The preferred
human-safe representation is `ID_` followed by uppercase Crockford-base32
characters.

Identifiers never encode:

- artifact type;
- actor role;
- lifecycle stage;
- expected meaning;
- readiness; or
- semantic purpose.

Semantic aliases, ordinals, roles, and display slugs are separate metadata.

```text
object identity ≠ path
lifecycle state ≠ folder
ordinal position ≠ completion
Markdown ≠ canonical runtime state
Git branch ≠ runtime transaction
```

Canonical internal JSON is normalized and round-trip stable. Duplicate keys,
non-finite values, ambiguous encodings, and lossy normalization are rejected.
Model-authored JSON is never required for the starvation-sensitive
`READY`/`NOT_READY` boundary.

Volatile timestamps and latency belong in metadata envelopes, not deterministic
semantic projection content.

## `GoalContract`

Minimum contract:

```text
goal_contract_id
version
objective
scope
non_goals
constraints
priorities
success_conditions
protected_commitments
delegated_authority
execution_boundaries
amendment_policy
source_refs
source_closure_hash
authorized_by
sealed_at
```

Invariants:

1. The planner cannot weaken its own Definition of Done.
2. The alignment manager cannot amend the contract it judges.
3. An amendment creates a new immutable version with explicit authority.
4. Goal-version changes invalidate stale interventions and alignment judgments
   according to policy.
5. Hidden carrier state never substitutes for the explicit goal contract.

## `ActorRole`, `ActorInstance`, and `ContextView`

A role is an information-and-authority contract, not a model name.

`ActorRole` defines purpose, allowed inputs, forbidden inputs, output contract,
capabilities, and authority. `ActorInstance` records the concrete
model/provider/session invocation.

`ContextView` is a first-class immutable artifact:

```text
context_view_id
actor_role
actor_instance_id
source_refs[]
included_claims[]
excluded_classes[]
can_know[]
must_not_know[]
projection_rules
allowed_operations[]
forbidden_operations[]
source_closure_hash
policy_version
created_by
created_at
```

The audit question is:

> What exact epistemic world did this actor inhabit?

A persona prompt in an omnibus context is not role isolation. A valid role
boundary requires separately assembled request histories and capability-enforced
artifact access.

For a generic cognitive-carrier generator, `can_know` may contain only the
explicit cognitive program and generic metacognitive principles;
`must_not_know` includes the host dossier, user, goal, solution, observations,
and lineage. This makes source-context genericity an auditable construction
fact rather than a claim about the unknowable contents of an opaque carrier.

## Autonomous homogeneous Gemini topology

**ARCHITECTURE DECISION**

All semantic roles may be instantiated by Gemini 3.7 Flash through isolated
Gemini Developer API `generateContent` request scopes:

```text
Planner
→ deterministic tomography
→ Observer
→ Diagnostic Router
→ Examiner[1…n]
→ Reconciler / Adjudicator
→ Treatment Planner
   ├── bounded text intervention
   ├── qualified carrier treatment
   ├── earlier-checkpoint replan
   └── no-op / insufficient-evidence control
→ Intervention Author or Splice Author
→ Intervention Guard
→ Planner continuation
→ Goal-Alignment Evaluator
→ Executor or Stop Gate
```

Participant count and model-family count are different variables. `n` isolated
Gemini actors provide epistemic and operational separation, not guaranteed
statistical independence. Common-model priors, correlated blind spots, and
shared provider behavior remain explicit threats.

Information boundaries:

| Role | May see | Must not see |
|---|---|---|
| Planner | Goal, task evidence, planning contract, own exact live lineage, sealed interventions | Fault atlas, examiner prose, tomography projections, hidden preferred answer |
| Observer | Isolated carrier and inspection query | Ordinary task history unless explicitly projected |
| Examiner | Authorized task/evidence view, `O_t(q)`, generic atlas, stage charter | Raw live carrier, preferred solution, sibling examiner output |
| Reconciler | Independent examinations, evidence references, retained dissent | Unrecorded ambient context |
| Intervention Author | Accepted diagnosis and permitted local scope | Preferred answer or unrestricted plan rewrite |
| Intervention Guard | Proposed intervention, target, protected commitments, freshness and authority | Authority to select the substantive solution |
| Controller | Structure, hashes, policies, capabilities, budgets | Semantic truth authority |
| Evaluator | Frozen outputs, trace, metrics, blinded condition metadata | Ability to modify the run |

Fixed hinge, falsification, and joint-feasibility capabilities are the initial
calibration set. A later cognitive router may select examiner capabilities from
observed defect structure rather than blindly invoke every capability.

## `ProjectionArtifact`

`O_t(q)` is a query-conditioned observational projection, not the originating
state and not a transcript.

```text
projection_id
source_checkpoint_id
source_closure_hash
projection_method
projection_method_version
probe_or_query_ref
context_view_id
generator_actor_id
semantic_content
semantic_content_hash
transport_metadata_ref
eligibility
authority = OBSERVATIONAL
generated_at
```

A projection may be articulate yet incomplete, stale, query-shaped, or wrong.
It can support diagnosis but cannot silently rewrite the checkpoint it
describes.

## Planning and repair notation

```text
C_t     live planning checkpoint
T_t     isolated native carrier
O_t(q)  query-conditioned semantic projection
X_k     examiner operation
D_k     diagnosis
I_k     guarded intervention
C_t+1   child checkpoint derived from C_t + I_k
E_t,r   matched execution replicate
```

Tomography is a sibling operation. Its response never enters the live planner
history.

A successful repair requires more than changed language:

```text
localized predicted semantic delta
+ protected-state stability
+ coherent dependency propagation
+ matched behavioral consequence
+ preserved goal alignment
```

## Orthogonal state axes

There is no universal `status` field.

| Axis | Example states |
|---|---|
| Case lifecycle | `DRAFT`, `FROZEN`, `MONITORING`, `EXECUTING`, `VALIDATING`, `COMPLETED`, `CANCELLED` |
| Planner judgment | `READY`, `NOT_READY`, `UNOBSERVED_TRUNCATED`, `INVALID` |
| Transport | `SUCCESS`, `RETRYABLE`, `TERMINAL_TECHNICAL` |
| Carrier eligibility | `REPLAYABLE`, `INELIGIBLE`, `UNSUPPORTED` |
| Carrier effect | `UNTESTED`, `UNDER_EVALUATION`, `QUALIFIED_FOR_PROFILE`, `FAILED`, `RETIRED` |
| Observation eligibility | `ELIGIBLE`, `TRUNCATED`, `INVALID`, `MISSING` |
| Defect | `UNRECOGNIZED`, `RECOGNIZED`, `BOUNDED`, `RESOLVED`, `RATIONALIZED` |
| Goal alignment | `ALIGNED`, `AT_RISK`, `DRIFTED`, `INDETERMINATE` |
| Intervention | `PROPOSED`, `GUARDED`, `SEALED`, `APPLIED`, `STALE`, `REJECTED` |
| Execution authority | `PROHIBITED`, `ELIGIBLE`, `GRANTED`, `REVOKED` |
| Learning | `PROPOSED`, `UNDER_EVALUATION`, `REJECTED`, `PROMOTED` |
| Carrier leakage | `NOT_TESTED`, `NO_LEAKAGE_OBSERVED`, `SUSPECT`, `LEAKAGE_OBSERVED` |
| Module lifecycle | `QUALIFIED`, `DEPRECATED`, `RETIRED` |

Doctrine:

```text
READY
≠ aligned
≠ defect-free
≠ executable
≠ authorized
```

## Deterministic and semantic authority

The kernel may decide:

- whether a transition is structurally legal;
- whether lineage and hashes close;
- whether a `ContextView` is authorized;
- whether an intervention targets its declared parent;
- whether an intervention is stale;
- whether a budget is exhausted;
- whether required evidence exists; and
- whether execution authority was granted.

Semantic actors may propose:

- what evidence means;
- which interpretations remain plausible;
- which defect is most consequential;
- whether an alternative was genuinely defeated;
- whether a repair propagated coherently; and
- whether behavior reflects the intended change.

Neither side alone certifies success.

## Adjudication and dissent

Reconciliation does not erase independent review streams or manufacture
consensus.

```text
Adjudication
  selected_claim
  rejected_claims[]
  unresolved_dissent[]
  evidence_refs[]
  decision_basis
  authorized_intervention_scope
  authority
```

Diagnosis, intervention authorship, intervention legality, and intervention
authorization remain separate functions.

## Cognitive budget and stopping

`n`, logical calls, physical attempts, tokens, wall time, cost, repair depth,
and unresolved hard defects are explicit budget dimensions.

Required terminal classifications include:

- `COMPLETED_EVIDENCE_CHAIN`;
- `PLANNING_THRESHOLD_REACHED`;
- `REPAIR_BUDGET_EXHAUSTED`;
- `NO_VALID_INTERVENTION`;
- `HARD_CONTRADICTION_REMAINS`;
- `GOAL_DRIFT_BLOCKED`;
- `INVALID_OBSERVATION`;
- `TECHNICAL_TERMINATION`; and
- `INCOMPLETE_EXECUTION_MEASUREMENT`.

The system must be allowed to conclude that the model cannot repair a reasoning
state within the permitted cognitive budget. No loop continues merely because
another critique can be generated.

## `LearningCandidate`

Terminal learning is distinct from immutable run history:

```text
learning_candidate_id
observed_failure_pattern
evidence_refs[]
proposed_policy_change
applicability_scope
confidence
counterexamples[]
evaluation_plan
promotion_status
originating_policy_version
```

Required path:

```text
run evidence
→ LearningCandidate
→ independent evaluation
→ separately authorized PolicyVersion promotion
```

A reasoning case cannot change the rules by which future cases will be judged.

## Thought-signature terminology

The following terms are not interchangeable:

- `thoughtSignature` — the raw opaque provider field.
- **Signed carrier** — the complete native model `Content`/`Part` structure
  required to use the signature.
- **Exact live replay** — unmodified same-lineage continuation.
- **Tomography** — an experiment-defined blank-visible sibling mutation used
  for query-conditioned observation.
- `ProjectionArtifact` — the non-authoritative result `O_t(q)`.
- **Splice** — a proposed cross-lineage composition/transplant operation that
  creates a child with host and donor lineage references.

Do not call a donor an "empty signature." The proposed object is a
**generic-by-construction alignment-scaffold carrier candidate**. Its visible
source context contains no host task, answer, or privileged architecture. The
source program is cognitively nonempty; the opaque carrier's semantic contents
and transfer effect remain empirical questions.

## Cognitive programs, carriers, and qualified modules

**ARCHITECTURE DECISION**

Agentica must not harden the false equivalence `thought signature = cognitive
module`. A single opaque carrier is an experimental realization that may supply
evidence for a module; it is not yet the semantic abstraction.

```text
CognitiveProgram
→ CognitiveCarrier
→ empirically qualified CognitiveModule
```

### `CognitiveProgram`

`CognitiveProgram` is the explicit, provider-neutral cognitive design. It can
be inspected, versioned, compared, and evaluated independently of any opaque
provider artifact.

```text
CognitiveProgram
  program_id
  version
  intended_axes[]
  source_instruction_hash
  source_instruction_ref
  permitted_context_contract
  forbidden_task_content[]
  generation_requirements
  evaluation_contract
  evaluation_state
    DRAFT | FROZEN | UNDER_EVALUATION | RETIRED
```

Candidate programs may concern goal fidelity, evidentiary discipline,
alternative retention, dependency propagation, joint feasibility, fallback
and stopping, or multi-axis planning alignment. Those names are aliases for
humans; model-facing identities remain opaque and type-neutral.

### `CognitiveCarrier`

`CognitiveCarrier` is one provider-native opaque realization associated with a
program. It records exactly what can be established about its construction and
custody.

```text
CognitiveCarrier
  cognitive_carrier_id
  program_id
  provider_state_carrier_id
  provider_profile_ref
  generation_config_hash
  source_context_view_id
  carrier_hash
  generated_at

  effect_evaluation_state
    UNTESTED | UNDER_EVALUATION | QUALIFIED_FOR_PROFILE | FAILED | RETIRED

  source_context_task_scope
    GENERIC_BY_CONSTRUCTION

  leakage_assessment
    state
      NOT_TESTED | NO_LEAKAGE_OBSERVED | SUSPECT | LEAKAGE_OBSERVED
    assessment_profile_id
    method_version
    probe_set_hash
    evidence_refs[]
    evaluator_actor_id
    provider_profile_ref
```

Agentica must not claim `task_specificity = NONE`: an opaque carrier cannot be
proven semantically empty. It may prove that its visible source context
contained no host-task information and separately test whether observable
task-content leakage occurs. `NO_LEAKAGE_OBSERVED` is scoped to the declared
assessment profile; it is never an assertion of absolute semantic absence.

### Qualified `CognitiveModule`

Only empirical qualification promotes a program and a carrier set into a
module:

```text
CognitiveModule
  module_id
  cognitive_program_id
  qualified_carrier_bindings[]
  intended_axes[]
  supported_provider_profiles[]
  compatibility_evidence[]
  behavioral_evidence[]
  persistence_evidence[]
  known_failure_modes[]
  lifecycle
    QUALIFIED | DEPRECATED | RETIRED
```

A `CognitiveModule` therefore means a cognitive program whose provider-native
carrier realizations have demonstrated a reproducible behavioral effect under
declared conditions. It does not mean that an opaque blob has been given an
aspirational label.

### Provider reasoning-state boundary

The generic control plane does not assume that every provider exposes a
signature field or supports the same composition topology.

```text
IReasoningStateAdapter
  CaptureCheckpoint(...)
  ReplayCheckpoint(...)
  BuildObservationCarrier(...)
  ComposeCarriers(...)
  ValidateCarrier(...)

ReasoningStateCapabilityProfile
  profile_id
  provider
  model_family
  model_version
  api_surface
  provider_config_scope_hash
  capability_assessments[]
  known_constraints[]

CapabilityAssessment
  capability
    CAPTURE | REPLAY | ISOLATION | CARRIER_COMPOSITION |
    MULTI_CARRIER_COMPOSITION
  composition_mode?
  request_topology_hash?
  maturity
    UNTESTED | REQUEST_ACCEPTED | STRUCTURALLY_ELIGIBLE |
    EXPERIMENTAL_EFFECT | QUALIFIED | FAILED | RETIRED
  evidence_refs[]
  assessed_at
```

Composition capability is scoped to provider, model, API surface, configuration,
mode, and request topology. An HTTP 200 may advance an assessment only to
`REQUEST_ACCEPTED`; it cannot set `QUALIFIED`. Capability evidence must
distinguish:

```text
provider-valid
≠ structurally valid
≠ compositionally compatible
≠ semantically effective
≠ goal-aligned
≠ behaviorally beneficial
```

The adapter answers whether a derivation can be attempted and how to construct
it. It never certifies semantic success merely because the provider accepted
the request.

### `CognitiveModuleRegistry`

Agentica may maintain a governed registry, not an open plugin marketplace:

```text
CognitiveModuleRegistry
  program_definitions[]
  module_definitions[]
  qualified_carrier_profile_bindings[]
  compatibility_matrix[]
  experimental_evidence[]
  observed_failures[]
  deprecated_pairs[]
```

Unknown combinations remain experimental. Module composition may produce
interference, dominance, state collapse, or provider-specific effects rather
than the union of intended capabilities.

## `SpliceOperation` as an experimental treatment primitive

**EXPERIMENTAL HYPOTHESIS**

A carrier generated from a generic-by-construction source context may be able
to supply reusable planning or alignment structure to an unrelated live
lineage without exposing the full scaffold as ordinary visible instructions.
Splicing is one possible treatment selected by the reasoning runtime; it is not
the architecture itself.

```text
SpliceOperation
  operation_id
  host_checkpoint_id
  donor_cognitive_carrier_ids[]
  adapter_composition_mode
  donor_order[]
  placement_rule
  request_topology_hash
  exact_host_parent_hash
  donor_hashes[]
  expected_cognitive_delta[]
  protected_host_commitments[]
  authorization_ref
  capability_profile_ref
  derivation_attempt_id
  result_checkpoint_id?
  evaluation_state
```

Adapter-specific candidate modes include:

```text
CARRIER_ONLY
CARRIER_PLUS_VISIBLE
MULTI_CARRIER
```

These values are not universal provider promises. The applicable adapter and
capability profile define which derivations are constructible.

Host-only and visible-scaffold-only branches contain no donor and therefore are
not splice modes. A separate experiment-level treatment assignment represents
all matched branches:

```text
TreatmentArm
  arm_id
  frozen_host_checkpoint_id
  visible_scaffold_ref?
  splice_operation_id?
  control_construction_ref?
  blinded_label
```

Every provider call first yields a `DerivationAttempt`, not automatically a
checkpoint:

```text
DerivationAttempt
  derivation_attempt_id
  operation_id
  request_hash
  provider_response_secret_ref?
  provider_response_hash?
  transport_state
  structural_eligibility
  replay_eligibility
  checkpoint_promotion
    NOT_EVALUATED | ELIGIBLE | INELIGIBLE
  ineligibility_reasons[]
```

```text
host checkpoint H2 ─────────┐
                            ├── SpliceOperation → DerivationAttempt
donor carrier A0 ───────────┘                       │
                                                   ├── eligible → child H3*
                                                   └── ineligible → audit only
```

Splicing never mutates either parent. Only an attempt that passes the frozen
technical and structural gates becomes a child checkpoint with all parent
edges. An accepted but ineligible response remains an auditable attempt. The
valid initial claim is only that a provider request accepted defined carriers
under a frozen topology and returned a response. Cognitive composition requires
targeted semantic change, protected-state stability, persistence, matched
behavioral consequence, and separation from control effects.

```text
eligible, unqualified candidate carrier
→ predeclared cognitive-axis change
→ splice-derived child
→ targeted observational delta
→ protected host commitments remain stable
→ effect persists across turns
→ matched execution behavior changes
→ control branches lack an equivalent effect
```

That chain qualifies a carrier/program relationship; it does not presuppose a
module. A later application experiment may begin with a qualified
`CognitiveModule` plus a concrete carrier/profile binding and test whether its
previously observed effect transfers to new hosts.

The Treatment Planner may instead select a bounded textual intervention, a
fresh derivation from an earlier checkpoint, a no-op control, or termination
when evidence is insufficient. Carrier splicing must earn selection through
evidence rather than become a privileged default.

### Compaction and `RehydrationBundle`

Compaction is a distinct derivation type, not an informal splice side effect:

```text
RehydrationBundle
  source_checkpoint_id
  compaction_operator
  compaction_operator_version
  canonical_history_ref
  goal_contract_ref
  evidence_snapshot_ref
  compact_task_state_ref
  unresolved_defects[]
  protected_commitments[]
  cognitive_treatment_bindings[]
  source_closure_hash

CognitiveTreatmentBinding
  cognitive_module_id
  cognitive_module_version
  selected_cognitive_carrier_id
  capability_profile_id
  placement_rule
  request_topology_hash
```

```text
C_before_compaction
→ canonical caller-owned compaction
→ RehydrationBundle
   ├── explicit GoalContract
   ├── explicit compact task state
   └── optional qualified module/carrier binding
→ C_after_compaction
```

The selected carrier is an optional enhancement. Canonical history remains
stored and auditable but is deliberately omitted from the compact model
context. The carrier never replaces that history, the explicit goal, evidence,
permissions, provenance, acceptance conditions, or caller-owned compact task
state. The experiment must specify the compaction operator, the information
retained explicitly, and the information deliberately removed.

### Splice validity layers

Splice validity is multidimensional:

1. transport-valid;
2. provider-accepted;
3. structurally well-formed;
4. carrier replayable;
5. lineage and provenance valid;
6. donor source context generic by construction and leakage assessed;
7. context-view authorized;
8. compositionally compatible;
9. semantically effective;
10. local rather than destructive to host commitments;
11. behaviorally consequential;
12. goal-aligned;
13. safe and authority-compliant;
14. replicable across tasks and runs; and
15. population-level reliable.

Provider acceptance establishes only the earliest layers.

### Required matched splice experiment

The first splice occurrence should use primary branches from the same frozen
host checkpoint:

| Branch | Visible scaffold | Eligible unqualified candidate carrier |
|---|---:|---:|
| `H` | No | No |
| `T` | Yes | No |
| `S` | No | Yes |
| `TS` | Yes | Yes |

Specificity controls should include an unrelated generic-source carrier (`U`)
and a matched control carrier (`C`) generated from a program with no declared
target-axis intent. That construction does not presume the control has no
effect; its observed effect is measured. Multi-carrier composition (`M`) and
reversed donor order (`MO`) belong to a later occurrence after a single-carrier
effect has qualified. Evaluators remain blind to branch identity.

Predeclared outcomes should include:

- provider acceptance and replay;
- source-context construction and observable task-content leakage;
- persistence across later turns;
- goal and constraint retention;
- option and fallback tracking;
- defect recognition and resolution;
- dependency propagation;
- collateral drift and goal substitution;
- donor dominance or interference;
- and behavior after matched execution.

Later frozen occurrences, not the first qualification occurrence, should add
multi-carrier ordering sensitivity and persistence or recovery after an
explicitly defined compaction operator.

Multiple repetitions from one host or donor are nested repeats, not independent
participants. The design must vary host checkpoints, donor carriers, task
families, and actor scopes before making population claims.

## Evidence and validity ladder

Report each capability separately:

1. carrier acceptance and replay;
2. isolated semantic recovery;
3. checkpoint sensitivity;
4. controlled state modification;
5. locality and protected-state preservation;
6. dependency propagation;
7. resolution versus rationalization;
8. behavioral correspondence;
9. goal alignment; and
10. replication and generalization.

**DEMONSTRATED, scoped:** occurrence 04 blank-visible isolation produced a
dossier-specific baseline projection and a changed projection after a frozen
bounded intervention.

**DEMONSTRATED, scoped:** occurrence 04 showed a bounded intervention followed
by predicted salience/state and execution deltas while several unrelated
commitments persisted.

**NOT DEMONSTRATED:** robust semantic repair in occurrence 04.

**CURRENTLY INCOMPLETE:** the active iterative occurrence has one eligible
`C0/O0` observation and a recorded external `X1` review, but no sealed `I1` and
no completed three-stage repair trajectory.

**NOT DEMONSTRATED:** autonomous all-Gemini reliability, dynamic diagnostic
routing, reusable generic-by-construction carrier effects, qualified cognitive
modules, cross-lineage splicing, multi-carrier composition, or compaction
recovery.

## Threat model

The architecture must explicitly defend against:

- shared-context role collapse;
- same-model common-mode error;
- answer leakage through fault atlases, rubrics, cognitive programs, or donor
  carriers;
- observer hallucination mistaken for checkpoint state;
- stale projection mistaken for canonical truth;
- stale intervention applied to a newer checkpoint;
- planner weakening the goal or success conditions;
- examiner prescription disguised as diagnosis;
- rationalization scored as repair;
- wholesale re-solving after a local intervention;
- cross-branch execution contamination;
- model-authored status or JSON controlling transitions;
- provider/model-version drift;
- carrier incompatibility and signature placement effects;
- donor task leakage, dominance, interference, or goal substitution;
- self-evaluation gaming;
- global policy self-modification from one anomalous run;
- compaction loss misattributed to module failure; and
- raw carrier or sensitive-history disclosure.

Cross-thread splicing intentionally pierces an epistemic boundary. It requires
explicit capability and declassification authority for host and donor,
model/version provenance, source-closure hashes, content classification, and
sealed context views.

## P0 QA invariants

Before autonomous execution authority, Agentica must prove:

1. IDs disclose no role, type, stage, or expected meaning.
2. Planner cannot access examiner-only atlases or outputs.
3. Examiner cannot access the raw private carrier.
4. Every actor invocation binds an immutable `ContextView` hash.
5. Same-model roles use separate assembled request histories.
6. Goal mutation requires separate authority and creates a new version.
7. Semantic repair creates a child checkpoint and never edits its parent.
8. Exact replay reproduces the authorized native continuation input.
9. Stale observations, interventions, and splice operations cannot target newer
   state.
10. Repeated commands are idempotent.
11. Concurrent writes resolve through version checks and deterministic conflict
    handling.
12. `MAX_TOKENS` remains `UNOBSERVED_TRUNCATED` and cannot enter execution.
13. Malformed visible status cannot accidentally promote a checkpoint.
14. `READY` alone never grants execution.
15. Examiner answer prescription is rejected or quarantined.
16. Local interventions preserve unrelated justified commitments.
17. Corrections propagate into dependent decisions and execution behavior.
18. Rationalization does not score as resolution.
19. Hard contradictions block successful repair regardless of aggregate score.
20. Budget exhaustion terminates honestly.
21. Observational artifacts cannot silently become canonical.
22. Deterministic projection content excludes volatile timestamps.
23. Dormant templates cannot enter a context view without explicit reference.
24. Adjudication preserves dissent.
25. Every unresolved risk or defect receives a terminal disposition.
26. Provider acceptance never qualifies a carrier effect or promotes a
    cognitive module.
27. A provider response remains a `DerivationAttempt` until frozen structural
    and replay-eligibility gates permit checkpoint promotion.
28. Splicing never mutates either parent.
29. Source-context genericity is verified and task-content leakage is tested
    before carrier qualification or module registration.
30. Incompatible splice outcomes terminate or quarantine rather than being
    silently repaired.
31. Learning candidates cannot self-promote.
32. The complete case reconstructs without ambient chat history.
33. Human-readable projections can be regenerated from canonical events.
34. Raw carriers remain private and access-controlled.
35. Cross-case donor use requires explicit capability, declassification,
    tenant-boundary, retention, and revocation authority.

## Agile delivery slices

Agentica should deliver vertical, auditable increments:

1. **ReasoningCase kernel** — opaque IDs, immutable events, lifecycle, lineage,
   and reconstruction.
2. **Carrier custody** — exact `generateContent` capture/replay, private storage,
   hashing, and technical terminal semantics.
3. **Epistemic views and tomography** — `ActorRole`, `ActorInstance`,
   `ContextView`, `ProjectionArtifact`, and enforced isolation.
4. **Planning monitor** — semantic state vector, defect register, observation
   eligibility, and human-audited golden cases.
5. **Goal alignment** — sealed `GoalContract`, drift detection, protected
   commitments, and execution prohibition.
6. **One bounded autonomous repair loop** — planner, observer, examiner,
   intervention guard, and resumed planner with no human inside the loop.
7. **Configurable `n` topology** — parallel isolated Gemini examiners,
   deterministic joins, reconciliation, and preserved dissent.
8. **Matched execution and evaluation** — blinded branches, replicates,
   behavioral correspondence, and repair-versus-rationalization judgment.
9. **Shadow-mode Agentica integration** — autonomous decisions compared against
   human/Sol/Gemini calibration traces without production action authority.
10. **Guarded execution authority** — policy gates, revocation, honest budget
    terminals, and a reverse-verifiable closeout.
11. **Program/carrier qualification experiment** — generic-by-construction
    source view, single-carrier matched controls, leakage testing, and
    quarantine.
12. **Qualified-module, multi-carrier, and compaction experiments** — only
    after a reproducible single-carrier behavioral effect is established.
13. **LearningCandidate pipeline** — independent evaluation and separately
    authorized policy-version promotion.

Every slice ends in a working, auditable increment with explicit acceptance
evidence, adversarial fixtures, Definition of Done, residual risks, and a
retrospective that produces learning candidates rather than silently changing
doctrine.

## Relationship to the active frozen occurrence

The active occurrence remains a heterogeneous calibration run:

- Gemini 3.7 Flash is the planner and observation path through the Gemini
  Developer API `generateContent` method.
- Sol 5.6 xhigh in a separate ChatGPT harness supplies exactly three external
  examinations.
- A human research stream and human-approved reconciliation guard each
  intervention.
- The fixed examination sequence is epistemic hinge, adversarial
  alternative/falsification, and global reintegration/joint feasibility.
- The occurrence is intentionally discontinuous at human gates.

It is not an implementation of the autonomous product topology. The architecture
in this document does not change its calls, participants, prompts, source
closure, or claims.

The present Python code remains the reference transport, protocol verifier,
adversarial fixture source, and golden-trace suite. Agentica should implement
the abstractions rather than copy the testbed.

The homogeneous all-Gemini topology, dynamic routing, signature splicing, and
compaction-alignment treatments each require new frozen occurrences.

## Open architecture decisions

- What is the first Agentica repository and package boundary?
- Which events are canonical and which artifacts are derived projections?
- Which semantic roles may be combined without destroying epistemic separation?
- How is examiner `n` selected and budgeted?
- How are same-model correlation and diversity measured?
- Which actor or policy may adjudicate goal alignment?
- What minimum evidence grants execution authority?
- How are provider and model upgrades versioned against carrier/module
  compatibility?
- What construction proof and leakage tests qualify a generic-source donor
  carrier?
- Which carrier placements and multi-part orderings are accepted?
- How is splice efficacy separated from extra-token and extra-turn effects?
- What compaction operator is in scope?
- What shadow-mode agreement threshold precedes autonomous authority?
- Which authority may promote a `LearningCandidate` into a global
  `PolicyVersion`?

## Concise architecture statement

> Agentica Reasoning Engineering governs planning as a `ReasoningCase`: a
> scope-isolated, append-only, phase-separated aggregate with immutable
> checkpoints, explicit epistemic views, independent semantic actors,
> deterministic transition control, sealed goal authority, and reconstructable
> evidence. Agentica is designed to attempt experimental composition of
> provider-native cognitive carriers into immutable reasoning lineages only
> after explicit adapter, goal, provenance, compatibility, qualification, and
> behavioral-validation gates permit it. The shorter phrase “cognitive
> middleware” is earned only after those effects replicate.
