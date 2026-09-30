---
name: wqb-self-diagnostic
description: "Run objective post-session attribution and process-health evaluation on the structured trace produced by Trace 2.0 (reference/trace-schema-v2.md), then emit typed proposals to extend the agent's data and (eventually) prompts. Closes the self-evolution loop that wqb-self-analyst only opens (analyst… Part of the WorldQuant BRAIN auto-mining workflow (post-S9 (after wqb-memory-writer and wqb-self-analyst))."
---

# Skill: wqb-self-diagnostic

**Consumers**: Claude Code · GitHub Copilot · Codex · generic assistants.
**Stage**: post-S9 (after `wqb-memory-writer` and `wqb-self-analyst`)
**Budget cost**: 0 (no MCP calls; pure filesystem + Python)
**Auto-apply scope**: NEVER auto-modify this skill (`reference/trace-schema-v2.md` auto-apply blacklist).

## 1. Purpose

Run **objective post-session attribution and process-health evaluation** on the structured trace produced by Trace 2.0 (`reference/trace-schema-v2.md`), then **emit typed proposals** to extend the agent's data and (eventually) prompts. Closes the self-evolution loop that `wqb-self-analyst` only opens (analyst writes a human-readable report; diagnostic writes machine-readable metrics and proposals that the eval harness can act on).

Human-facing markdown output is Chinese-first by default. Keep JSON keys,
operator names, check names, and alpha IDs unchanged.

No metric, no evaluation: every diagnostic must produce a quantified scorecard. The scorecard evaluates the *mining process*, not only alpha outcomes, so a session with no qualified alpha can still pass if it produced complete, diverse, falsifiable evidence and a clean learning loop.

The two skills are complementary, not redundant:

| | `wqb-self-analyst` | `wqb-self-diagnostic` |
|---|---|---|
| Audience | human | harness + future diagnostic runs |
| Output format | markdown report | JSON proposals + JSON diagnostic |
| Closure | open (proposes via `pending-forbidden.jsonl`) | closed (proposals → eval → applied) |
| Touches MCP | no | no |

## 2. Inputs

```yaml
session_id: str          # required; the session to diagnose
dataset_hint: str | null # optional override if scope.started missing
force: bool              # default false; if true, overwrite existing diagnostic
```

If invoked by a Claude Stop hook, `session_id` is auto-derived from the latest entry in `metrics/sessions.jsonl`. Codex and other portable clients invoke this skill explicitly after S9 and should pass or derive the same latest `session_id`.

## 3. Outputs

```yaml
diagnostic_json: "analytics/diagnostic/<session_id>.json"
diagnostic_md:   "analytics/diagnostic/<session_id>.md"
process_health:
  overall_score: float          # 0..100, higher is better
  decision: "PASS|REVIEW"
  scores:
    trace_completeness: float
    execution_efficiency: float
    research_diversity: float
    learning_loop: float
    qualification_signal: float
    operator_coverage: float
    parameter_depth: float
    signal_mining_depth: float
  raw_metrics: object
  issues: list[object]
proposals_written: list[str]    # paths under analytics/proposals/pending/
proposals_skipped: list[str]    # signature-deduped against existing queues
record_events_emitted:
  - kind: diagnostic.proposal     # one per written proposal
```

## 4. MCP tools used

**None.** Pure filesystem + Python.

## 5. Steps

### Step 1. Idempotency check

If `analytics/diagnostic/<session_id>.json` exists AND `force == false` → exit 0 with status `"skipped_idempotent"`. Append a single record event:

```json
{"kind": "diagnostic.skipped", "session_id": "<sid>", "payload": {"reason": "already_diagnosed"}}
```

### Step 2. Run the analyzer

Invoke via Bash:

```bash
python3 scripts/diagnostic/analyze_session.py --session-id <sid> [--dataset <hint>] [--force]
```

This produces `analytics/diagnostic/<sid>.json` (machine) + `analytics/diagnostic/<sid>.md` (human). The Python script is **the source of truth** for the attribution analyses and process-health scorecard; do NOT re-implement them in skill prose.

The analyses (mirrored in `scripts/diagnostic/analyze_session.py`):

1. **Bandit-cell attribution** — for every `gate.tier`, walk back to the originating `bandit.sampled` (matched by hypothesis_id) and join `(cell, posterior, sampled_value) → outcome`. If a portable run emitted legacy compact `batch.preflight` / `batch.results` without `gate.tier`, `scripts/diagnostic/analyze_session.py` now synthesizes read-only Trace-like events before analysis and marks them `legacy_synthesized=true`.
2. **Field attribution** — per REJECT, decompose by `field.scored.components` (when v2 emit is wired) or fall back to v0.3 fields-list. Distinguish "memory-driven" vs "prior-driven" picks.
3. **Repair attribution** — aggregate `repair.step` (which mutation ops are perpetually blocked pre-dispatch) vs `repair.attempted + repair.failed` (which dispatch but fail re-gate).
4. **Coverage-gap analysis** — enumerate the (task_type × paradigm) cube and flag zero-trial cells in the v0.3 default sub-cube and full v0.4 cube.
5. **Structural-entropy detection** — op_class histogram + paradigm distribution + (n_fields, depth) joint. Triggers a proposal if normalized op_class entropy < 0.6.
5a. **Operator/parameter coverage audit** - exact operators used vs the REGULAR
operator universe, op-class entropy, rare/unseen operator families, and
parameter-rich operator depth. This prevents a few familiar operators from
becoming an invisible bias.
5b. **Hypothesis/field/signal-depth audit** - task/paradigm/L0/L1/L2/track
diversity, unique fields/roles/pairs, and evidence coverage from raw field to
L0, L1, L2, robustness, correlation, and overfit.

