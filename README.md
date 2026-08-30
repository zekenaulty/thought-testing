# thought-testing

Controlled black-box experiments on opaque provider-native LLM continuation
artifacts and the practical discipline we call **reasoning engineering**.

## Current conclusion: do not model this as ViewState

A Gemini `thoughtSignature` is not a transparent, self-describing serialization
of model cognition. There is no documented object schema here that this project
can deserialize into the model's exact beliefs, variables, plan, or hidden
chain-of-thought.

The experimentally usable object is also not the bare signature byte string. It
is the complete provider-native signed `Content`/`Part` carrier, together with
its part order, role, provider, model, API surface, generation configuration,
request topology, and lineage.

The central measurement is a new model inference from a protocol-defined
derivative of that carrier:

```text
C_t     live planning checkpoint, including its exact native response
N_t     exact captured provider-native signed carrier within C_t
T_t     isolate(C_t): sibling derivative of N_t with visible text blanked,
        signature/topology preserved, and ordinary task/history withheld
O_t(q)  new, query-conditioned projection returned after query q is appended to T_t
```

Exact live replay and observation are different operations:

- **Live continuation** preserves the authorized parent `Content` unchanged and
  appends only the permitted continuation or intervention input.
- **Tomography** constructs the isolated sibling `T_t` and appends query `q`.
  Its response `O_t(q)` never enters the live planner history.

`O_t(q)` can be detailed and experimentally useful without being the original
state. It may be incomplete, probe-shaped, stale, or wrong. The signature bytes
remain opaque throughout.

The experiments cannot distinguish direct retrieval, provider-conditioned
reconstruction, or a mixture of both. “State,” “checkpoint,” and “carrier” name
an experimentally observable continuation interface and lineage—not an
implementation theory about what Gemini stores.

| A ViewState-like interpretation would imply | The evidence here supports |
|---|---|
| A decodable, field-level serialization | An opaque native carrier usable only through provider inference |
| A complete, canonical snapshot | A scoped, query-conditioned projection |
| Passive retrieval of stored fields | A new model call over a controlled carrier derivative |
| A portable blob with stable semantics | Evidence only under a declared provider/model/API/configuration/topology |
| Exact reconstruction of arbitrary state | Relational semantic recovery in some tasks; complete detached-carrier exact-ledger recovery failed in the S0–S6 protocol |

The practical object of study is therefore a control loop, not a state viewer:

```text
preserve checkpoint
→ isolate and project
→ diagnose a reasoning relationship
→ apply a bounded intervention to the untouched live lineage
→ re-project
→ compare predicted semantic and behavioral consequences
→ continue, execute, or stop under explicit authority
```

## What we found

The claims below are deliberately scoped.

1. **Exact capture and authorized replay worked in occurrence 04.** Through the
   Gemini Developer API `generateContent` method on `gemini-3.7-flash`, the
   transport preserved complete live-parent content when constructing
   continuation requests. Both baseline and adjusted planning branches reached
   eligible `READY` checkpoints.
2. **Blank-visible isolation recovered useful dossier-specific semantics.** A
   planning turn whose only visible status was `READY` yielded a detailed
   projection of interpretations, commitments, alternatives, dependencies,
   uncertainties, and revision triggers after task/history suppression and
   signed-carrier isolation.
3. **A bounded intervention produced a predicted local semantic change.** The
   adjusted projection made the targeted coupling among cost, staffing, and
   calendar assumptions more explicit.
4. **Multiple unrelated commitments survived, and the targeted change propagated
   into matched behavior.** Several protected architectural and governance
   commitments persisted after intervention. All three adjusted execution
   replicates more explicitly exposed cost ranges, funding provenance, and
   conditioned legacy/security fallbacks.
5. **`READY` was contradicted as substantive validation.** Both baseline and
   adjusted states emitted `READY`; isolation showed improvement without robust
   resolution of the diagnosed relationship.
6. **The exact-state failure was informative.** The native S0-S6 experiment did
   not recover an exact synthetic ledger or localize changed transitions from
   detached carriers. That is a construct boundary for mathematical state
   reconstruction, not evidence that reasoning semantics are absent.

