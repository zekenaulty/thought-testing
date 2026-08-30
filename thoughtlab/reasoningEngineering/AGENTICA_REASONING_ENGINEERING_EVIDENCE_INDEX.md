# Agentica Reasoning Engineering Evidence Index

## Scope

This index identifies the evidence behind the demonstrated claims carried into
the Agentica architecture candidate. It is a provenance map, not a new
experiment and not an independent re-adjudication of the semantic findings.

Private provider artifacts, signed native carriers, credentials, and ignored
run payloads are deliberately excluded from the review packet. The public seals
and summaries permit integrity and protocol checks; a full raw-artifact audit
must occur inside the authorized `thought-testing` environment.

All hashes below are SHA-256 over the named file bytes unless explicitly called
an internal source-closure or semantic-payload hash.

## Completed source occurrence

```text
occurrence: modernization_reasoning_engineering_generate_content_review_01_occurrence_04
freeze_id: 262b3d0a3908b154f6f694b37b8f4548c49963a1bbd8dff2033218a5891ed5fe
provider_method: Gemini Developer API generateContent
model: gemini-3.7-flash
verified_final_seal_sha256: 613996094ab2379fec7f34935c391c3fc8ce2c7ddd04f561b87c35c865b3f2de
frozen_source_closure_sha256: 840ba09692665b90c38de06cb390b6382bde923e757860da9c7290d27b13aa49
terminal: COMPLETED_EVIDENCE_CHAIN
```

Before the post-freeze root-README correction, the verifier reproduced the final
seal byte hash with this PowerShell command:

```text
python -u -m thoughtlab.reasoningEngineering.modernization_pilot verify-phase-two --run-dir results/reasoning_engineering/262b3d0a3908b154f6f694b37b8f4548c49963a1bbd8dff2033218a5891ed5fe --freeze-dir thoughtlab/reasoningEngineering/freezes/modernization_reasoning_engineering_generate_content_review_01_occurrence_04 --freeze-id 262b3d0a3908b154f6f694b37b8f4548c49963a1bbd8dff2033218a5891ed5fe
```

Expected output:

```text
sha256_bytes=613996094ab2379fec7f34935c391c3fc8ce2c7ddd04f561b87c35c865b3f2de
```

The completed occurrence byte-bound the earlier root README:

```text
README bytes: 9413
README sha256: 7fe130fe54a6a67a274e2f26f9d7e8f56b69c7536634470f0d805577a8be06a7
recorded git head: dbf8569a2e7a8673e86dbb56cea16bcc7842b180
```

The root README was intentionally corrected after the occurrence to explain
that the carrier is not a ViewState-like state contract. Therefore, direct
`modernization_freeze verify` against the current live tree now correctly
reports JSON containing these normalized findings:

```text
valid: false
source file changed: README.md
source inventory changed during verification
```

The `modernization_pilot verify-phase-two` wrapper stops before artifact-seal
verification and raises `ValueError` citing the same two source-closure reasons.

This is documented post-freeze source drift, not a changed result seal. Full
reproduction requires an isolated copy of the freeze-era source closure with
the recorded README bytes restored from the recorded Git snapshot; do not
rewrite the historical manifest, lock, or seal. Artifact identities and the
previously reproduced final seal hash remain the values recorded above.

## Demonstrated-claim map

### `E0` — exact capture and authorized live replay, scoped

Claim: in occurrence 04, the transport captured complete provider-native model
`Content` and preserved the authorized live-parent content unchanged when
constructing continuation requests. Both baseline and adjusted live-planning
branches produced eligible `READY` checkpoints.

Primary evidence:

- frozen protocol, manifest, and experiment definition;
- baseline and adjusted planning-attempt and planning-summary artifacts; and
- the final phase-two seal and summary.

Qualification: this establishes exact request construction and eligible
continuation in the tested Gemini Developer API configuration. It does not prove
provider-internal determinism, decode a thought signature, or establish that
every future carrier is replayable.

### `E1` — isolated semantic recovery, scoped

Claim: a protocol-defined blank-visible derivative of exact captured signed
model content—with existing `Part.text` blanked, signature bytes and frozen part
topology preserved, ordinary task/history suppressed, and an inspection query
appended—produced a detailed dossier-specific `ProjectionArtifact` from a
planning response whose visible status was only `READY`.

