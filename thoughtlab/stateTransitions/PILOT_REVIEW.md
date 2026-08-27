# Checkpoint-fork pilot: final findings for review

## Decision status

The frozen v3 replacement is complete. It cleanly reproduces and strengthens a
narrow planning-state result, but it still does **not** satisfy the
prespecified complete-fork composite. The original 30-eligible-trial,
40-attempt-capped full-state program should therefore remain deferred.

The strongest supported exploratory observation is now:

> In this Gemini 3.7 Flash checkpoint-fork setup, detached signed thought-step
> bundles enabled exact, source-specific recovery of the current candidate-plan
> registry, relative utility ranking, and branch-selected plan. They did not
> recover explicit rejected-plan status or the earlier fact, objective, and
> constraint ancestry.

Pilot 05 recovered all 18 planning-slice cells: candidate registry, selected
plan, and utility rank for both branches through the target latest-response
bundle, target cumulative bundle, and wrong-trial donor bundle. All six positive
wrong-trial results were donor-exact and target-inexact. Both negative-control
arms were uniformly `unknown + []`.

This is evidence for a locally task-shaped, artifact-specific planning slice.
It is not evidence that the artifact is a complete working-memory snapshot, raw
signature bytes alone are sufficient, or hidden chain-of-thought has been
reconstructed.

## Execution ledger

| Run | Protocol | Generation | Tomography | Classification |
|---|---|---:|---:|---|
| pilot 01 | v1 | 0 eligible; local socket denied | 0 | sandbox feasibility failure |
| pilot 02 | v1 | 0 eligible; 64-token ceiling caused `incomplete` S0 | 0 | cap feasibility failure |
| pilot 03 | v2, no transport retry | 14/14 eligible | 84 rows; 74 evaluable | excluded incomplete pilot |
| pilot 04 | v3 bounded retry | donor S5A exhausted three transport attempts | 0 | pre-tomography infrastructure failure |
| pilot 05 | v3 bounded retry | 14/14 eligible | 84/84 evaluable | final v3 replacement |

Pilot 05 was the first planned replacement to enter tomography. Under the
pre-execution stopping policy it is therefore the final analyzed v3 run;
pilot 06 was not launched and must not be used as a semantic rerun.

V1, v2, and v3 remain separate estimands. Pilot 03 and pilot 05 are compared
descriptively below, not pooled as interchangeable replications. Raw request,
response, and signed-carrier bytes remain only in ignored local result
directories.

## Pilot 05 execution integrity

All 14 target/donor generation checkpoints were eligible:

- exact requested and returned model: `gemini-3.7-flash`;
- completed responses, one signed thought step, and one exact acknowledgement;
- no visible identifier or utility leakage;
- exact shared P4 parent for both children of each trial;
- distinct S5A/S5B response and thought-bundle hashes.

The run made 98 logical requests and 99 physical attempts. The only retry was
donor S0 generation: a transport reset followed by a byte-identical successful
HTTP 200 attempt after the frozen two-second backoff. All 84 tomography requests
completed with first-attempt HTTP 200 responses. There were no probe retries,
transport-missing cells, HTTP 400 carrier rejections, parse failures, or schema
failures.

Independent post-run checks found:

- exactly 14 unique generation rows and 84 unique, evaluable, scored probe rows;
- 99 request files, 99 response files, 99 physical metadata files, and 98
  logical metadata files;
- exact recomputation of every normalization, target/donor score, composite,
  summary, and rendered run review;
- matching frozen definition, manifest, probe, response-format, source, carrier,
  raw-byte, and metadata hashes;
- zero duplicate or noncanonical returned IDs; the only target-foreign rows were
  the six intended donor-exact wrong-trial planning rows;
- 37 tests plus 19 subtests passing.

The no-retry sensitivity gate is false because donor S0 required a generation
retry. This is a conservative counterfactual gate, not a second observed run.
Because no probe retried, every probe-level first-attempt score equals the
selected-policy score.

Two nonblocking provenance caveats remain. The stopping-policy hash was not
embedded in pilot 05's preregistration, although the clean pre-run commit and
policy file bind the definition, seed, and planned run names. Also, additive v3
retry fields retain `..._v2` row/summary schema labels; the manifest's v3
protocol and frozen source hashes are authoritative.

## Mechanical comparison

| Carrier arm | Pilot 03 | Pilot 05 | Pilot 05 missing |
|---|---:|---:|---:|
| full valid prefix, target exact | 12/14 exact; 12/12 evaluable | 14/14 exact | 0 |
| latest-response bundle, target exact | 4/14; 4/12 evaluable | 6/14 | 0 |
| cumulative bundle, target exact | 5/14; 5/12 evaluable | 6/14 | 0 |
| visible acknowledgement control | 13/13 evaluable `unknown + []` | 14/14 `unknown + []` | 0 |
| probe-only control | 12/12 evaluable `unknown + []` | 14/14 `unknown + []` | 0 |
| wrong-trial bundle, target exact | 0/14; 0/13 evaluable | 0/14 | 0 |
| wrong-trial bundle, donor exact | 4/14; 4/13 evaluable | 6/14 | 0 |

Every pilot 05 full-prefix probe was exact, establishing that the prompts,
ground truth, scorer, and model could recover all seven fields when supplied a
documented-valid history.

### Exact planning-slice comparison

`E` means exact on the intended target or donor truth, `U` means evaluable but
unknown/nonexact, and `M` means transport-missing.