The strongest completed result is occurrence 04. Its public adjudication is
[`thoughtlab/reasoningEngineering/MODERNIZATION_REASONING_ENGINEERING_OCCURRENCE_04_ADJUDICATION.md`](thoughtlab/reasoningEngineering/MODERNIZATION_REASONING_ENGINEERING_OCCURRENCE_04_ADJUDICATION.md),
and its claim-to-source map is
[`thoughtlab/reasoningEngineering/AGENTICA_REASONING_ENGINEERING_EVIDENCE_INDEX.md`](thoughtlab/reasoningEngineering/AGENTICA_REASONING_ENGINEERING_EVIDENCE_INDEX.md).
The verified final seal hash is
`613996094ab2379fec7f34935c391c3fc8ce2c7ddd04f561b87c35c865b3f2de`.

## What we did not find

This repository does **not** establish:

- decoded, verbatim, complete, or canonical hidden chain-of-thought;
- a ViewState-like serialization or a universal, stable, query-independent
  readout;
- that a bare `thoughtSignature` is sufficient, that every carrier is
  replayable, or that carriers are portable across provider/model/API/config
  profiles;
- a one-to-one mapping from opaque bytes to recovered semantic claims;
- general fidelity or completeness of tomography projections;
- robust semantic repair in occurrence 04—the adjusted plan still contained
  favorable-range/vendor-offset assumptions and unresolved calendar coupling;
- replication across task families, independent participants, models, or a
  population;
- statistical independence among isolated actors using the same model family;
- a reusable generic cognitive carrier, a qualified `CognitiveModule`,
  cross-lineage carrier splicing, multi-carrier composition, or compaction
  recovery;
- a reliable autonomous all-Gemini reasoning supervisor; or
- production-safe execution authority.

An HTTP 200, exact transport acceptance, articulate projection, higher rubric
score, or `READY` token proves none of the later claims by itself.

## Completed occurrence 04

The completed reasoning-engineering loop was:

```text
complex modernization dossier
→ private scaffolded baseline checkpoint C0
→ raw READY
→ blank-visible isolated carrier
→ baseline projection O0(q)
→ sealed diagnosis, prediction, and bounded intervention
→ adjusted child checkpoint C1 from the untouched live parent
→ adjusted projection O1(q)
→ three baseline and three adjusted execution continuations
→ human semantic adjudication
```

All ten physical calls returned HTTP 200 on their first attempt, both isolated
observations were eligible, all six matched execution continuations were
eligible, and the terminal was `COMPLETED_EVIDENCE_CHAIN`. Transport and seal
validity do not replace the semantic limitations listed above. The three
replicates in each branch are nested repetitions from one frozen host, not six
independent participants.

## Current iterative occurrence

The active design extends the loop across three bounded examinations and
potential interventions:

```text
C0 → O0 → X1/I1 → C1 → O1 → X2/I2 → C2 → O2 → X3/I3 → C3 → O3
```

Current status is intentionally incomplete:

- freeze `15865775a8ea7bd18461793888d8622c86dd9567ea71ebad2c3da81c6a8bf134`
  remains valid;
- `C0/O0` is valid with exactly two physical calls;
- one external `X1` examination is recorded, but `I1` is not sealed; and
- no iterative repair trajectory or execution comparison has completed.

Because the recorded `X1` content entered the working conversation, it cannot
by itself satisfy the preregistered mutually unseen human-review stream. A
blinded replacement stream is required for a protocol-compliant `I1`.
Otherwise, the deviation must be recorded and any continuation labeled
noncompliant or exploratory.

The governing design is
[`thoughtlab/reasoningEngineering/MODERNIZATION_ITERATIVE_REASONING_ENGINEERING_DESIGN.md`](thoughtlab/reasoningEngineering/MODERNIZATION_ITERATIVE_REASONING_ENGINEERING_DESIGN.md).

## Agentica direction: architecture, not a finding

This Python repository is the calibration rig, controlled transport,
golden-trace generator, adversarial fixture source, and conformance suite. The
intended product direction is Agentica: an agentic runtime in which reasoning is
governed as observable, revisable work under explicit goals, information rights,
budgets, evidence, and execution authority.

The current abstraction is deliberately conservative:

```text
CognitiveProgram
→ CognitiveCarrier
→ empirically qualified CognitiveModule
```

A single opaque carrier is not a module. Carrier splicing is one unproven
treatment primitive, not the architecture itself.

- [Agentica reasoning-engineering architecture](thoughtlab/reasoningEngineering/AGENTICA_REASONING_ENGINEERING_ARCHITECTURE.md)
- [Fresh-context Agentica review brief](thoughtlab/reasoningEngineering/AGENTICA_FRESH_CONTEXT_ARCHITECTURE_REVIEW.md)

## Protocol invariants

- New controlled runs use Gemini 3.7 Flash through the Gemini Developer API
  `generateContent` method. Historical transports and model IDs remain labeled
  as historical evidence.