5c. **Hypothesis-failure attribution** (added 2026-05-08, Phase 2) — for every `hypothesis.falsified` event in this session, validate its `failure_class` against:
  (a) the 4 children's alpha-level `failure_category` distribution from `gate.tier`,
  (b) `attribution.root_cause_layer` from `attribution.generated`,
  (c) yearly stats / risk-neutralized Sharpe / sub-universe pass from `robustness.audited`.
The 12-class enum + symptom→class mapping + research response is in `reference/failure-taxonomy.md §Hypothesis-level Failure Taxonomy`. If the writer's `failure_class` choice mismatches the symptoms, emit `diagnostic.proposal { scope_tier: "data", target_path: "memory/{region}/hypothesis_failures.jsonl", change_type: "patch", proposal: "reclassify failure_class for h-... from X to Y" }`. Aggregated rows are appended to `memory/{region}/hypothesis_failures.jsonl` keyed by `(hypothesis_id, failure_class)` (idempotent rewrite by key) so cross-session S2.1 `research_gap_scan` can read `falsified_mechanisms_to_avoid` from this file.

6. **Process-health scorecard** - score the session across trace completeness, execution efficiency, research diversity, learning-loop closure, and qualification signal. This is the primary metric for workflow optimization.

### Process-health scorecard

All component scores are 0..100, higher is better. `overall_score` is:

```text
0.25 * trace_completeness
+ 0.20 * execution_efficiency
+ 0.25 * research_diversity
+ 0.20 * learning_loop
+ 0.10 * qualification_signal
```

| Dimension | What it measures | Core raw metrics | Review trigger |
|---|---|---|---|
| `trace_completeness` | whether the session is diagnosable | required stage presence, child outcome coverage, preflight coverage | `< 70` |
| `execution_efficiency` | whether budget produced clean outcomes | sim success rate, unresolved/timeout rate, gate coverage | `< 70` |
| `research_diversity` | whether search avoided local narrowness | cube coverage, op entropy, operator coverage, parameter depth, paradigm entropy, task entropy, 2+ field ratio, signal-depth coverage | `< 60` |
| `learning_loop` | whether post-S9 feedback closed | memory update, session summary, self-analyst, external consult ratio | `< 80` |
| `qualification_signal` | whether the session produced useful alpha evidence | reject rate, PROMISING+ rate, SUBMITTABLE_PENDING/CONFIRMED rate | all-reject windows after >=8 children |

Decision:

- `PASS`: `overall_score >= 75` and no high-severity issue.
- `REVIEW`: any high-severity issue, or `overall_score < 75`.

Interpretation rules:

- Low `qualification_signal` alone does not prove the process is bad; it may prove the source is weak.
- In a manual-submit campaign with an unreached target, low `qualification_signal`
  is a continuation directive, not a stop condition. The next loop must carry
  the issue into attribution, S2.5 source/L0 rebuild, or a valid dataset-switch
  gate; it must not end the campaign after S9.
- Low `trace_completeness` invalidates downstream interpretation until logging is fixed.
- Low `research_diversity` means next S3/S4 should broaden source/operator/field-arity coverage before drawing dataset conclusions.
- Low `operator_coverage` or `parameter_depth` means next exploration slots
  should try compatible underused operator families or parameter neighborhoods,
  not random wrappers.
- Low `execution_efficiency` means recover unresolved simulations before spending more budget.
- Low `learning_loop` means S9/self-analyst/self-diagnostic/external records did not close cleanly; do not feed the session into deep synthesis without marking the gap.

### Step 3. Emit proposals

Invoke via Bash:

```bash
python3 scripts/diagnostic/emit_proposals.py --session-id <sid>
```

This reads `analytics/diagnostic/<sid>.json` and writes typed proposals to `analytics/proposals/pending/<id>.json`. Phase 2 emits 3 proposal types (all `data` tier — minimum blast radius):

| Generator | Trigger | Target | scope_tier |
|---|---|---|---|
| `gen_coverage_gap_proposal` | default cube coverage < 50% | `memory/{region}/next_session_priorities.jsonl` | data |
| `gen_field_forbidden_proposal` | field with `trials >= 3 ∧ 100% REJECT` | `analytics/pending-forbidden.jsonl` | data |
| `gen_structural_entropy_proposal` | `is_under_explored_op_class == true` | `memory/{region}/next_session_priorities.jsonl` (data) **or** `skills/wqb-hypothesis-designer.md` (skill_prompt) | data \| skill_prompt |

