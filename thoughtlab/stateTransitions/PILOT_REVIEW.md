# Checkpoint-fork pilot: findings for review

## Decision status

The first excluded fork pilot produced a coherent but incomplete signal. It did
not satisfy the prespecified full-fork composite, so the 30-trial confirmatory
program should **not** be approved yet.

The strongest preliminary observation is narrower:

> In the eligible Gemini 3.7 Flash fork execution, detached latest-response and
> cumulative thought bundles recovered exact opaque plan registries and utility
> rankings, plus some selected-plan state. A same-branch artifact from an
> unrelated donor trial recovered donor—not target—plan state. Successful
> visible-only and probe-only controls returned `unknown + []`.

This is evidence of artifact-specific, structured planning information beyond a
nonce. It is not yet evidence of complete branch-state recovery, selected versus
rejected partition recovery, or a self-contained checkpoint of shared ancestry.

## Execution ledger

| Run | Protocol | Generation | Tomography | Classification |
|---|---|---:|---:|---|
| pilot 01 | v1 | 0 eligible; local socket denied | 0 | sandbox feasibility failure |
| pilot 02 | v1 | 0 eligible; 64-token ceiling caused `incomplete` S0 | 0 | cap feasibility failure |
| pilot 03 | v2, 8,192-token ceiling | 14/14 eligible | 84 attempted; 74 evaluable | excluded incomplete pilot |
| pilot 04 | v3 bounded retry | donor S5A exhausted three transport attempts | 0 | pre-tomography infrastructure failure |

The v1 and v2 definition files were preserved at the exact hashes recorded by
their runs. V3 is a separate bounded-retry estimand and is not pooled with v2.
Raw request/response bytes and signed artifacts remain only in ignored local run
directories.

## Pilot 03 mechanical results

All 14 generation checkpoints were eligible:

- exact requested/returned model: `gemini-3.7-flash`;
- completed status, signed thought material, and exact acknowledgement shape;
- no visible identifier or utility leakage;
- exact shared P4 prefix for both children of each trial;
- distinct S5A/S5B response and thought-bundle hashes.

Probe outcomes were:

| Carrier arm | Evaluable | Exact target truth | Exact donor truth | Transport missing |
|---|---:|---:|---:|---:|
| full valid prefix | 12/14 | 12 | n/a | 2 |
| latest-response thought bundle | 12/14 | 4 | n/a | 2 |
| cumulative thought bundle | 12/14 | 5 | n/a | 2 |
| visible acknowledgement only | 13/14 | 0 | n/a | 1 |
| probe only | 12/14 | 0 | n/a | 2 |
| wrong-trial latest bundle | 13/14 | 0 | 4 | 1 |

Every evaluable full-prefix probe was exact. Every evaluable visible-only control
(13/13) and probe-only control (12/12) returned `unknown + []`, with no target-ID
leakage. The ten missing cells were remote disconnect, SSL EOF, or connection
reset errors distributed across every carrier class. No detached carrier was
rejected with HTTP 400.

### What the detached artifacts recovered

Using ground-truth aliases rather than reproducing opaque IDs:

- **Utility ranking:** latest and cumulative target bundles recovered the exact
  three-plan order in both S5A and S5B (4/4 evaluable target comparisons). The
  wrong-trial bundle recovered the donor ranking in both branches (2/2).
- **Candidate registry:** cumulative target bundles recovered all plans in both
  branches; the latest target bundle recovered them in S5B, while the S5A cell
  was transport-missing. The S5A wrong-trial bundle recovered the donor
  registry; its S5B counterpart was transport-missing.
- **Selected plan:** target S5A latest and cumulative bundles both recovered the
  exact maximum-utility selection. Target S5B latest returned unknown and the
  cumulative cell was transport-missing. The wrong-trial S5B bundle recovered
  the donor's minimum-utility selection; wrong-trial S5A returned unknown.
- **Rejected plans:** every evaluable latest, cumulative, and wrong-trial probe
  returned unknown. Exact rejected-set recovery was 0.
- **Shared ancestry, active objective, and active constraint:** every evaluable
  detached or wrong-trial probe returned unknown. These entries were recoverable
  from every evaluable full prefix, so this is not a ground-truth/scorer failure.

All 25 `known` responses across the run contained only prescribed target or
donor identifiers. There were no noncanonical or duplicate identifiers. The
four rows foreign to target truth were exactly the four donor-correct
wrong-trial results, as intended.

## Prespecified gates

| Gate | Pilot 03 |
|---|---:|
| generation eligible | pass |
| exact fork parent and distinct child artifacts | pass |
| complete evaluable full-prefix adherence composite | fail (2 transport-missing) |
| all controls evaluable `unknown + []` | fail (3 transport-missing) |
| wrong-trial full donor composite | fail (4/14 exact; 1 missing) |
| latest full-fork composite | fail (4/14 exact; 2 missing) |
| cumulative full-fork composite | fail (5/14 exact; 2 missing) |

The failures are not only transport-related. Even among successful responses,
shared ancestry and rejected-plan recovery were absent, and selected-plan
recovery was asymmetric. Therefore filling only the missing transport cells
would not make this pilot pass the original claim.

## Interpretation

The pilot supports three exploratory conclusions:

1. Detached Interactions thought bundles are accepted carrier shapes for this
   model/API configuration; none produced protocol rejection.
2. They expose an artifact-specific planning slice: exact candidate IDs,
   relative utility order, and some branch selection state.
3. The latest-response bundle was nearly as informative as the cumulative
   bundle for that planning slice, but neither behaved like a complete working
   state checkpoint.

It does **not** support these stronger claims:

- both children independently recover their complete selected/rejected plan
  partitions;
- rejected-plan lifecycle status is recoverable;
- shared fact/constraint/objective ancestry is encapsulated in the latest
  bundle;
- cumulative bundles reliably reconstruct complete state;
- Gemini thought signatures serialize or reveal full latent state or original
  chain-of-thought.

## Recommendation before any 30-trial program

Do not start the 30-trial confirmatory program yet. The next authorized action
should be one clean replacement execution under the already frozen v3 transport
policy, with the semantic result accepted regardless of outcome. A separate
stopping rule permits at most two pre-tomography replacement attempts and stops
at the first generation-eligible run; it does not permit rerunning an unfavorable
tomography result.

If that execution reproduces the planning slice but again fails ancestry and
rejected-state recovery, redesign the S5 state-acquisition instruction before
adding supersession/deactivation. If it cleanly recovers both branch partitions
and donor routing, then run the planned excluded S6/S7 pilots before freezing a
30-trial confirmatory protocol.

No further external run has been made because replacement execution requires
explicit user authorization.