- Live continuation replays authorized native parent content unchanged;
  tomography uses a derived sibling carrier and never contaminates the live
  history.
- Planning status is a raw visible `READY` or `NOT_READY` token. `MAX_TOKENS`
  records `UNOBSERVED_TRUNCATED`; it is never converted into a model readiness
  judgment and permits only neutral continuation when a replayable checkpoint
  exists.
- Canonical infrastructure JSON is normalized and round-trip stable. Model JSON
  is not required at the starvation-sensitive readiness boundary.
- Canonical identifiers are random, opaque, type-neutral `ID_` plus Crockford
  base32; semantic roles never leak through identifiers.
- Raw signed carriers are private bearer-like artifacts. Public carrier records
  expose opaque references, hashes, counts, sizes, and classifications; semantic
  projections, prompts, reviews, and interventions require separate explicit
  release authority.

## Relation to Raistlin Bridge

Raistlin Bridge is a downstream motivation, not an experimental dependency or
success criterion. The completed work supports treating a whole provider
response/signed carrier as a sensitive original-turn receipt and experimentally
useful continuation artifact. It does not establish a readable self-record,
identity truth, or complete cognition snapshot. A Bridge implementation could
capture the input, exact approved context/prompt, visible output,
model/configuration provenance, and whole provider response without a second
interpretive model call at capture time; storage, later interpretation,
validation, transport, and governance still have real cost.

Expensive identity interpretation belongs on an asynchronous cold path. Its
counterfactual forks and merge remain one evidence lineage derived from the same
root turn, not multiple independent witnesses or new primary experiences. Their
records require root/parent links and a `derived_reflection` label; any later
promotion into live context remains derived. A permissible self-authorship
scaffold supplies an epistemic method—preserve alternatives, uncertainty, and
reversal conditions—without supplying identity content or a required conclusion.

No experimental result here automatically justifies adding elaborate
deliberation to every live interaction. Any Bridge-facing cognitive-contract
change requires a separate matched experiment plus instrumented segment-level
p50/p95 latency, quality, cost, concurrency, storage, and security measurements.

## Layout

```text
thoughtlab/
  initialTests/
  historicalTests/
  stateTransitions/
  reasoningTraces/
  executablePlans/
  reasoningEngineering/
    MODERNIZATION_REASONING_ENGINEERING_OCCURRENCE_04_ADJUDICATION.md
    MODERNIZATION_ITERATIVE_REASONING_ENGINEERING_DESIGN.md
    AGENTICA_REASONING_ENGINEERING_ARCHITECTURE.md
    AGENTICA_REASONING_ENGINEERING_EVIDENCE_INDEX.md
    freezes/
  gemini_legacy.py

historical_probe.py   # compatibility launcher
results/              # ignored/private run artifacts plus authorized summaries
```

## Historical calibration: initial Interactions trials

`thoughtlab/initialTests/googleThoughts.py` demonstrated, in two separate
Gemini Interactions API trials, that a fact created only inside a `thought` step
could be recovered from the detached thought artifact while seed-only,
output-only, and probe-only controls failed to recover the original fact.

That was an early calibration result, not the transport used by the current
reasoning-engineering occurrences. Current controlled runs use the Gemini
Developer API `generateContent` method.

## Historical BookForge corpus

The historical corpus comes from old BookForge `generateContent` logs containing
`thoughtSignature` metadata.

Raw capsules and probe results are intentionally **not committed**. Tested
provider-native carriers have supported recovery of source-specific semantic
information under query-conditioned probes, so treat them as potentially
sensitive bearer-like artifacts.

### 1. Inspect the local scrape (zero API calls)

```powershell
python .\thoughtlab\historicalTests\inspect_corpus.py
```

Pick one of the largest capsules with a useful source label.

### 2. Run the historical ablation

```powershell
$env:GEMINI_API_KEY="your-throwaway-key"

python .\historical_probe.py `
  --capsule .\bookforge-thought-corpus\capsules\0001_example.json `
  --model gemini-3.7-flash
```

The five arms are:

- `signed_part`: exact historical signed response part
- `text_only`: same visible response part with the signature removed
- `signature_blank`: signed carrier with visible payload erased
- `signature_minimal`: almost only the signature metadata
- `probe_only`: no prior carrier

The original BookForge prompt is **withheld from Gemini** and retained locally
only as ground truth.

