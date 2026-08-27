# Native S0-S6 review 02: final findings

## Decision status

The repaired `1.1_canonical_ack_json` execution is complete and scientifically
valid. It is not another protocol-envelope failure. The prespecified positive
composite did **not** pass, but the run establishes a narrower and useful result:

> Under this execution, detached native thought carriers sometimes supported
> exact, source-specific recovery of the candidate registry, but did not
> reliably expose utility ranking, viability, selection, or their transitions.

The recovered signal was sparse, registry-specific, and epistemically
conservative. Every thought-carrier response that claimed `known` was exact for
its source. Every other thought-carrier response was `unknown`; there were no
confidently wrong values, future or premature identifiers, or cross-trial
contamination.

This remains one excluded exploratory target/donor sequence, not an estimate of
population reliability or a scalar measurement of latent state.

## Execution identity and integrity

- model: `gemini-3.7-flash`
- protocol revision: `1.1_canonical_ack_json`
- master seed: `7631801246228819094`
- freeze ID: `b98a93fd8ba23718196a5113afa7dbdc81bd704db8810c66def9f7347edb13bf`
- final status: `tomography_complete`
- final run: `run_01`; no `run_02`
- requests: `210` logical, `213` physical
- generation: `14/14` eligible, exact lineages, pairwise-distinct artifacts
- tomography: `196/196` evaluable and scored
- delta matrix: `120/120` present and mechanically derived

The complete ledger is in
[`execution_ledger.json`](../../results/planning_transition/executions/b98a93fd8ba23718196a5113afa7dbdc81bd704db8810c66def9f7347edb13bf/execution_ledger.json),
and the frozen machine summary is in
[`summary.json`](../../results/planning_transition/executions/b98a93fd8ba23718196a5113afa7dbdc81bd704db8810c66def9f7347edb13bf/run_01/summary.json).

Two logical probes used the frozen retry policy. Target full-prefix S1
viability encountered two transport errors before an exact third-attempt
response. Target cumulative S0 selection encountered one transport error before
a second-attempt `unknown`. Retry bodies were byte-identical and the prescribed
backoffs were followed. No experimental latest-carrier hit depended on a retry;
the first-attempt latest result remains `3/28`.

Independent post-run checks found:

- an exact byte-for-byte copied freeze and matching manifest/summary hashes;
- exactly 213 raw request/response/physical-metadata triplets, 210 logical
  metadata files, and one 213-entry call index;
- exact replay of all 196 selected responses into the stored 120 delta rows and
  final summary;
- no credential occurrence in any artifact and no raw signature value or raw
  thought content in compact artifacts;
- no symlink/reparse escape, unknown opaque ID, or compact-ID value outside the
  frozen 20-ID universe.

Two completed `.partial.json` snapshots remain byte-identical to their final
counterparts. This is stale resumability duplication, not missing or corrupted
evidence. The canonical execution directory has not been modified after
completion.

## The JSON repair was necessary

All 14 acknowledgements strictly parsed and matched the canonical expected JSON
value. None of the 14 post-extraction strings matched the old minified bytes:

- canonical acknowledgement matches: `14/14`
- old text-byte matches: `0/14`
- observed visible lengths: 13 or 17 characters

The previous gate would therefore have rejected every checkpoint in this valid
generation. Canonicalizing both actual and expected values removed formatting
noise while retaining semantic strictness: wrong booleans, numeric `1`, null,
extra or duplicate keys, and non-finite values remain ineligible.

## Frozen validity gates

| Gate | Result |
|---|---:|
| Target full-prefix truth | `28/28` exact |
| Donor full-prefix truth | `28/28` exact |
| Combined full-prefix task adherence | `56/56` exact |
| Visible-only controls | `28/28` clean `unknown` |
| Probe-only controls | `28/28` clean `unknown` |
| Probe matrix | `196/196` complete and scored |
| Delta matrix | `120/120` complete and mechanical |
| Identifier/timeline anomalies | `0` |
| Common validity gate | pass |
| Causal-specificity gate | fail |
| Latest positive exploratory observation | fail |

The perfect full-prefix arms establish that Gemini could perform the task, the
ground truth was coherent, and every field was recoverable when its documented
history was present. The uniformly clean controls show that the probe text,
visible acknowledgement, and opaque-ID syntax were not sufficient to recreate
the answers.

## Recoverability matrix

| Carrier arm | Registry | Ranking | Viability | Selection | Joint |
|---|---:|---:|---:|---:|---:|
| Target full prefix | `7/7` | `7/7` | `7/7` | `7/7` | `28/28` |
| Donor full prefix, donor truth | `7/7` | `7/7` | `7/7` | `7/7` | `28/28` |
| Target latest thought | `3/7` | `0/7` | `0/7` | `0/7` | `3/28` |
| Target cumulative thoughts | `5/7` | `0/7` | `0/7` | `0/7` | `5/28` |
| Wrong-trial latest, donor truth | `2/7` | `0/7` | `0/7` | `0/7` | `2/28` |
| Target visible only | `7/7` clean | `7/7` clean | `7/7` clean | `7/7` clean | `28/28` clean |
| Probe only | `7/7` clean | `7/7` clean | `7/7` clean | `7/7` clean | `28/28` clean |

