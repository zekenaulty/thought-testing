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

The next experiment intentionally measures a native-to-task,
ordinary-instruction baseline before introducing the proposed
metacognitive/hermeneutic retention procedure. This remains a prescribed
synthetic task, not spontaneous or unprompted cognition. A later contemporaneous
three-arm study may compare native, neutral-procedure, and retention-scaffold
recoverability, but it is a separate phase with separate claims and
authorization. A two-arm native-versus-retention fallback could estimate only a
package effect, not a retention-specific mechanism.

## Native S0-S6 freeze history

### Review 02: completed native S0-S6 execution

The repaired native-to-task protocol revision is
`1.1_canonical_ack_json`, frozen at
[`freezes/native_s0_s6_review_02`](freezes/native_s0_s6_review_02).

- model: `gemini-3.7-flash`
- master seed: `7631801246228819094`
- freeze ID: `b98a93fd8ba23718196a5113afa7dbdc81bd704db8810c66def9f7347edb13bf`
- local verification: `86 passed, 31 subtests passed`
- frozen calls: `210` logical requests for one complete run; `224` logical and
  `672` physical attempts at the two-run stopping ceiling
- review payload: exactly five allowlisted files; no credentials, requests,
  responses, call index, or execution output

Generation acknowledgement eligibility now strictly parses JSON with
duplicate-key and non-finite-number rejection, canonicalizes both the returned
value and the expected `{"ack": true}` value through the same deterministic
serializer, and compares the resulting UTF-8 bytes. This ignores insignificant
whitespace while preserving JSON types, so `{"ack": 1}` does not equal
`{"ack": true}`. Post-extraction text-byte equality remains diagnostic only.
Original provider response bytes and response steps are not rewritten; exact
bytes remain authoritative for freeze integrity, retry identity, and wire
evidence.

The freeze was prepared without a model transport path using:

```powershell
python -m thoughtlab.stateTransitions.planning_transition_freeze prepare `
  --seed 7631801246228819094 `
  --out thoughtlab/stateTransitions/freezes/native_s0_s6_review_02
```

Reviewers can verify its exact bytes and current source binding with:

```powershell
python -m thoughtlab.stateTransitions.planning_transition_freeze verify `
  --freeze-dir thoughtlab/stateTransitions/freezes/native_s0_s6_review_02 `
  --freeze-id b98a93fd8ba23718196a5113afa7dbdc81bd704db8810c66def9f7347edb13bf
```

The freeze was executed once on 2026-08-27 after separate approval. Its final
status is `tomography_complete`: 14/14 generation checkpoints were eligible,
all 196 probe cells were scored, and the run used 210 logical requests and 213
physical attempts. The prespecified positive composite did not pass. Full
prefixes were 56/56 exact and controls were 56/56 clean, while target latest
thought bundles recovered 3/28 state cells, all candidate registry. Cumulative
thought bundles recovered 5/28, also registry-only; ranking, viability, and
selection were uniformly unknown through detached thought carriers.

See [`NATIVE_S0_S6_REVIEW_02.md`](NATIVE_S0_S6_REVIEW_02.md) for the audited
findings and the
[`execution_ledger.json`](../../results/planning_transition/executions/b98a93fd8ba23718196a5113afa7dbdc81bd704db8810c66def9f7347edb13bf/execution_ledger.json)
for the canonical one-shot record. This freeze is consumed and must not be run
again.

### Review 01: consumed historical execution

The immutable v1.0 freeze remains at
[`freezes/native_s0_s6_review_01`](freezes/native_s0_s6_review_01). It was
executed once on 2026-08-27 after separate approval using master seed
`3201385410977130018` and freeze ID
`262a6c487a42c3aed9c1d17c42e5d7d4428c2c89c667b993293df890639328a3`.

Its terminal status is `both_planned_runs_generation_ineligible`; see the
[`execution_ledger.json`](../../results/planning_transition/executions/262a6c487a42c3aed9c1d17c42e5d7d4428c2c89c667b993293df890639328a3/execution_ledger.json).
Run 01 stopped at donor S3 and Run 02 stopped at target S1 solely because the
local v1.0 gate treated parse-valid pretty JSON as different task semantics from
the minified serialization. The completed prefixes otherwise passed their
checkpoint checks. The execution made 6 logical requests and 7 physical
attempts, including one successful byte-identical retry after HTTP 500.

That was an erroneous protocol-envelope failure on our side, not a Gemini
planning-generation failure. Neither run entered tomography, so the execution
does not estimate `R_native` and supplies no evidence for or against
carrier-specific planning-state recovery. Review 01 remains byte-unchanged and
consumed. Its old current-source binding is necessarily obsolete after the v1.1
repair; it must not be rerun or silently reinterpreted under the new protocol.

## Earlier fork-pilot frozen design

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

In that earlier fork pilot, `max_output_tokens` is 8192 for both generation and
probes because Interactions
counts private thought tokens against that ceiling. Any `status: incomplete`
response remains ineligible; the larger ceiling prevents a trivial
acknowledgement from being truncated after high-level thinking consumes a small
cap. This is protocol revision `1.1_cap8192_after_s0_feasibility`: two preserved
pre-tomography feasibility runs established that the original 64-token
generation cap could be exhausted before the acknowledgement. No probe calls
were made in either failed run.

The earlier fork-pilot execution revision is
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
