# thought-testing

Controlled experiments around provider-native LLM reasoning state.

## Research program

The empirical object is not hidden chain-of-thought. It is the **observable
semantics and transition behavior of an opaque provider continuation state**:

- which task-relevant distinctions can be recovered through an exact signed
  thought-step carrier under controlled probes;
- whether those distinctions follow the source artifact rather than the probe
  context;
- whether detached readouts predict the originating state's prospective actions,
  conditional branches, revisions, and stopping behavior across a real tool
  interruption; and
- whether an assigned metacognitive/hermeneutic planning scaffold makes
  decision structure observable enough to diagnose and revise locally.

The current experiment is aimed at the practical reasoning-engineering loop:

```text
complex modernization dossier
        -> private scaffolded planning state C_t
        -> READY / continuation threshold
        -> blank-visible isolated native carrier T_t
        -> holistic semantic observation O_t(q)
        -> sealed human diagnosis + local intervention prediction
        -> adjusted continuation from the untouched READY state
        -> re-isolation and matched baseline/adjusted executions
```

Isolation/mutation is the primary observation instrument: it suppresses the
ordinary task and visible answer while preserving the provider-native signed
thought carrier. The experiment asks whether that view is useful for observing
option structure, commitments, assumptions, unresolved tensions, and revision
conditions—and whether a diagnostic intervention can produce a predicted,
localized state change that survives into behavior.

This is a black-box behavioral science of provider-native continuation artifacts,
not an attempt to decrypt signatures, serialize complete cognition, or claim
access to original internal reasoning.

If the preregistered observation/intervention/execution chain is positive, it
would establish a practical form of **reasoning-state engineering**: shaping the
originating deliberative procedure, observing its recoverable decision state,
and making a bounded diagnostic correction—not editing or decoding the opaque
artifact itself.

## Relation to Raistlin Bridge

Raistlin Bridge is a downstream motivation, not an experimental dependency or
success criterion. If the research holds, an ordinary live turn could retain a
sensitive original-turn receipt—input, exact approved context/prompt, visible
output, model/configuration provenance, and the whole provider response/signed
thought-step artifact—without a second interpretive model invocation. This is
contemporaneous generation evidence, not identity truth or a readable self-
record. Capture, secure storage, validation, transport, and governance still
have real cost.

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
    googleThoughts.py
    gemini_thought_ablation_results.json
    harvest_bookforge_thoughts.py
  historicalTests/
    inspect_corpus.py
    historical_probe.py
    tomography.py
    capsule.py
    probes.py
  gemini_legacy.py

historical_probe.py   # compatibility launcher
```

## Established result

`thoughtlab/initialTests/googleThoughts.py` demonstrated, in two independent
Gemini Interactions API trials, that a fact created only inside a `thought` step
could be recovered from the detached thought artifact while seed-only,
output-only, and probe-only controls failed to recover the original fact.

## Historical BookForge corpus

The historical corpus comes from old BookForge `generateContent` logs containing
`thoughtSignature` metadata.

Raw capsules and probe results are intentionally **not committed**. We have direct
evidence that provider-native reasoning artifacts can preserve semantically
recoverable hidden state, so treat them as potentially sensitive bearer-like
artifacts.

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
  --model gemini-3.6-flash
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
but the mutation is off-protocol and does not establish faithful historical
reasoning replay. Raw outputs remain local and ignored.

Some legacy history shapes may be rejected because the request begins with a
`model` role. If that happens, rerun with a content-free structural stub:

```powershell
python .\historical_probe.py `
  --capsule .\bookforge-thought-corpus\capsules\0001_example.json `
  --model gemini-3.6-flash `
  --neutral-stub
```

An HTTP 4xx from a deliberately mutilated carrier is experimental evidence.

### 3. Cognitive tomography

Only after a historical capsule proves usable:

```powershell
python .\thoughtlab\historicalTests\tomography.py `
  --capsule .\bookforge-thought-corpus\capsules\0001_example.json `
  --model gemini-3.6-flash
```

That asks independent stateless questions of the exact same reasoning artifact:
objective, constraints, uncertainty, intended next steps, and a counterfactual
alternative.

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

The current freeze-ready review design is
[`thoughtlab/reasoningEngineering/MODERNIZATION_REASONING_ENGINEERING_DESIGN.md`](thoughtlab/reasoningEngineering/MODERNIZATION_REASONING_ENGINEERING_DESIGN.md).
It induces a complex planning state with a semantic-state scaffold, observes
each checkpoint through a blank-visible isolated native carrier, pauses for a
sealed human diagnostic intervention, and compares the resulting trace and
execution deltas. Planning emits only raw `READY` or `NOT_READY`; provider
truncation is carried forward only when an exact signed checkpoint is replayable.