For the prespecified latest-response primary arm:

- replication-under-history: `2/11`;
- history-dependent S2-S6 state: `2/20`;
- registry trajectory: `3/7`;
- ranking trajectory: `0/7`;
- viability trajectory: `0/7`;
- preselection known-empty state: `0/6`;
- selected candidate at S6: `0/1`.

Every non-registry latest, cumulative, and wrong-trial cell returned `unknown`.
This is evidence about behavioral recoverability through this exact carrier and
probe configuration; it is not proof that the corresponding distinction was
absent internally.

## Where registry recovery appeared

`E` means exact source truth and `U` means evaluable `unknown`.

| Checkpoint | Target latest | Target cumulative | Wrong-trial donor |
|---|---:|---:|---:|
| S0 | E | U | U |
| S1 | U | E | U |
| S2 | E | E | U |
| S3 | U | U | U |
| S4 | U | E | E |
| S5 | E | E | U |
| S6 | U | E | E |

The two wrong-trial exact cells at S4 and S6 were donor-exact and target-inexact,
so they are genuine source-distinguishing recoveries. They are only `2/19`
prespecified discriminating cells, however, and do not satisfy the causal-
specificity gate.

Excluding S0 as preregistered, cumulative registry was descriptively exact in
`5/6` cells versus `2/6` for latest. That apparent advantage is a hypothesis,
not a carrier-effect estimate. At S0 the latest and cumulative carrier hashes
and complete request-wire hashes were identical, yet one fresh request returned
exact known-empty state and the other returned `unknown`. The API seed is only a
best-effort control; this pair directly demonstrates nonzero readout
variability.

## Transition localization

| Carrier arm | Exact deltas | Changed | Stable | Directional changed |
|---|---:|---:|---:|---:|
| Target full prefix | `24/24` | `12/12` | `12/12` | `12/12` |
| Donor full prefix | `24/24` | `12/12` | `12/12` | `12/12` |
| Target latest thought | `0/24` | `0/12` | `0/12` | `0/12` |
| Target cumulative thoughts | `3/24` | `0/12` | `3/12` | `0/12` |
| Wrong-trial latest | `0/24` | `0/12` | `0/12` | `0/12` |

The three cumulative successes were stable candidate-registry transitions at
S1->S2, S4->S5, and S5->S6. No detached carrier localized a changed transition.
Accordingly this run does not support a broadly recoverable mutable planning
state, even though it found isolated exact state cells.

## Relation to pilot 05

Pilot 05's simpler fork task recovered candidate registry, relative rank, and
branch selection through latest, cumulative, and wrong-trial thought bundles in
all 18 planning-slice cells. Review 02 did not generalize that result to this
sequential mutable-state task: only registry survived, and only intermittently.

Several things changed together: the task topology, mutation sequence, probe
matrix, opaque-ID construction, and execution sample. Type-neutral IDs did the
intended methodological work—successful cells required recovering both an
opaque token and its role—but this run cannot identify ID neutrality as the
cause of the difference.

The supported model is narrower than a semantic ledger. Provider-native thought
artifacts can carry exact task-shaped distinctions, but accessibility is
selective, checkpoint-dependent, and readout-variable. Whole signed artifacts
should not be treated as complete working-memory snapshots.

## Raistlin Bridge boundary

For Raistlin Bridge, this result strengthens the distinction between an original
turn receipt and a readable self-record. The full receipt—approved input and
context, visible output, model/configuration provenance, and the whole provider
response—remains valuable canonical evidence. The signed thought artifact alone
is not a dependable mutable planning-state interface.

Cold-path interpretation should therefore retain evidence lineage, explicit
uncertainty, and the ability to abstain. An `unknown` readout must not be silently
promoted into an assertion that a distinction was absent from the originating
process.

## Recommended next experiment

Do not advance yet to the retention scaffold or the later 30-eligible-trial,
40-attempt-capped confirmatory program. The next excluded experiment should
decide whether registry recovery is a repeatable carrier property or a sparse
readout accident.

The next design should:

1. use multiple independently seeded S0-S6 target/donor sequence pairs for
   between-sequence reliability;
2. preregister repeated byte-identical registry probes on the same frozen
   carriers, randomized through the schedule, to measure within-artifact readout
   repeatability without calling repeats independent trials;
3. keep latest, cumulative, wrong-trial, full-prefix, visible-only, and
   probe-only registry arms as the primary matrix;
4. make source-specific current-registry recovery and changed-registry temporal
   localization the primary endpoints;
5. retain rank, viability, and selection as negative-boundary diagnostics rather
   than positive gates;
6. preserve type-neutral IDs, exact full-prefix calibration, clean controls,
   bounded byte-identical transport retries, and frozen first-attempt
   sensitivity reporting.

If registry recovery replicates and follows the source artifact, freeze that
narrower `R_native` before designing the contemporaneous native/neutral/
retention comparison. If it does not replicate, reconsider the carrier model
before adding a scaffold around it.
