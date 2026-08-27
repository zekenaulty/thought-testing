# Checkpoint-fork state-transition pilot

This directory contains the first excluded pilot beyond the nonce experiment.
It tests whether two descendants of one exact Gemini reasoning checkpoint support
branch-specific recovery of selected/rejected plan state while retaining shared
ancestry, and whether the latest response's thought-step bundle behaves
differently from the cumulative thought-step bundle.

The pilot deliberately stops at the fork. It does not test supersession,
deactivation, the proposed mutable planning-state sequence, or the later
30-eligible-trial/40-attempt-capped confirmatory regime.

## Completed result

Pilot 05 is the final v3 replacement under the frozen stopping rule. It produced
14/14 eligible generation checkpoints and 84/84 evaluable probes. Latest,
cumulative, and donor carriers exactly recovered candidate registry, selected
plan, and utility rank in both branches, while explicit rejected status and
remote ancestry remained unavailable. Both control arms were uniformly
`unknown + []`.

See [`PILOT_REVIEW.md`](PILOT_REVIEW.md) for the audited comparison and
[`PLANNING_SLICE_TEST_PLAN.md`](PLANNING_SLICE_TEST_PLAN.md) for the proposed
next experiment. The complete-fork confirmatory program remains deferred.

## Frozen design

The synthetic sequence is:

```text
S0 empty -> S1 fact -> S2 constraint -> S3 objective -> S4 three plans
                                                       /              \
                                             S5A choose max    S5B choose min
```

Both children receive deep copies of the exact same full P4 history. Every
checkpoint returns only `{"ack":true}` visibly. Identifiers use the type-neutral
`ID_` plus 26-character Crockford-base32 form; role is recorded separately.

Seven fresh stateless probes interrogate each target descendant through six
carrier arms:

- full valid prefix (task-adherence upper bound only)
- all thought steps from the latest response (the latest-response bundle)
- cumulative thought-step bundle
- visible acknowledgement only
- probe only
- the same branch's latest-response thought bundle from an independent donor trial

The wrong-trial arm is scored against both target and donor ground truth.
The exploratory positive gate also requires a complete probe matrix, exact
full-prefix task adherence, every negative-control answer to be an evaluable
`unknown + []`, and every wrong-trial answer to match donor rather than target
truth. Transport or parse failures never count as clean negative controls.

Gemini 3.7 Flash sampling parameters (`temperature`, `top_p`, and `top_k`) are
omitted. The per-call API `seed` is recorded as a best-effort reproducibility
control, not a promise of deterministic decoding. No retired `Api-Revision`
migration header is presented as a version pin; the manifest records the active
post-June-2026 `steps`/`response_format` schema epoch instead.

`max_output_tokens` is 8192 for both generation and probes because Interactions
counts private thought tokens against that ceiling. Any `status: incomplete`
response remains ineligible; the larger ceiling prevents a trivial
acknowledgement from being truncated after high-level thinking consumes a small
cap. This is protocol revision `1.1_cap8192_after_s0_feasibility`: two preserved
pre-tomography feasibility runs established that the original 64-token
generation cap could be exhausted before the acknowledgement. No probe calls
were made in either failed run.

The current execution revision is
`1.2_fixed_transport_retries_after_pilot03`. Pilot 03 completed generation but
encountered remote disconnect/SSL reset failures across all carrier classes.
Each logical request now has a frozen maximum of three byte-identical attempts,
with 2- and 5-second backoffs. Only transport errors and HTTP
408/429/500/502/503/504 are retryable. HTTP 400 carrier rejection and every 2xx
response—including incomplete, malformed, schema-invalid, or scientifically
unfavorable output—stop immediately and are never retried. The selected-policy
analysis and a first-attempt-only sensitivity analysis are both reported; v3 is
not pooled naively with the earlier no-retry executions.

## Prepare without API calls

```powershell
python -m thoughtlab.stateTransitions.fork_pilot `
  --seed 3185947291046687 `
  --out .\results\fork_pilot\dry_run
```

This freezes `manifest.json` and `preregistration.json`, including prompt,
definition, and code hashes. The command refuses to overwrite a nonempty run
directory.

## Execute the excluded pilot

```powershell
$env:GEMINI_API_KEY="your-throwaway-key"

python -m thoughtlab.stateTransitions.fork_pilot `
  --execute `
  --seed 3185947291046687 `
  --out .\results\fork_pilot\pilot_01
```

Generation eligibility is decided before any tomography. If any of the 14
generation checkpoints is incomplete, returns the wrong model, lacks a signed
thought step, leaks prescribed state visibly, or violates the expected response
shape, no probe calls run.

Raw requests and responses are retained beneath the ignored `raw/` directory.
They may contain signed reasoning artifacts. Compact JSON and Markdown outputs
contain signature hashes and lengths, not raw signature strings.

This pilot is exploratory and excluded. Its result cannot by itself justify a
general claim about Gemini, raw signature bytes, complete latent state, or
chain-of-thought reconstruction.
