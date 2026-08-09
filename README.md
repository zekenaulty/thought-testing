# thought-testing

Controlled experiments around provider-native LLM reasoning state.

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