The completed 2026-08-27 blunt three-source diagnostic is reported in
[`thoughtlab/historicalTests/BOOKFORGE_BLUNT_ONE_OFF_2026-08-27.md`](thoughtlab/historicalTests/BOOKFORGE_BLUNT_ONE_OFF_2026-08-27.md).
Its modified signature-only arms recovered extensive source-specific context,
but those exploratory mutations were not governed by the later occurrence-04
protocol and do not establish faithful historical reasoning replay. Isolation
and mutation are not inherently off-protocol: occurrence 04 froze blank-visible
signed-carrier isolation as its primary tomography operator. Raw outputs remain
local and ignored.

Some legacy history shapes may be rejected because the request begins with a
`model` role. If that happens, rerun with a content-free structural stub:

```powershell
python .\historical_probe.py `
  --capsule .\bookforge-thought-corpus\capsules\0001_example.json `
  --model gemini-3.7-flash `
  --neutral-stub
```

An HTTP 4xx from a deliberately mutilated carrier is evidence of transport or
request-topology rejection, not evidence about the carrier's semantics.

### 3. Cognitive tomography

Only after a historical capsule proves usable:

```powershell
python .\thoughtlab\historicalTests\tomography.py `
  --capsule .\bookforge-thought-corpus\capsules\0001_example.json `
  --model gemini-3.7-flash
```

That asks separately scoped stateless questions through the same source carrier:
objective, constraints, uncertainty, intended next steps, and a counterfactual
alternative. Each answer is a query-conditioned projection, not a decoded field
from the carrier.

Add `--controls` to run text-only and probe-only controls for every semantic
slice. That costs three API calls per slice, so use it intentionally.

## Synthetic opaque identifiers

Role-neutral synthetic tokens and experimental infrastructure use type-neutral
identifiers from `thoughtlab.opaque_ids.generate_opaque_id`. The canonical form
is `ID_` followed by 26 uppercase Crockford-base32 characters (130 bits). When an
identifier is itself the experimental object, semantic role belongs in the
withheld ground-truth record: do not use prefixes such as `FACT_`, `PLAN_`, or
`CONSTRAINT_`.

Do not use opaque identifiers to erase evidence provenance in hermeneutic tasks.
Source type, authorship, scope, incentives, and institutional position can be
part of the meaning the model must interpret. The modernization
reasoning-engineering dossier therefore uses realistic fictional provenance;
only its run, branch, and checkpoint identifiers are opaque.

New controlled experiments use `gemini-3.7-flash`. Historical scripts and saved
results retain their original model identifiers; runs should always record the
explicit requested and returned model IDs rather than silently relabeling them.

The first excluded true-fork pilot is documented in
`thoughtlab/stateTransitions/README.md`, with its evidence review in
`thoughtlab/stateTransitions/PILOT_REVIEW.md`. The completed mutable S0-S6
native-to-task follow-up is reported in
`thoughtlab/stateTransitions/NATIVE_S0_S6_REVIEW_02.md`: full histories and
controls calibrated perfectly, while detached thought carriers produced sparse,
registry-only recovery and no changed-transition localization. Subsequent
construct review established that this is an exact-ledger projection boundary,
not a general reasoning-persistence result; see
`thoughtlab/stateTransitions/NATIVE_S0_S6_CONSTRUCT_VALIDITY_ADDENDUM.md`.
The earlier `thoughtlab/stateTransitions/PLANNING_SLICE_TEST_PLAN.md` is a
consumed historical specification, not the governing next design.

The completed single-intervention design remains at
[`thoughtlab/reasoningEngineering/MODERNIZATION_REASONING_ENGINEERING_DESIGN.md`](thoughtlab/reasoningEngineering/MODERNIZATION_REASONING_ENGINEERING_DESIGN.md).
It is historical protocol evidence, not the governing next design.

## Post-freeze documentation provenance

Occurrence 04 byte-bound the then-current root README into its source closure:

```text
bytes: 9413
sha256: 7fe130fe54a6a67a274e2f26f9d7e8f56b69c7536634470f0d805577a8be06a7
recorded_git_head: dbf8569a2e7a8673e86dbb56cea16bcc7842b180
```

This README revision is an explicitly post-freeze correction. It intentionally
changes the current working-tree source closure, so strict occurrence-04
verification against the live tree must report `README.md` as changed. That is
provenance enforcement, not retroactive alteration of the sealed occurrence.
The old manifest, lock, results, and final seal remain unchanged; the old README
is reconstructable from the recorded Git snapshot.

The active iterative freeze does not include the root README, so this
documentation update does not alter its frozen 26-file source closure or its
completed `C0/O0` artifacts.
