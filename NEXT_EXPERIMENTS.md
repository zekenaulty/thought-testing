# Next historical thought-signature experiments

Use the already harvested BookForge capsule:

```text
bookforge-thought-corpus/capsules/0001_continuity_pack_9fdb145e4a5a.json
```

The first historical probe established that this January 2026 signature is accepted
by `gemini-3.6-flash`, and that a signature-minimal carrier reconstructs substantial
state that the visible-response-only control does not.

Run these one at a time. Do not batch the whole suite until the individual results
make sense.

## Experiment 1 — Exact hidden ground truth

Strongest next test. The harness extracts expected values locally from the withheld
BookForge prompt and never sends those expected answers to Gemini.

```powershell
python .\thoughtlab\historicalTests\ground_truth_probe.py `
  --capsule .\bookforge-thought-corpus\capsules\0001_continuity_pack_9fdb145e4a5a.json `
  --model gemini-3.6-flash
```

It asks for exact values including the scene ID, scene target, complete character
registry, complete thread registry, characters not present in the selected scene,
and threads available but not selected. It automatically scores:

- signature-minimal
- visible text only
- probe only

This should be run first.

## Experiment 2 — Signature integrity / bit flip

Tests whether a one-character mutation destroys or changes the reasoning artifact.

```powershell
python .\thoughtlab\historicalTests\signature_integrity.py `
  --capsule-a .\bookforge-thought-corpus\capsules\0001_continuity_pack_9fdb145e4a5a.json `
  --model gemini-3.6-flash
```

Expected possibilities:

- mutated signature rejected: evidence of integrity/authentication checking
- mutated signature accepted but loses state: evidence signature bytes matter
- mutated signature still recovers identical state: very surprising; repeat before concluding

## Experiment 3 — Signature transplant

After Experiment 2, choose a semantically different second capsule. A useful
candidate from the current corpus is:

```text
bookforge-thought-corpus/capsules/0040_repair_scene_8e3c8b2c444a.json
```

Run:

```powershell
python .\thoughtlab\historicalTests\signature_integrity.py `
  --capsule-a .\bookforge-thought-corpus\capsules\0001_continuity_pack_9fdb145e4a5a.json `
  --capsule-b .\bookforge-thought-corpus\capsules\0040_repair_scene_8e3c8b2c444a.json `
  --model gemini-3.6-flash
```

This swaps B's signature onto A's visible response and A's signature onto B's
visible response. The outcome distinguishes:

- signature-bound semantics
- visible-carrier dominance
- cryptographic/structural binding that rejects transplant

## Experiment 4 — Fork

Same exact signature, two independent stateless continuations:

```powershell
python .\thoughtlab\historicalTests\fork_probe.py `
  --capsule .\bookforge-thought-corpus\capsules\0001_continuity_pack_9fdb145e4a5a.json `
  --model gemini-3.6-flash
```

Both branches first reconstruct the same hidden continuity witness. One preserves
the original thread-selection policy; the other must choose a different available
thread. The harness reports whether the witnesses match and whether the branches
diverge.

## Experiment 5 — Cross-model portability

Only after the exact-ground-truth test:

```powershell
python .\thoughtlab\historicalTests\cross_model_probe.py `
  --capsule .\bookforge-thought-corpus\capsules\0001_continuity_pack_9fdb145e4a5a.json `
  --models gemini-3-flash-preview gemini-3.6-flash
```

This holds the signature and probe constant while varying only the model.

## Order

Run:

1. `ground_truth_probe.py`
2. `signature_integrity.py` with capsule A only
3. `signature_integrity.py` with A + B transplant
4. `fork_probe.py`
5. `cross_model_probe.py`

Stop after each result and inspect it before moving on.
