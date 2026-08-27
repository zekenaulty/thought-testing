# thought-testing

Controlled experiments around provider-native LLM reasoning state.

## Research program

The empirical object is not hidden chain-of-thought. It is the **observable
semantics and transition behavior of an opaque provider continuation state**:

- which task-relevant distinctions can be recovered through an exact signed
  thought-step carrier under controlled probes;
- whether those distinctions follow the source artifact rather than the probe
  context;
- whether they update with candidate addition/removal, rank reversal, viability,
  and selection; and
- eventually, whether an assigned metacognitive/hermeneutic scaffold package
  changes which preregistered distinctions neutral probes can recover.

The current program separates baseline from intervention:

```text
native planning-slice evidence
        -> mutable native-to-task planning dynamics (R_native)
        -> excluded replication and adversarial attack
        -> contemporaneous native/neutral/retention scaffold experiment
        -> claim-specific confirmation
        -> only then downstream application decisions
```

This is a black-box behavioral science of provider-native continuation artifacts,
not an attempt to decrypt signatures, serialize complete cognition, or claim
access to original internal reasoning.

If a future preregistered scaffold contrast is positive, it would define a practical
form of **reasoning-state engineering**: changing the originating deliberative
procedure to change preregistered, model-mediated recoverability—not editing or
decoding the opaque artifact itself.

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

Controlled experiments must use type-neutral identifiers from
`thoughtlab.opaque_ids.generate_opaque_id`. The canonical form is `ID_` followed
by 26 uppercase Crockford-base32 characters (130 bits). Semantic role belongs in
the withheld ground-truth record, never in the identifier: do not use prefixes
such as `FACT_`, `PLAN_`, or `CONSTRAINT_`.

New controlled experiments use `gemini-3.7-flash`. Historical scripts and saved
results retain their original model identifiers; runs should always record the
explicit requested and returned model IDs rather than silently relabeling them.

The first excluded true-fork pilot is documented in
`thoughtlab/stateTransitions/README.md`, with its evidence review in
`thoughtlab/stateTransitions/PILOT_REVIEW.md`. The completed mutable S0-S6
native-to-task follow-up is reported in
`thoughtlab/stateTransitions/NATIVE_S0_S6_REVIEW_02.md`: full histories and
controls calibrated perfectly, while detached thought carriers produced sparse,
registry-only recovery and no changed-transition localization. The governing
design and interpretation decision tree remain in
`thoughtlab/stateTransitions/PLANNING_SLICE_TEST_PLAN.md`.
