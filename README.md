# thought-testing

Small controlled experiments around provider-native LLM reasoning state.

## Current results

`googleThoughts.py` established a clean Gemini Interactions-API ablation:
information created only inside a `thought` step was recoverable from the
standalone thought artifact in two independent trials, while seed-only,
output-only, and probe-only controls did not recover the original nonce.

## Historical BookForge experiments

The next phase uses old BookForge `generateContent` logs that contain
`thoughtSignature` metadata. Historical signatures are more awkward than modern
Interactions `thought` steps because the signature is attached to a response
part, so the important control is:

- exact signed historical part
- the exact same visible part with the signature removed
- signature-only carrier (may be rejected; rejection is data)
- probe-only baseline

The original BookForge prompt is kept **withheld** from Gemini and is used only as
local ground truth after the probe.

### Security / repository hygiene

Raw reasoning capsules are intentionally gitignored. We have direct evidence that
provider-native reasoning artifacts can preserve semantically recoverable hidden
state. Treat raw capsules and probe results as potentially sensitive bearer-like
artifacts, not as ordinary debug logs.

### Run

Set a throwaway developer API key locally:

```powershell
$env:GEMINI_API_KEY="..."
```

Then probe one harvested capsule:

```powershell
python .\historical_probe.py --capsule .\bookforge-thought-corpus\capsules\0001_example.json
```

Override the model if the historical model name is no longer callable:

```powershell
python .\historical_probe.py --capsule .\bookforge-thought-corpus\capsules\0001_example.json --model gemini-3.6-flash
```

HTTP 4xx responses from deliberately mutilated history arms are experiment
outcomes, not necessarily harness failures.