Primary evidence:

- frozen protocol and experiment definition;
- baseline observation artifact;
- final phase-two seal; and
- occurrence 04 adjudication.

Qualification: this demonstrates query-conditioned semantic recovery in the
tested configuration. It does not prove verbatim hidden chain-of-thought,
complete state recovery, or universal projection fidelity.

### `E2` — targeted reasoning-state mutation, scoped

Claim: after a frozen diagnosis, prediction, and bounded intervention targeted
coupled cost, staffing, and calendar assumptions, the adjusted isolated
observation made the predicted relationships more explicit.

Primary evidence:

- sealed diagnosis, prediction, intervention, and intervention lock;
- baseline and adjusted observation artifacts;
- phase-two summary and trace review; and
- occurrence 04 adjudication.

Qualification: the semantic comparison is an adjudicated interpretation of
sealed artifacts, not a deterministic proof that a hidden state literally
contains a named variable.

### `E3` — preservation and downstream propagation, scoped

Claim: several unrelated commitments persisted after intervention, while all
three adjusted execution replicates more explicitly exposed cost ranges,
funding provenance, and conditioned legacy/security fallbacks.

Primary evidence:

- baseline and adjusted observation artifacts;
- six matched execution artifacts;
- phase-two trace review; and
- occurrence 04 adjudication.

Qualification: repetitions from one frozen host are nested replicates, not
independent population participants.

### `E4` — `READY` is not substantive validation

Claim: both baseline and adjusted planning states emitted `READY`, while the
isolated observations distinguished improvement from unresolved coupling.

Primary evidence:

- planning and observation summaries committed into the final seal;
- phase-two summary; and
- occurrence 04 adjudication.

### `N1` — robust semantic repair not demonstrated

The adjusted state still relied on favorable range points or unresolved vendor
offsets and did not consistently reconcile the six-month shadow requirement
with readiness and cutover dates. The architecture must retain this as a
negative boundary, not average it into the positive findings.

## Public evidence identities

| SHA-256 | Bytes | Artifact |
|---|---:|---|
| `add39592e065c3147cc868e93c3cad59d624f99502945ec19226a72638cb3dc8` | 4,564 | `MODERNIZATION_REASONING_ENGINEERING_OCCURRENCE_04_ADJUDICATION.md` |
| `736bb672172b2edc33db2c2c146e36f382b6098833cf99b61266361aaae44128` | 14,476 | `MODERNIZATION_REASONING_ENGINEERING_DESIGN.md` |
| `cd43ccea4384a7e84746e0de7151071812464b9591db7893bedb33ee0f784fd4` | 6,310 | occurrence 04 `manifest.json` |
| `f5f2058c3356f3a2311387d1aa4735b34e6cdb32bd71e2bfca391335aaa3f72e` | 2,297 | occurrence 04 `preregistration.json` |
| `464998ab1e976d792f4fe42e92a54c1eaf0fab5bc0d475605105e46ca714911a` | 109,250 | occurrence 04 `experiment_definition.json` |
| `8262800b85e815579e0903ac77d351b8e1bf338d05606233c61c05888bd6b108` | 1,052 | occurrence 04 `validation_report.json` |
| `367033ad4ab94ef52dc5029cad8ac60016873015c9e0f38032510f40c440a57b` | 1,597 | occurrence 04 `baseline_planning_attempts.json` |
| `449ccc34fa2fbd3a2fe3afcb1ba533d27209b96e179dfaf7371527aaaff77293` | 3,709 | occurrence 04 `baseline_planning_summary.json` |
| `d6e058cfe666e9cf2c82cf63782ed97c8a91d7dfc972a285c1ba937112f5ecc5` | 1,598 | occurrence 04 `adjusted_planning_attempts.json` |
| `6d6e2b1a7c7bc69a83457bfdaa910732d9ff4537989e7fa6e5ad94f6c274a457` | 3,711 | occurrence 04 `adjusted_planning_summary.json` |
| `3585e78befc25bc59b0fa770189279e64e861744e74e822f25e5790f5395eeda` | 822 | occurrence 04 `phase_two_summary.json` |
| `bbeebc74f6efa31233c3e15a562aa71d5fb6cfca6fb91e34c0ead2e76000bdb1` | 15,998 | occurrence 04 `baseline_observations.json` |
| `5e9a17b9edad79e7dee1816346cf311ec2f8af672b21a61d8e8389b0f8fbb956` | 415 | occurrence 04 `baseline_observation_seal.json` |
| `af6314ecacae151589dad063d9704d017024f7c700bf0375d49f4c6c42021bf9` | 10,095 | occurrence 04 `adjusted_observations.json` |
| `87a1cb5110a54a3535f16b820f1d43ea3022cf9e49353fc7a2c0169f3400dc89` | 415 | occurrence 04 `adjusted_observation_seal.json` |
| `2e880dbf5822561e48cbfc7fb206ba73f174a8c5f07dcf3cd5c6b384751adfd5` | 234,420 | occurrence 04 `executions.json` |
| `a2da3578209a5ac4bb29003fa694adb5af1b1a5668e352cad3355c55a5dba628` | 8,785 | occurrence 04 `PHASE_TWO_TRACE_REVIEW.md` |
| `613996094ab2379fec7f34935c391c3fc8ce2c7ddd04f561b87c35c865b3f2de` | 12,627 | occurrence 04 `phase_two_seal.json` |
| `366183bcbb6df308f6174f2d0dee6333e0d8ce70ecd93b5b30061e7048ea11cf` | 901 | occurrence 04 `intervention/diagnosis.md` |
| `ebf3f08b31258c7fe35abda61c43a04da61aa6d53efca16098ef450613e17f43` | 1,118 | occurrence 04 `intervention/prediction.md` |
| `eaf8f009d7577185d2f30160e4db4cfc04e39b359aa68647c8b64864250cebcd` | 517 | occurrence 04 `intervention/intervention.txt` |
| `9ba63f859427188e287a0cc1ed0632898e535ddd3a249100f85a76822fa32b20` | 762 | occurrence 04 `intervention/intervention.lock.json` |

