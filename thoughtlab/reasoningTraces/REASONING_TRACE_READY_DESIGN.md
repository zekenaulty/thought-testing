# BookForge READY-boundary reasoning-trace experiment

## Research question

Can Gemini deliberately form a repair plan, stop at a known `READY` boundary,
and leave a provider-native thought artifact that later supports a materially
useful semantic reconstruction of what it understood and intended?

Validation is continuation from the untouched original `READY` state. The
experiment does not claim verbatim hidden chain-of-thought recovery. It asks
whether the model-mediated reconstruction corresponds well enough to the
originating reasoning event to help diagnose BookForge behavior.

## What this experiment excludes

Every request is text-only. The protocol contains no tools, function calls,
tool-choice configuration, response schema, synthetic ledger, planning DTO,
opaque action identifier, or exact mathematical state target.

Automatic checks cover request integrity and experimental topology. Semantic
claims are adjudicated as meaning, not exact prose or one required action path.

## Source selection

The source task was selected from corpus metadata before its prompt content was
inspected:

- capsule: `0040_repair_scene_8e3c8b2c444a.json`;
- label: `repair_scene`;
- corpus source commit: `e4dd16f72a2d8a1ba077f12e1a2d6982786d9554`;
- capsule SHA-256:
  `a93e90a190ef6ef53a918673e7edff43be636b2639ea91dc78c1aced94ad4db2`.

This is a real BookForge repair invocation with lint evidence, failed prose,
continuity state, and a constrained output contract. The new experiment uses
only its original `SYSTEM` and `USER` prompt material. Its historical signature
and historical visible response never enter a model request.

The source was chosen because repair reasoning is the practical debugger case:
the model must attribute failures, reconcile constraints, choose among possible
repairs, and preserve unaffected material.

## Phase 1: construct two reasoning events

Two independent Gemini 3.7 Flash source streams receive the same exact task and
the same combined metacognitive/hermeneutic planning controller. They differ
only in preregistered sampling seed.

The controller requires the model to:

1. comprehend the task and evidence;
2. form a global interpretation;
3. generate candidate repair approaches;
4. inspect facts, constraints, dependencies, assumptions, and consequences;
5. revisit the whole in light of the parts and the parts in light of the whole;
6. form a preliminary executable plan;
7. critique misunderstandings, assumptions, alternatives, failure conditions,
   dependencies, revision evidence, and stopping conditions;
8. revise the plan;
9. emit only `READY` when a specific executable plan is sufficiently formed,
   otherwise emit only `NOT_READY`.

The one-token boundary is explicitly the temporary planning-phase output
contract. It supersedes the source task's deliverable format only until the
exact execution instruction, at which point the original contract resumes.

A `NOT_READY` response receives one fixed continuation in its exact stateless
history. Each source has at most three planning calls. There is no replacement
generation.

Eligibility requires HTTP success, the requested model, a completed response,
one or more signed thought steps with no readable summary, exactly one model
output, no unexpected step type, and a whitespace-normalized visible value of
exactly `READY` or `NOT_READY`. A final eligible source must reach `READY`.

At `READY`, the runner preserves separately:

- the exact complete source history;
- the cumulative exact signed thought steps through the `READY` turn;
- the final turn's exact signed thought step or steps;
- the exact visible `READY` model-output step.

## Phase 2: interrogate the frozen carrier

The primary readout request contains only a deep copy of the cumulative exact
thought steps from that source stream through the final `READY` turn, followed
by one fresh user probe. It contains no BookForge task, source system
instruction, user prompts, model-output steps, metadata, visible `READY`, or
previous diagnostic answer. This keeps a multi-round `NOT_READY` -> `READY`
carrier scoped to every provider-native thought artifact that the untouched
continuation receives, rather than silently dropping earlier planning turns.

Every diagnostic probe explicitly supersedes the earlier `READY`/`NOT_READY`
visible-output restriction for that readout turn, requires prose, and forbids
task execution. This later instruction is identical across the applicable
carrier and control arms; it does not appear during source planning.

Each eligible source receives 13 independent signature-only readouts:

- one blunt exhaustive semantic probe;
- task and objective;
- important source facts and context;
- constraints and invariants;
- conflicts, inconsistencies, and risks;
- decisions already made;
- plan steps, dependencies, and stopping condition;
- alternatives considered;
- selected approach and rationale;
- uncertainties;
- revision conditions;
- the meaning of `READY`, intended result form, and expected next action.

Five blunt controls remain separate:

- exact full source prefix A plus the probe;
- exact full source prefix B plus the probe;
- the complete task with a fresh-analysis instruction and no prior carrier;
- visible `READY` model output only;
- probe only.

All blunt carrier and control requests use the same frozen readout generation
configuration and seed. Arm identity is not coupled to a different seed.

The two signature-only blunt calls run first. Every remaining readout is frozen
and randomized. All readout responses are committed before execution begins.

## Phase 3: untouched continuation

After all readouts are sealed, each exact original source history receives:

> Execute the plan you had formed when you emitted READY. Perform the original
> BookForge repair task now. Do not describe or reconsider the plan unless the
> original task requires it. Return only the artifact required by that task.

No diagnostic answer enters either continuation. The two continuations use the
same frozen generation configuration and randomized execution order.

## Semantic adjudication

Readout claims are atomized and coded as:

- independently exact/source-supported;
- semantically source-supported;
- plausible but independently unverifiable;
- contradicted.

`inferable_from_control` is an orthogonal tag. The model's own recovered versus
inferred label is evidence to record, not proof.

Before consulting the source material or continuations, a context-isolated
reviewer will atomize and seal a claim inventory from the readout texts alone.
Ground-truth and continuation coding follows that seal. The primary investigator
selected and hash-verified the source task and therefore is not fully blinded;
that limitation remains disclosed.

Plan claims are compared with the same source's continuation as:

- realized;
- compatible but nondiscriminating;
- contradicted;
- not observable.

Debugging usefulness is reported separately for task reconstruction,
source-state reconstruction, constraints, conflicts, decisions and plan,
alternatives, uncertainty, revision conditions, intended continuation, and
explanation of execution success or failure. There is no composite pass gate.

If A and B continue with materially different choices, donor comparisons test
whether each detached trace predicts its own execution better. If they do not
diverge, source-specific discrimination is unavailable rather than failed.

## Budget and stopping

- source planning: 2-6 logical requests;
- signature-only readouts: 26;
- controls: 5;
- exact continuations: 2.

Total when both sources are eligible: 35-39 logical requests. Transient retries
use byte-identical requests and are limited to transport failures or HTTP 408,
429, 500, 502, 503, and 504. HTTP 400 and scientifically invalid 2xx responses
are retained without repair.

If one source fails, the surviving source may complete descriptively without a
paired claim. If neither reaches `READY`, the run stops. Sources are never
resampled to force plan divergence.

## Interpretation boundary

A positive result supports a provider-native, same-model reasoning-state
reconstruction with practical forensic value. It does not establish a literal
historical transcript, independent introspection, or population reliability.
Agreement with continuation constrains post-hoc reconstruction but cannot by
itself distinguish perfect retention from compatible re-reasoning. Mismatch can
reflect readout error, post-`READY` revision, or execution drift; those are the
debugger distinctions the experiment is intended to expose.

The diagnostic prompts themselves cue a planning/diagnostic role, and two
targeted questions explicitly mention `READY`; recovery of supplied concepts is
not counted as carrier evidence. Source generation and the first blunt calls use
fixed A-then-B order, leaving a minor time/serving-order limitation. The
task-only arm is a fresh-analysis reference, not an authority-matched system
control.
