# Agentica Fresh-Context Reasoning-Architecture Review

## Purpose

This is a clean-room review brief for a new context opened inside the actual
Agentica repository. The review is architectural and evidentiary. It must not
implement code, modify the repository, or silently turn experimental findings
into product capabilities.

The question is not whether the candidate design sounds sophisticated. The
question is:

> Does the proposed Reasoning Engineering architecture fit Agentica's real
> domain model and control plane, preserve the demonstrated scientific
> findings, and expose the unproven carrier-composition ideas as testable,
> governable capabilities rather than magical primitives?

## Review packet

Provide the fresh context with these files:

1. `README.md` — the current project-level synthesis, limits, and post-freeze
   provenance note.
2. `AGENTICA_FRESH_CONTEXT_ARCHITECTURE_REVIEW.md` — this review contract.
3. `AGENTICA_REASONING_ENGINEERING_ARCHITECTURE.md` — the candidate product
   abstraction to evaluate.
4. `AGENTICA_REASONING_ENGINEERING_EVIDENCE_INDEX.md` — the claim-to-source map,
   exact evidence identities, and audit limit.
5. `MODERNIZATION_REASONING_ENGINEERING_OCCURRENCE_04_ADJUDICATION.md` — the
   completed bounded-intervention evidence and its limitations.
6. `MODERNIZATION_REASONING_ENGINEERING_DESIGN.md` — the completed occurrence's
   frozen protocol-level design.
7. `MODERNIZATION_ITERATIVE_REASONING_ENGINEERING_DESIGN.md` — the current
   three-examination calibration protocol, not a finished product design.
8. `AGENTICA_FRESH_CONTEXT_PACKET.sha256` — the byte identities of the seven
   documents above.

If the evaluator needs to audit lower-level provenance, add the relevant frozen
manifest, preregistration, and result artifacts. Do not substitute a large
archive for the seven-document conceptual packet unless the evaluator explicitly
requests an evidence audit.

Verify the packet manifest before review. The Agentica repository itself is the
authoritative source for Agentica's existing abstractions, conventions, package
boundaries, persistence model, event model, and agent lifecycle. The candidate
document is external input, not authority over the repository.

## Evidence boundary the evaluator must preserve

### Demonstrated, with limited scope

- In occurrence 04, the transport captured complete provider-native model
  content and replayed the authorized live-parent content unchanged when
  constructing continuation requests; both live planning branches reached
  eligible `READY` checkpoints.
- In occurrence 04, a blank-visible derivative of an exact captured signed
  carrier yielded a dossier-specific baseline projection and a changed
  projection after the frozen bounded intervention.
- A completed occurrence produced predicted semantic and execution deltas after
  a bounded intervention, while preserving several unrelated commitments.

### Not demonstrated

- Verbatim or canonical access to hidden chain-of-thought.
- General semantic fidelity of every projection.
- Robust autonomous repair.
- Reliable all-Gemini multi-actor supervision.
- A reusable generic cognitive-carrier effect.
- A qualified `CognitiveModule`.
- Cross-lineage carrier splicing, multi-carrier composition, or recovery after
  compaction.
- Production-safe autonomous execution authority.

The active iterative occurrence is incomplete and must not be cited as a
completed repair result.

## Abstraction correction under review

The review must preserve this separation:

```text
CognitiveProgram
→ CognitiveCarrier
→ empirically qualified CognitiveModule
```

- `CognitiveProgram` is the explicit, provider-neutral cognitive design.
- `CognitiveCarrier` is one opaque provider-native realization with construction
  provenance and leakage assessment.
- `CognitiveModule` exists only after reproducible semantic and behavioral
  qualification across a declared carrier set and provider profile.

Do not accept `task_specificity = NONE` for an opaque carrier. The auditable
construction fact is `source_context_task_scope = GENERIC_BY_CONSTRUCTION`,
followed by a scoped leakage assessment such as
`NO_LEAKAGE_OBSERVED` under a declared method, probe set, evaluator, evidence
set, and provider/model profile. It is not an absolute `CLEAN` claim.

Also preserve:

- `ReasoningCase` as the scope-isolated governance aggregate;
- `ReasoningGraph` with typed, potentially multi-parent derivation edges;
- a provider `IReasoningStateAdapter` and evidence-backed capability profile;
- `ProjectionArtifact` as observational, never canonical state;
- `ReasoningQualityVector` plus `HardDefect[]`, never one quality scalar;
- separately sealed `GoalContract` and goal-alignment authority;
- explicit actor `ContextView` information rights;
- deterministic transition authority separated from semantic authority;
- treatment selection among text, carrier, earlier-checkpoint replan, no-op, or
  stop;
- `RehydrationBundle` for explicit compaction recovery;
- `LearningCandidate` review before any global policy promotion; and
- a governed module registry, not a cognition-plugin marketplace.

## Review procedure

### 1. Inspect Agentica before judging fit

Read repository-level instructions and the smallest sufficient set of actual
Agentica source and architecture documents. Identify the existing aggregate
roots, agent/session/run types, event or state persistence, provider adapters,
tool/capability model, authorization model, evaluation facilities, and
extension boundaries.

Do not infer Agentica's architecture from its name, README summary, or the
candidate proposal.

### 2. Map instead of rename

For each proposed type, determine whether Agentica already has:

- a directly suitable abstraction;
- a suitable abstraction that needs a narrow extension;
- a conflicting abstraction;
- no equivalent; or
- an abstraction that should remain outside Agentica's core.

At minimum map:

```text
ReasoningCase
ReasoningGraph
Checkpoint
TypedDerivationEdge
ProviderStateCarrier
GoalContract
ActorRole
ActorInstance
ContextView
ProjectionArtifact
ReasoningQualityVector
HardDefect
CognitiveProgram
CognitiveCarrier
CognitiveModule
CognitiveModuleRegistry
IReasoningStateAdapter
ReasoningStateCapabilityProfile
SpliceOperation
RehydrationBundle
LearningCandidate
TreatmentPlanner
InterventionGuard
DeterministicOrchestrationKernel
```

Prefer Agentica's established vocabulary where it preserves the invariants.
Reject superficial renaming that hides a semantic mismatch.

### 3. Audit control and information boundaries

Verify that the proposed design can enforce, rather than merely prompt:

- separate request histories for isolated semantic actors;
- explicit `CAN_KNOW` and `MUST_NOT_KNOW` context rights;
- immutable parent checkpoints and append-only derivations;
- opaque, type-neutral identifiers;
- exact provider-native carrier custody without parsing signature bytes;
- stale-artifact rejection;
- goal amendments through separate authority;
- `READY` independent from alignment and execution permission;
- honest `MAX_TOKENS` and invalid-status terminals;
- configurable participant count `n` without claiming witness independence;
- retained dissent and reconstructable adjudication; and
- no self-promotion from one run into global policy.

Also inspect Agentica's actual tenant boundary, secret-storage mechanism,
retention and revocation rules, provider data boundary, and authorization model
for crossing host/donor carrier scopes. A prompt-level prohibition is not a
security boundary.

### 4. Challenge the carrier-composition hypothesis

Treat carrier splicing as an experimental provider capability and one treatment
primitive. Ask:

- What exact request topology would the provider adapter construct?
- Which facts establish transport acceptance, replayability, structural
  validity, semantic effect, behavioral effect, persistence, alignment, and
  safety separately?
- How would same-host `H/T/S/TS` controls, unrelated carriers, matched
  non-target-axis control carriers, blinded evaluation, and later
  multi-carrier/order tests be represented without presuming that an opaque
  control is a semantic no-op?
- What explicit capability and declassification authority permits a
  cross-lineage edge?
- How are donor leakage, dominance, interference, or state collapse detected?
- What negative result would retire or quarantine the capability?

An HTTP 200, an articulate projection, or a higher aggregate score is not proof
of composition.

### 5. Identify the smallest real vertical slice

Recommend one auditable Agentica increment that exercises existing product
surfaces while minimizing speculative machinery. The default candidate is:

```text
sealed GoalContract
→ one planner checkpoint through the native provider adapter
→ immutable carrier custody
→ one isolated ProjectionArtifact
→ one independent diagnostic actor
→ one guarded text intervention
→ child checkpoint
→ re-observation and matched evaluation
→ no production execution authority
```

Carrier splicing should not be the first implementation slice unless the actual
Agentica architecture makes the prerequisite custody, graph, context, and
evaluation controls already complete.

## Required output

Return a review, not a rewritten manifesto, with these sections:

1. **Verdict** — `ADOPT`, `ADOPT_WITH_CHANGES`, `REWORK`, or `REJECT`, with the
   controlling reason.
2. **Repository and packet identity** — packet hashes, Agentica HEAD, dirty
   state, exact repository files, and relevant symbols inspected.
3. **Strong convergence** — candidate abstractions already supported by
   Agentica.
4. **Conflicts and category errors** — where the proposal misreads the actual
   system.
5. **Abstraction mapping table** — proposed type, Agentica equivalent, gap,
   disposition.
6. **Evidence-claim audit** — demonstrated, architecture decision,
   experimental hypothesis, overclaim, or `NOT_AUDITABLE_FROM_PACKET`.
7. **Hard defects and risks** — prioritized, evidence-backed, and localizable.
8. **Recommended first vertical slice** — interfaces, canonical events,
   acceptance tests, and Definition of Done.
9. **Experimental backlog** — especially carrier qualification, splicing, and
   compaction, kept separate from product implementation.
10. **Open decisions requiring the human owner** — only choices that materially
    change scope or product direction.

Preserve disagreement. Do not manufacture consensus with the candidate authors
or infer approval from conceptual similarity.

## Verbatim launch prompt

Use this in the new Agentica context after attaching the review packet:

> Perform the fresh-context architecture and evidence review defined in
> `AGENTICA_FRESH_CONTEXT_ARCHITECTURE_REVIEW.md`. Begin by inspecting the
> actual Agentica repository and its instructions. Verify and report the packet
> hashes, Agentica HEAD, and dirty state; treat the candidate
> Reasoning Engineering architecture as external input rather than authority.
> Do not implement or edit anything. Map the proposed abstractions to the real
> system, preserve the demonstrated-versus-hypothesized boundary, challenge
> carrier composition as an unproven treatment capability, and return the exact
> required review structure. Mark claims that cannot be independently checked
> from the supplied evidence as `NOT_AUDITABLE_FROM_PACKET`. I want independent
> correction, not agreement.