| Branch / field | Target latest, 03 -> 05 | Target cumulative, 03 -> 05 | Donor wrong-trial, 03 -> 05 |
|---|---:|---:|---:|
| S5A candidate registry | M -> E | E -> E | E -> E |
| S5A selected plan | E -> E | E -> E | U -> E |
| S5A utility rank | E -> E | E -> E | E -> E |
| S5B candidate registry | E -> E | E -> E | M -> E |
| S5B selected plan | U -> E | M -> E | E -> E |
| S5B utility rank | E -> E | E -> E | E -> E |

Across these 18 cells, pilot 03 had 13 exact, two unknown, and three missing.
Pilot 05 had 18/18 exact:

- candidate registry: 6/6;
- selected plan: 6/6;
- utility ranking: 6/6.

The two branches selected opposite utility extremes as instructed. The donor's
opaque IDs were independently generated, so donor exactness is not an alias or
label coincidence.

### What remained unavailable

For latest, cumulative, and donor wrong-trial bundles alike, both branches
returned evaluable `unknown` answers for:

- active ancestry;
- active objective;
- active constraint;
- rejected plans.

Each unavailable field was therefore 0/6 across the two target carrier arms and
the donor arm. Candidate membership plus the selected ID mathematically implies
the two-item complement in this synthetic setup, but that derivation is not
evidence that the explicit `rejected` lifecycle status was present or
recoverable.

Latest-response and cumulative bundles produced identical normalized answers
for all 14 pilot 05 probes. That is consistent with the latest bundle being
sufficient for this planning slice, but one excluded target/donor pair does not
establish general equivalence.

## Prespecified gates

| Gate | Pilot 03 | Pilot 05 |
|---|---:|---:|
| generation eligible | pass | pass |
| exact fork parent and distinct child artifacts | pass | pass |
| full-prefix task-adherence composite | fail: 12/14, two missing | pass: 14/14 |
| all controls evaluable `unknown + []` | fail: three missing | pass: 28/28 |
| wrong-trial full donor composite | fail: 4/14, one missing | fail: 6/14 |
| latest full-fork composite | fail: 4/14, two missing | fail: 6/14 |
| cumulative full-fork composite | fail: 5/14, two missing | fail: 6/14 |

The v3 result removes tomography-cell missingness and the resulting semantic-cell
ambiguity, but it still fails the original all-field claim. The failure is
structural: planning membership, rank, and selection were available, while
remote ancestry and explicit rejected status were uniformly unavailable.

## Interpretation

The two excluded semantic runs support a coherent, narrow model:

1. Whole signed thought-step bundles are accepted as detached carrier shapes in
   this exact Interactions configuration.
2. The carrier was sufficient for source-specific recovery of structure for the
   reasoning problem active at the moment it was generated: candidate
   membership, comparative rank, and chosen continuation.
3. The carrier did not behave like a semantic ledger or complete working-state
   snapshot. Earlier context and the experimenter's explicit rejected-status
   ontology were not recoverable under these probes.
4. Donor routing and uniformly clean controls make ordinary reconstruction from
   the probe prompt alone a poor explanation for the positive planning cells.

This remains an excluded observation for one model, API/schema epoch, prompt
family, single master seed/specification, and whole signed thought-step
carriers. It does not support claims about raw signature sufficiency,
latent-state serialization, chain-of-thought recovery, or population-level
reliability.

## Recommended next experiment

Stop trying to confirm the original complete-checkpoint theory. The evidence now
earns a surgical test of the planning representation that actually reproduced:

```text
S0  empty planning slate
S1  candidates A/B/C; rank A > B > C
S2  same candidates; change rank to B > A > C
S3  remove C from consideration
S4  add D; rank B > A > D
S5  keep B registered but make the current top-ranked candidate nonviable
S6  select the new highest-ranked viable candidate (A)
```

At each checkpoint, including S0, test exact candidate membership, complete
rank, viability partition, and selected candidate. Add a same-checkpoint donor
carrier for source specificity, then cross-score adjacent checkpoint outputs
for temporal localization without issuing duplicate requests.

Keep this S0-S6 experiment as the native-to-task, ordinary-instruction baseline.
It remains a prescribed synthetic task, but deliberately excludes the proposed
hermeneutic/metacognitive retention intervention. Its `R_native` is the full
preregistered recoverability matrix, not a scalar or direct latent-state readout.
After those dynamics replicate and survive adversarial checks, run a separate
contemporaneous three-arm study with the same problem and acknowledgement:
`R_native`, an effort-/structure-/placement-/length-matched neutral procedural
condition `R_neutral`, and a private retention scaffold `R_retention` that keeps
alternatives, reversal conditions, and unresolved uncertainty continuation-
relevant. Preregister the total package contrast (`R_retention` versus
`R_native`), the retention-specific contrast (`R_retention` versus `R_neutral`),
and the generic procedure/effort diagnostic (`R_neutral` versus `R_native`).
These are cellwise contrasts between recoverability matrices, not scalar latent-
state measurements. A separately preregistered two-arm fallback could support
only a package-effect claim. This separation prevents baseline, intervention,
generic added procedure, and model/API drift from being collapsed.

The review-ready proposal is in
[`PLANNING_SLICE_TEST_PLAN.md`](PLANNING_SLICE_TEST_PLAN.md). The original
30-eligible-trial, maximum-40-attempt confirmatory regime remains a later phase,
not the immediate next run. Its exact outcome should be chosen only after native
replication and the separately preregistered scaffold design establish which
claim is actually being confirmed.
