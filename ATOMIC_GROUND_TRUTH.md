# Atomic ground-truth follow-up

The first whole-object exact probe produced useful evidence but the
`signature_minimal` response ended mid-JSON after successfully recovering all four
character names. Because the JSON was incomplete, the old scorer marked that arm
as `parsed: false` and assigned `0/7`.

This follow-up makes each hidden fact its own independent stateless experiment.

Quick run (12 API calls: 4 fields x 3 arms):

```powershell
python .\thoughtlab\historicalTests\atomic_ground_truth_probe.py `
  --capsule .\bookforge-thought-corpus\capsules\0001_continuity_pack_9fdb145e4a5a.json `
  --model gemini-3.6-flash
```

It tests:
- exact scene_id
- complete character-name registry
- complete thread-id registry
- exact set of unselected thread IDs

Every field is independently tested with:
- signature-minimal
- visible-text-only
- no-history

New runs use result schema `atomic_ground_truth_v2`. It records parse status
separately from the parsed value, so valid JSON `null`, empty responses,
malformed JSON, and requests where parsing was not attempted cannot be confused
during scoring. Do not pool older v1 scores with v2 without rescoring the stored
response text.

For the full nine-field suite:

```powershell
python .\thoughtlab\historicalTests\atomic_ground_truth_probe.py `
  --capsule .\bookforge-thought-corpus\capsules\0001_continuity_pack_9fdb145e4a5a.json `
  --model gemini-3.6-flash `
  --all
```

Do the quick run first.