| `gen_process_health_proposal` | `process_health.decision == REVIEW` with concrete issues | `memory/{region}/next_session_priorities.jsonl` | data |

For each written proposal, the emitter ALSO appends a `diagnostic.proposal` event to `records/<today>.jsonl` with `session_id = <source sid>`. This closes the loop: future diagnostic runs see what was already proposed and avoid re-proposing (signature dedup) or building proposals on top of unstable evidence (lineage check via `source_proposal_id`).

**Idempotency**: each proposal carries a `signature` (sha256 of `target_path + change_type + change_summary`); if the same signature exists in any of `pending/`, `applied/`, `rejected/`, the proposal is skipped.

### Step 4. (Phase 2 done) Just report — do NOT apply

In Phase 2, no proposal is auto-applied. The eval harness + `apply_proposal.sh` (Phase 5) consume the queue. This skill's job ends at queueing.

## 6. Events emitted

`diagnostic.proposal` (×N), `diagnostic.skipped` (when idempotent short-circuit fires).

The diagnostic JSON itself is NOT a record event (it's persistent state in `analytics/diagnostic/`).

## 6.5 Workflow integration

Run order:

1. S9 `wqb-memory-writer` closes records and memory.
2. `wqb-self-analyst` writes the human cross-session report.
3. `wqb-self-diagnostic` writes the machine scorecard and proposal queue.
4. If the 10-round gate is due, the strategy-diversity gate (`scripts/session_gate.py strategy-diversity`) must run before the next budget-spending batch; its plan should treat `process_health`, operator coverage, parameter depth, and signal-mining depth as inputs.

Integration rules:

- If `process_health.decision == REVIEW`, the next mining loop may continue, but it must carry the top issues into S2/S2.5/S3/S4 planning.
- If `trace_completeness < 70`, do not promote lessons from this session to validated memory; first fix logging or mark the evidence as partial.
- If `execution_efficiency < 70`, prioritize recovery/accounting over more simulation spend.
- If `research_diversity < 60`, the next batch should explicitly widen task_type, paradigm, operator class, or 2-field L0 coverage.
- If operator or parameter coverage is narrow, the next batch should include a
  compatible exploration slot for an underused REGULAR operator family or a
  parameter-neighborhood probe.
- If `learning_loop < 80`, rerun or repair post-S9 closure before deep synthesis consumes the session.
- If `qualification_signal` is weak while the other scores pass, treat it as source/dataset evidence rather than workflow failure.

## 7. Constraints

1. **Never call MCP**.
2. **Never modify `memory/`, `skills/`, `workflow/`, or `reference/` directly.** Proposals go through the harness.
3. **Never propose changes to itself** (`skills/wqb-self-diagnostic.md`) or the eval harness (`tests/eval/*`, `scripts/eval/*`) — Phase 5 black-list enforces this even if a buggy proposal escapes.
4. **Idempotent**: re-running for the same session is a no-op (unless `--force`).
5. Single-session scope: this skill operates on ONE `session_id` per invocation. Cross-session trends are `wqb-self-analyst`'s job.
6. Lineage tracking: every proposal carries `source_proposal_id` (null on first generation) so Phase 5's environment loop detector can refuse to consume evidence from < 3-session-old applied proposals.

## 8. Self-validation

- [ ] `analytics/diagnostic/<sid>.json` exists with `ok == true`
- [ ] `analytics/diagnostic/<sid>.md` exists and renders the scorecard plus all 5 attribution sections
- [ ] JSON contains `process_health.overall_score`, 5 component scores, raw metrics, `decision`, and issues list
- [ ] Markdown renders the **流程健康评分** before detailed attribution sections, in Chinese-first form
- [ ] Markdown and JSON include operator coverage, parameter-depth, hypothesis diversity, field diversity, and signal-mining depth
- [ ] `proposals_written` is a (possibly-empty) list of files under `analytics/proposals/pending/`
- [ ] Each written proposal validates against `reference/trace-schema-v2.md §3.7` schema
- [ ] One `diagnostic.proposal` event in `records/<today>.jsonl` per written proposal, linked by `proposal_id`
- [ ] No file outside `analytics/` was modified by this invocation

## 9. Phase roadmap

| Phase | Capability |
|---|---|
| 2 (current) | 6 analyses including process-health scorecard, 4 proposal generators, queue-only |
| 3 | add rolling/session-window trend deltas for process-health components and incorporate forum/web evidence into coverage proposals |
| 4 | add `track`/`structural_features`-driven proposals (e.g. "DFS slot is converging — propose seed rotation") |
| 5 | invoked after S9 (Claude may use `.claude/settings.json` Stop hook; Codex invokes explicitly); outputs feed `apply_proposal.sh`; rolling 5-session monitor for `proposal.regressed` |