The `phase_two_summary.json` contains internal semantic-payload hashes for the
intervention artifacts. Those intentionally differ from the byte hashes above
when the sealed representation is normalized.

## Active iterative occurrence: status only

```text
freeze_id: 15865775a8ea7bd18461793888d8622c86dd9567ea71ebad2c3da81c6a8bf134
verified_through: C0
physical_call_count_through_C0: 2
completed_repair_trajectory: false
```

Public status identities:

| SHA-256 | Bytes | Artifact |
|---|---:|---|
| `ad6c654c1cd9260d892650262469b8fb021ea47b6f99b51b791e3a6e63ed0e64` | 21,747 | `MODERNIZATION_ITERATIVE_REASONING_ENGINEERING_DESIGN.md` |
| `48fd2a074b8c2859d32ab7946e9b61a4dd5d74f6bb7a0b719fb3e8133c498035` | 5,760 | active iterative `manifest.json` |
| `8bd8c1c20e933b9590fb54776397847dfd6085ff0153f441342f64bae7107e7c` | 8,914 | active iterative `preregistration.json` |
| `ef33cfa553f7952a1eefac176168729c00faee8fd1ae6c45fba95bd1103bb31f` | 1,241 | active iterative `validation_report.json` |
| `2bac28dd7533742a89a19c713a180afaf934387307e89be0b5590c4a082e9ad9` | 4,266 | active iterative `c0_stage_seal.json` |
| `1488ef73a4a583817f35c2bd3b0b7c9d371241b9d0aa9972206fa69a0958dbb2` | 4,368 | active iterative unsealed `i1/examiner_review.md` |

The external examination is recorded and parser-valid but does not complete or
seal `I1`. It is not evidence of a completed iterative repair trajectory.

## Review limit

A fresh Agentica context receiving only the conceptual packet may audit:

- whether each architecture claim is labeled consistently with this index;
- whether the candidate abstractions preserve the listed limitations; and
- whether the exact supplied file identities match the packet manifest.

It may not claim an independent raw-artifact replication without access to the
authorized result archive and verifier. Any broader scientific conclusion must
be returned as `NOT_AUDITABLE_FROM_PACKET`.
