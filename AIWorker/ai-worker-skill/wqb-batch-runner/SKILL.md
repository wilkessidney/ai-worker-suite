---
name: wqb-batch-runner
description: "Take 4 structured hypotheses, convert their expression_sketch values into runnable expressions, dispatch them in a single create_multi_simulation call (server-side handles concurrency), collect the returned child results, and hand the results to wqb-quality-gate. Part of the WorldQuant BRAIN auto-mining workflow (S4 of workflow/auto-mining.md)."
---

# Skill: wqb-batch-runner

**Consumers**: Claude Code · GitHub Copilot · OpenAI Codex · generic LLM assistants
**Stage**: S4 of `workflow/auto-mining.md`
**Budget cost**: 1 unit per child simulation in the multi-sim payload (typical batch = 4 children = 4 units; failed children still consume)

> **MCP output shapes** — `create_multi_simulation` / `get_alpha_details` now return *slimmed* JSON. Each `alpha_results[]` entry is flattened (`alpha_id, location, id, code, status, settings, metrics{…}, checks{fail,warning,pass,pending}, pyramids{effective,list}`) — no nested `.details.is.checks[]`. Translation map in `reference/mcp-output-shapes.md`.

## 1. Purpose

Take 4 structured hypotheses, convert their `expression_sketch` values into runnable expressions, dispatch them in a **single** `create_multi_simulation` call (server-side handles concurrency), collect the returned child results, and hand the results to `wqb-quality-gate`.

> **`diversity_probe` mode (2026-07-03, template on-platform validation only):** batches emitted by `scripts/templates/onplatform_validate.py --prepare` (the Phase-4 template-validation sweep) are **validation probes, not mining candidates**. For these, the 5-lock diversity contract runs in **report-only** mode — only the ghost-op + fingerprint locks are blocking (the batch just confirms each template *compiles + produces cross-sectional signal*). Such probes MUST carry a `diversity_probe: true` marker, are dispatched with the standard harness settings (USA/TOP3000/D1, decay12/trunc0.08/SUBINDUSTRY), and are kept **out of** `records/<date>.jsonl` mining counts and the 10-round strategy-diversity gate. **Normal S4 mining batches are unaffected — they still enforce all 5 locks.** Note: a bad expression cancels its multi-sim batch-mates, so probes are pre-validated (ghost + fingerprint) before dispatch, and category carriers are replaced with always-valid pv primitives during validation.

## 2. Inputs (YAML)

```yaml
hypotheses: [<4 hypothesis dicts from wqb-hypothesis-designer>]
batch_settings:
  instrument_type: "EQUITY"
  region: "USA"
  universe: "TOP3000"
  delay: 1
  decay: 8
  neutralization: "CROWDING"
  truncation: 0.08
  pasteurization: "ON"
  unit_handling: "VERIFY"
  nan_handling: "OFF"
  language: "FASTEXPR"
  visualization: false
  reason: "shared setting chosen by S3; candidate-level suggested_params are advisory"
session_state:
  session_id: s-YYYYMMDD-<letter>
  budget_remaining: int
  region: "USA"
  universe: "TOP3000"
  delay: 1
memory_snapshot:
  fingerprints: set[str]                # memory/{region}/fingerprints.txt
  forbidden_patterns: list[{regex, blocked_until}]  # memory/{region}/forbidden_patterns.jsonl (unexpired)
  submitted_overlap_corpus: list[{alpha_id, canonical_expr, zfield_id, raw_field_set, l1_operator, lookback, neutralization}]
                                        # from memory/{region}/submittable_seeds.jsonl + cached submitted/saved alphas (this region only) — for the early self-corr proxy in Phase A step 8
  param_sweep_counts: dict              # session_state-carried: {(blanked_skeleton, param_family): count} over the rolling 2-batch window
platform_snapshot:
  operators: set[str]                   # names from data/platform/operators.json
  valid_neutralization: list[str]       # from data/platform/settings_options.json
research_snapshot:
  require_zero_order_provenance: true
  dataset_preprocessing_template: "ts_rank(ts_backfill(winsorize(Z, std=4), lookback=63), 189)"
  dataset_selection_mode: high_usage | low_usage | fixed_dataset
  robust_cohort_context:
    required_next_two_batches: bool
    trigger_checks: list
    candidate_axes: list
  l1_parent_bank: list                # optional: parent alpha diagnostics for L2 validation
  structural_similarity_threshold: 0.70
  latest_strategy_diversity_check: dict | null
  strategy_diversity_check_required_when_due: true
  require_template_skeleton_diversity: true
  min_template_families: 3
  min_template_stage_paths: 3
  max_per_template_family: 2
  require_operator_class_diversity: true
  min_operator_classes: 5
  min_operator_class_pairs: 4
  max_per_operator_class_pair: 1
  max_core_class_presence: 3
  require_explicit_operator_class_exclusion: true
  min_explicit_excluded_operator_classes: 3
  allowed_common_operator_classes: ["vector_collapse"]  # VECTOR boilerplate only; do not allow ratio/group everywhere by default
```

## 3. Outputs (YAML)

```yaml
batch_id: b-<session_id>-<N>
dispatched: int
succeeded: int
failed: int
timed_out: int
alpha_ids: list[str]          # for succeeded sims only
metrics: list[dict]           # {alpha_id, is: {sharpe, fitness, margin, turnover, returns, drawdown}}
is_checks: list[list[dict]]   # parallel to alpha_ids
risk_neutralized: list[dict]
sim_errors: list[dict]        # {candidate_id, sim_id, error_code, error_msg}
unresolved: list[dict]        # polling/MCP wrapper timeouts that may still be running server-side
budget_consumed: int          # sum of dispatched calls (includes failures)
hypotheses_with_metrics: list[dict]  # for hand-off to wqb-quality-gate
```

On `batch.all_failed` → returns with `succeeded=0`; outer loop increments `consecutive_empty`.

## 4. MCP tools used (bare names)

| Tool | When | Frequency |
|---|---|---|
| `create_multi_simulation` | Phase B once per batch | 1 call per batch (carries exactly 4 `alpha_expressions[]` + shared settings) |
| `lookINTO_SimError_message` | per failed child | per failure |
| `get_alpha_details` | Phase C per succeeded child | per success |

No single-sim `create_simulation`. No `submit_alpha`. No `check_correlation` (that's S5).

## 5. Steps

### Phase A — Pre-flight (atomic over ALL hypotheses)

1. Assign `batch_id = b-<session_id>-<N>` where N = monotonic counter in session_state.
2. **Compute `fingerprint`** for each candidate using the shared `batch_settings`. **Canonicalize the expression first** (lightweight — no full AST), so algebraically-equivalent-but-textually-different expressions hash to the same fingerprint and don't waste a sim child:
   ```python
   def canonicalize_expr(e):
       e = lowercase_and_collapse_whitespace(e)
       # numeric literals: ".5"->"0.5", "1.0"/"1.000"->"1", strip trailing zeros, "+3"->"3"
       e = normalize_numeric_literals(e)
       # idempotent / self-inverse collapses (apply to fixpoint):
       #   reverse(reverse(x)) -> x ;  not(not(x)) -> x ;  inverse(inverse(x)) -> x
       #   abs(abs(x)) -> abs(x) ;  sign(sign(x)) -> sign(x) ;  rank(rank(x)) -> rank(x)
       #   subtract(a, b) -> add(a, reverse(b)) ;  divide(a, b) -> multiply(a, inverse(b)) ;  x - y -> add(x, reverse(y))
       e = collapse_known_identities(e)
       # commutative-operator arg sort (lexicographic on the canonicalized sub-expressions):
       #   add, multiply, max, min, or, and, equal, not_equal  →  sort args
       e = sort_commutative_args(e)
       return e
   canonical_settings = {
       "instrumentType": "EQUITY",
       "region": batch_settings.region,
       "universe": batch_settings.universe,
       "delay": batch_settings.delay,
       "decay": batch_settings.decay,
       "truncation": batch_settings.truncation,
       "neutralization": batch_settings.neutralization,
       "pasteurization": batch_settings.pasteurization,
       "unitHandling": batch_settings.unit_handling,
       "nanHandling": batch_settings.nan_handling,
       "language": batch_settings.language,
       "visualization": batch_settings.visualization,
   }
   canonical_expr = canonicalize_expr(hypothesis.expression_sketch)
   canonical_payload = json.dumps({"type": "REGULAR", "settings": canonical_settings, "regular": canonical_expr}, sort_keys=True)
   fingerprint = sha256(canonical_payload)[:16]
   ```
   Keep `decay` / `truncation` / `neutralization` in the fingerprint (parameter sweeps are legitimate exploration), but see step 8's rolling param-sweep quota for the soft cap on re-sweeping the same skeleton.

   `create_multi_simulation` does **not** accept per-child settings in this workflow and must be called with exactly 4 expressions. If S3 did not provide compatible `batch_settings`, derive one from the modal candidate settings and include `{settings_coerced: true, settings_coercion_reason}` in the later `batch.started` payload; if no defensible shared settings exist, abort before budget reservation with `{succeeded: 0, skipped_reason: "settings_incompatible"}`.

3. **Fingerprint dedup** (batch-internal + memory):
   - If two candidates share fingerprint → emit `batch.dedup_hit { batch_id, fingerprint, source: "intra_batch" }`; drop one.
   - If any candidate's fingerprint is in `memory.fingerprints` → `batch.dedup_hit { source: "memory" }`; try swap from `hypothesis.reserved` (if present), else drop.
   - Remaining candidates count < 4 after all reserved/control/ablation fill attempts -> abort batch: return `{succeeded: 0, skipped_reason: "exact4_insufficient"}`.

4. **Forbidden-pattern check**: for each candidate's `canonical_expr`, test against each `memory.forbidden_patterns[].regex` whose `blocked_until > now`.
   - Match → drop candidate; emit `batch.forbidden_checked { fingerprint, matched_regex }`.

5. **Ghost-operator check**: tokenize `canonical_expr`; for each identifier that looks like an operator (matches `[a-z_][a-z0-9_]*` followed by `(`), verify it's in `platform_snapshot.operators`.
   - Any miss → drop candidate; emit `batch.forbidden_checked { fingerprint, ghost_op }` (using same event).

6. **Neutralization validity**: `batch_settings.neutralization` must be in `platform_snapshot.valid_neutralization`.
   - Invalid → abort batch before budget reservation with `{succeeded: 0, skipped_reason: "invalid_neutralization"}`.

7. **Research stack check**:
   - Non-ablation candidates must carry a template/L0 identity — **either**
     `template_ref.skeleton_fingerprint` + `derived_from_template_id`（template-transfer /
     generated_first_principles 路径，2026-07 主通道）**or** `zero_order_provenance.zfield_id`
     （L0 field-slot fallback 路径）。Both missing → drop candidate.
   - `template_ref.skeleton_fingerprint` in `data/templates/blocked_skeletons.txt` → drop（lock 0）。
   - If `bucket(` appears, candidate must include `bucket_axis_hypothesis`.
   - Reject candidates that apply scalar arithmetic directly to VECTOR/event raw fields.
   - Enforce streaming: S4 receives only the next exact-4 candidate set, never a fully materialized library.
   - Reject `expression_level: L2` candidates unless `parent_l1_evidence.parent_basic_strength.passed == true` per `reference/two-field-construction-contract.md`.
   - Reject mainline `ts_ops(ts_backfill(winsorize(single_field)))` candidates unless `ablation_baseline: true`.
   - When `research_snapshot.dataset_selection_mode == high_usage` or the mode is absent in broad mining, reject any non-ablation candidate whose L0/root uses a single high-alphaCount field with only a generic wrapper. Require a differentiated two-field root, or a documented decrowding/cohort axis carried from S2.5/S3 (`crowding_policy`, `decrowding_mechanism`, or `bucket_axis_hypothesis`).
   - Reject any non-ablation candidate missing `research_rationale.return_attribution_prior`, `economic_mechanism`, `statistical_evidence_plan`, or `signal_processing_rationale`.
   - **Anomaly-class reject** (Cluster 5 / G2, 2026-05-09): reject any non-ablation candidate whose `zero_order_provenance.anomaly_class` is missing or equals `"unclassified"`. Emit `batch.anomaly_class_rejected { fingerprint, anomaly_class, reason }`. `unclassified` is legal **only** when `ablation_baseline: true`. Canonical enum lives in `reference/submission-gates.md §11`.
   - Reject any non-ablation candidate missing `zero_order_provenance.two_field_construction_mode`, `zero_order_provenance.l0_economic_role`, or `zero_order_provenance.source_field_count`.
   - If `zero_order_provenance.two_field_construction_mode == "custom_group_axis"`, require `cohort_axis_family != none`, `cohort_axis_field`, and `bucket_axis_hypothesis`.
   - If `zero_order_provenance.two_field_construction_mode == "main_aux_complement"`, require `main_aux_structure.main_signal`, `main_aux_structure.auxiliary_signal`, and `main_aux_structure.auxiliary_role`.
   - If `zero_order_provenance.two_field_construction_mode == "horizon_complement"`, require `horizon_structure.fast_horizon` + `horizon_structure.slow_horizon` OR `horizon_structure.lead_lag_offset`, plus a statistical evidence plan explaining the fast/slow or lead/lag claim.
   - If `zero_order_provenance.two_field_construction_mode == "conditional_regime_gate"`, require `regime_gate_structure.regime_variable`, `regime_state`, `expected_sign_in_state`, and `gate_operator`. If the expression uses `trade_when` or a hard threshold, `research_rationale.trade_when_risk_assessment` is mandatory.
   - If `zero_order_provenance.two_field_construction_mode == "composite_cohort_axis"`, require `composite_cohort_structure.axis_a_field`, `axis_b_field`, `sparse_bucket_guard`, and `bucket_axis_hypothesis` covering both axes.
   - If `zero_order_provenance.two_field_construction_mode == "vector_field_pairing"`, require `vector_pairing_structure.vector_field`, `vec_collapse_op`, and `preserved_facet`. Reject any bare arithmetic on VECTOR fields before a `vec_*` collapse.
   - Reject `trade_when(` / hard-threshold / event-gate candidates unless `research_rationale.trade_when_risk_assessment` explicitly states: source-edge evidence, why the gate is economically causal, expected gate stability, and at least one negative-control/ablation comparison. If only metric improvement is cited, emit `batch.forbidden_checked { reason: "surface_metric_gate" }` and drop it.
> **起草前必读**:`skills/wqb-batch-diversity-cheatsheet.md`(SkillOpt 训练产出的 guard 首过清单,实测 sonnet 首过率 0/8→7/8;含算子→类别白名单、裸算术符号不计类、终检流程)。

   - Run the batch-level expression guard (`scripts/batch_expression_guard.py` semantics) on the exact 4 expressions before budget reservation. Reject/regenerate if all 4 children start with `trade_when`, if more than 2 children start with `trade_when`, if no non-outer-`trade_when` parent/control exists, or if 3+ children reuse the same outer gate condition. This applies even when the user requests an earnings `trade_when` auxiliary; that request does not override source-parent diversity. If session constraints include `no_trade_when: true`, or the user explicitly says not to use `trade_when`, pass `--forbid-trade-when` and reject any child containing `trade_when` anywhere in the expression.
   - Also pass `--require-template-skeleton-diversity --min-template-families 3 --min-template-stage-paths 3 --max-per-template-family 2` to the same guard. Prefer a JSON payload with `hypotheses[]` so the guard reads explicit `template_skeleton_family`, `template_stage_path`, `template_source`, and `skeleton_axis_signature`; if metadata is missing, the guard infers a conservative skeleton family from expression operators. Block on `template_family_collapse` or `template_stage_path_collapse`. This is a hard lock: wrapper/window/sign/field substitutions around the same L0/L1/L2 skeleton do not spend budget.
   - Also pass `--require-anti-crowding --max-crowded-skeleton 1` to the same guard (`reference/diversity-contract.md §0f`). This caps the platform-crowded `group_rank/group_zscore/rank/zscore(ts_*(field))` macro-skeleton at ≤1 of 4 children regardless of cohort axis or final wrapper; the other 3 must be structurally orthogonal escapes (two-leg subtract/add blend, `vector_neut` residual on raw fields, `ts_corr`/`ts_regression` pairwise, `power(x-0.5,3)`/`signed_power` on raw, native `vec_*`). Block on `crowded_skeleton_over_cap`. This is a hard lock and the root-cause fix for the GLB/general `prod_corr ~0.7–0.9` wall: `rank` vs `group_rank` vs `group_zscore` swaps are not diversity and do not spend budget. The guard infers the macro-skeleton from the expression, so legacy/manual payloads that disguise the monoculture with field/window/cohort/wrapper edits are still caught.
   - Also pass `--require-operator-class-diversity --min-operator-classes 5 --min-operator-class-pairs 4 --max-per-operator-class-pair 1 --max-core-class-presence 3 --allowed-common-operator-class vector_collapse --require-explicit-operator-class-exclusion --min-explicit-excluded-operator-classes 3` to the same guard. Prefer full `hypotheses[]` metadata so the guard reads `operator_class_signature`, `primary_operator_class_pair`, `excluded_operator_classes`, `operator_class_role_map`, and `underused_operator_class_target`; if metadata is missing, it infers operator classes from expression operators but cannot satisfy the explicit-exclusion lock. Block on `operator_class_pair_missing`, `operator_class_coverage_low`, `operator_class_pair_collapse`, `operator_class_common_collapse`, `operator_class_metadata_mismatch`, `operator_class_signature_mismatch`, `operator_class_exclusion_missing`, `operator_class_exclusion_rotation_low`, or `operator_class_exclusion_mismatch`. This is a hard lock: any reused primary pair, four children that all use the same pair such as `time_series_level + group_cross_sectional`, all carry the same non-boilerplate class through the core path, repeat the same absence slot, or declare operator-class metadata not proven by the expression, do not spend budget.
   - Run the submitted-family guard before budget reservation: `python scripts/submitted_family_guard.py --region <region> --require-region-cache --ban-recent-field-days 90 --fail-if-blocked --json-file <exact4.json>`. This is mandatory for every S4 batch. If it emits `submitted_region_cache_missing` or `submitted_corpus_empty`, refresh `data/platform/my_submitted_<region>_regular.json` via `get_user_alphas` before retrying; do not silently fall back to treating overlap data as unavailable. If any child is blocked by `recent_submitted_field_reuse`, `recent_submitted_semantic_field_reuse`, `same_raw_field_set`, `same_semantic_field_set`, or `submitted_semantic_pair_reused`, emit `batch.dedup_hit { source: "submitted_family_guard", matched_alpha_id, reason }`, regenerate from reserved/control fields, and do not reserve budget.

8. **Second-order correlation pruning**:
   - Compute `structural_family_key = {zfield_id, expression_level, l1_operator, lookback, sign, bucket_axis, cohort_axis_family, neutralization}`.
   - If two candidates share the same key, keep the simpler expression or the one with stronger attribution evidence.
   - Emit `batch.dedup_hit { source: "structural_family" }` for drops.
   - If a candidate's parent alpha has known `prod_corr >= 0.5` or `self_corr >= 0.5`, wrappers alone are insufficient; require a changed L0 construction or changed bucket axis.
   - Compute near-correlation score against remaining candidates and recent `memory/{region}/structural_features.jsonl`:
     ```python
     score = 0
     score += 0.35 if same_zfield_id else 0
     score += 0.20 if same_raw_field_set else 0
     score += 0.15 if same_l1_operator_and_lookback_bucket else 0
     score += 0.10 if same_sign else 0
     score += 0.10 if same_neutralization else 0
     score += 0.10 if same_bucket_axis_family else 0
     ```
     If `score >= structural_similarity_threshold` (default 0.70), drop the weaker candidate unless it has a different economic bucket axis family with a written `bucket_axis_hypothesis`.
   - For a batch with L2 candidates, enforce `unique(parent_alpha_id, bucket_axis_family)`: no two candidates may be wrapper-only variants of the same parent and bucket axis.
   - **Submitted-alpha overlap check (early self-corr proxy — added 2026-05-11; executable guard added 2026-05-13; 90-day field ban added 2026-05-13)**: you cannot call `check_self_correlation` yet (no `alpha_id` before simulation), so approximate it. For each remaining candidate compute `expression_overlap_score` against (a) every row in `memory/{region}/submittable_seeds.jsonl` and (b) the cached submitted/saved-alpha expressions for this region, using the **same `score` formula above** (heaviest weight on `same_raw_field_set` + `same_zfield_id`; also count `same_l1_operator_and_lookback_bucket`, `same_neutralization`). Then run `scripts/submitted_family_guard.py`, which hard-blocks any raw or canonical semantic field used by a submitted REGULAR alpha in the rolling last 90 days and also blocks near-equivalent field carriers (`source_real_*` vs `source_*`, `real_*` vs base) plus submitted field-pair reuse. If either `expression_overlap_score >= 0.7` or the guard reports a hit → drop the candidate, emit `batch.dedup_hit { batch_id, fingerprint, source: "submitted_family_guard", matched_alpha_id, reason }`, and try to refill from `hypothesis.reserved`. Rationale: a candidate that's structurally a tiny variant of something you already submitted would simulate fine, pass headline metrics, then fail the S5/S8 self-corr gate (`< 0.4`) — killing it here saves the S4 child budget and all downstream repair/robustness budget.
   - **Rolling param-sweep quota (added 2026-05-11)**: maintain `session_state.param_sweep_counts[(skeleton_with_params_blanked, param_family)]` where `skeleton_with_params_blanked` = `canonical_expr` with every `decay` / `truncation` / `ts_*` window literal replaced by `?`. Across a rolling 2-batch window, **at most 2 children** may share the same `(blanked_skeleton, param_family)` — additional sweep variants of an already-twice-swept skeleton are dropped with `batch.dedup_hit { source: "param_sweep_quota", blanked_skeleton }` and the slot is refilled from reserved/controls. Exception: a deliberate `wqb-alpha-repair` `hump_param_sweep` / decay sweep batch may use up to 4 in one batch (it's the explicit sweep), but cannot be re-run on the same parent next batch.

9. **Exact-4 and diversity check** (see `reference/diversity-contract.md` 4-axis rule plus robust-cohort overlay, template-skeleton overlay, and `reference/two-field-construction-contract.md`). Remaining count must equal 4. Require at least 2 task_types, 2 paradigms, 2 shapes, and 2 outer wrappers.
   - If `research_snapshot.robust_cohort_context.required_next_two_batches=true`, require at least one candidate with `cohort_axis_family != none` or a structured `cohort_axis.skipped` event. For robust repair/diagnostic batches with coherent parent evidence, prefer at least two distinct cohort-axis families across the 4 children.
   - When the field inventory permits, require at least 3 unique `two_field_construction_mode` values and at least 3 unique `l0_economic_role` values across the four children; no mode may appear in more than two children.
   - Require at least 3 unique `template_skeleton_family` and at least 3 unique `template_stage_path` values; no skeleton family may occupy more than two children. Do not count wrapper/sign/window/decay/truncation-only changes as new skeletons. The batch expression guard is the executable check and should emit `template_family_counts` / `template_stage_path_counts` into the `batch.diversity_checked` payload.
   - Require 4 unique `primary_operator_class_pair` values and at least 5 unique operator classes across four children; no pair may be reused; no non-boilerplate core class may appear in all four children. `vector_collapse` may be allowed in all four only for VECTOR data. Do not mark `arithmetic_ratio` or `group_cross_sectional` as common boilerplate unless a written dataset-specific reason explains why at least one child cannot exclude it. Every child must explicitly name an absent operator class first, then choose two primary classes from the remaining compatible set; the guard verifies declared absent classes are not used and declared pair classes are actually present in `expression_sketch`.
   - If any candidate carries `parent_l1_evidence.parent_basic_strength.reverse_control_required=true` or `expected_direction=unknown`, require a `companion_field_role=reverse_control` or `l0_economic_role=negative_control` child in the same batch.
   - Fail → return `{succeeded: 0, skipped_reason: "diversity_failure"}`. Emit `batch.diversity_checked { passed: false, count, unique_* }`.
   - Pass → emit `batch.diversity_checked { passed: true, ... }`.

9.5. **10-round strategy-diversity/self-correlation lock**:
   - If 10 production rounds have elapsed since the last `strategy_diversity.checked`, S4 must run `python scripts/session_gate.py strategy-diversity --session-id <sid> --region <region> --universe <universe> --delay <delay> --append-record --fail-if-blocked` before budget reservation.
   - If the latest `strategy_diversity.checked.decision == "BLOCK"`, abort the batch before budget reservation with `{succeeded: 0, skipped_reason: "strategy_diversity_block"}` unless every child avoids the blocked `top_strategy_families` / `top_field_sets` or changes at least two documented structural axes versus the blocked family.
   - Real diversification axes are: dataset/category, semantic field set, `two_field_construction_mode`, `l0_economic_role`, operator family, neutralization/cohort axis. Outer wrapper, sign, lookback, decay, truncation, and `rank`/`group_rank` swaps alone are not sufficient.
   - Emit `batch.diversity_checked { passed: false, reason: "strategy_diversity_block", strategy_diversity_event_ref: ... }` when blocked. Do not reserve budget and do not call `create_multi_simulation`.

No 2-child or 3-child payload override is allowed. If only 2 or 3 strong
candidates remain, fill to 4 with non-duplicate controls, ablations, or nearby
variants that preserve research value; otherwise defer the batch.

10. **Budget check** (unit = 1 per child sim in the multi payload):
   ```python
   needed = 4
   if len(remaining_candidates) != 4:
       emit batch.budget_checked { passed: false, needed: 4, available, reason: "exact4_required" }
       return { succeeded: 0, skipped_reason: "exact4_insufficient" }
   if session_state.budget_remaining < needed:
       emit batch.budget_checked { passed: false, needed, available }
       return { succeeded: 0, skipped_reason: "budget_insufficient" }
   emit batch.budget_checked { passed: true, needed, available, after: available - needed }
   session_state.budget_remaining -= needed
   ```
   Pre-subtract: budget is reserved even if a child fails (platform charges on dispatch).

10.5. **Parent basic-strength lock #7** (Cluster 2 / Iron Law §16b, 2026-05-09): for every L2 candidate (`expression_level == "L2"` AND `parent_l1_evidence.parent_alpha_id != null`), confirm the same session emitted `parent.basic_strength.checked { parent_alpha_id, passed: true }` (recorded directly in `records/<today>.jsonl`) OR the candidate carries `parent_l1_evidence.parent_basic_strength.passed: true` with full evidence metrics (sharpe / fitness / 2y_sharpe / failed_ra_count / source-attribution layer).
   - Failure → emit `batch.parent_strength_lock_failed { batch_id, parent_alpha_id, candidate_fingerprint, reason: "missing_basic_strength_event" | "passed_false" | "evidence_incomplete" }` and abort the entire batch (do not partial-dispatch). Return `{succeeded: 0, skipped_reason: "parent_basic_strength_failed"}`.
   - Rationale: Iron Law §16b — wrapper iteration on weak parents wastes budget on non-validated lineage. Repair / wrapper layers are forbidden until parent passes basic strength.

10.6. **Operator-frontier soft lock #8** (Cluster 4 / RC4, 2026-05-09): read the latest `operator.coverage_check` event for this batch from `records/<today>.jsonl`. If `frontier_unused_count >= 18` (over the rolling 50-batch window) AND `frontier_used_in_this_batch == 0`:
   - Emit `batch.exploration_debt { batch_id, frontier_debt: true, frontier_unused_count, frontier_used_in_this_batch }`.
   - Soft-fail: return `{succeeded: 0, skipped_reason: "frontier_debt_unrepaid"}` to S3 with directive `regenerate_with_frontier_op=true`. S3 retries up to 2 times before emitting `exploration_debt.unrepayable { reason }` and dispatching anyway (do not block budget on a 3rd attempt — exploration debt becomes informational only).
   - Frontier-20 catalog lives in `reference/operators-catalog.md §Frontier-20`. Cold start (no operator_usage.jsonl history) treats `frontier_used_in_this_batch >= 1` as satisfied.

11. **Track lock (added 2026-05-08, 6th pre-flight lock)**: verify upstream `wqb-hypothesis-designer` emitted `track.allocated { batch_id, bfs_slots, dfs_slots, fallback_to_bfs }` for this `batch_id` AND every candidate carries a `track` field in `{"BFS", "DFS"}`.
   - **Cold session exemption**: when `session_state.is_cold_session == true`, allow `track.allocated.fallback_to_bfs == true` and `track == "BFS"` for all 4 candidates.
   - **Warm session enforcement**: when `is_cold_session == false`, require both (a) a matching `track.allocated` event AND (b) BFS/DFS counts that satisfy `reference/track-allocation.md` (default `bfs_slots == 2 AND dfs_slots == 2`). `track == "unspecified"` is rejected.
   - Failure → abort dispatch before budget reservation: emit `batch.track_lock_failed { batch_id, reason: "missing_track_allocated" | "unspecified_track" | "parity_violation", expected, observed }` and return `{succeeded: 0, skipped_reason: "track_lock_failed"}`.

12. Emit `batch.started { batch_id, count: len(remaining_candidates), fingerprints: [...], l0_pack_slots: [...], l2_parent_count: <int> }`. If `dataset_selection_mode=high_usage`, also include `crowding_policy="decrowd_by_two_field_l0_and_corr_gate"` and `prod_corr_hard_gate=0.7`.

### Phase B — Multi-sim dispatch (single MCP call)

13. Build the `alpha_expressions` list (one expression per remaining candidate, in stable order), then call `create_multi_simulation` with that list plus the shared settings:

    ```python
    alpha_expressions = [c.expression_sketch for c in remaining_candidates]
    for c in remaining_candidates:
        emit sim.dispatched { candidate_id: c.hypothesis_id, fingerprint: c.fingerprint, settings: batch_settings }
    try:
        response = await create_multi_simulation(
            alpha_expressions=alpha_expressions,
            instrument_type=batch_settings.instrument_type,
            region=batch_settings.region,
            universe=batch_settings.universe,
            delay=batch_settings.delay,
            decay=batch_settings.decay,
            neutralization=batch_settings.neutralization,
            truncation=batch_settings.truncation,
            pasteurization=batch_settings.pasteurization,
            unit_handling=batch_settings.unit_handling,
            nan_handling=batch_settings.nan_handling,
            language=batch_settings.language,
            visualization=batch_settings.visualization,
        )
    except Exception as e:
        err = str(e)
        # The BRAIN wrapper can time out while waiting for multi-sim children
        # ("Children did not appear within ..."). That is an unresolved
        # platform polling state, not proof that the server did not create or
        # finish the child simulations. Do not count it as batch.all_failed
        # until recovery has searched user alphas by timestamp/expression.
        if "Children did not appear" in err:
            for c in remaining_candidates:
                emit sim.unresolved {
                  candidate_id: c.hypothesis_id,
                  fingerprint: c.fingerprint,
                  expression: c.expression_sketch,
                  recovery_key: {batch_id, fingerprint: c.fingerprint, expression: c.expression_sketch},
                  error_code: "children_not_visible",
                  error_msg: err
                }
            emit error.mcp { batch_id, error_code: "children_not_visible", recoverable: true, error: err }
            return {
              "succeeded": 0,
              "failed": 0,
              "timed_out": 0,
              "unresolved": len(remaining_candidates),
              "skipped_reason": "multi_children_unresolved",
              "recovery_required": true
            }
        for c in remaining_candidates:
            emit error.mcp { candidate_id: c.hypothesis_id, error: err }
        return { "succeeded": 0, "failed": len(remaining_candidates), "skipped_reason": "multi_dispatch_error" }
    multi_sim_id = response.multi_sim_id or response.id
    child_results = response.results or response.children or response.alphas
    for c, child in zip(remaining_candidates, child_results):
        emit sim.dispatched_done { candidate_id: c.hypothesis_id, sim_id: child.sim_id, multi_sim_id }
    ```

14. **Resolve per-child outcomes** from the returned multi-sim result. Some clients expose explicit `sim_id` and `status`; others return final alpha records after the MCP wrapper has already polled. Preserve stable input order when aligning children to candidates.

    ```python
    results = []
    for c, child in zip(remaining_candidates, child_results):
        st = child.status
        sid = child.sim_id
        if st in ("TIMEOUT", "timeout"):
            emit sim.timeout { sim_id: sid, candidate_id: c.hypothesis_id }
            results.append({"status": "timeout"})
            continue
        if st in ("FAILED", "failed", "ERROR"):
            err = child.error or await lookINTO_SimError_message(locations=[sid])
            emit sim.failed { sim_id: sid, candidate_id: c.hypothesis_id, error_code: err.code, error_msg: err.message }
            results.append({"status": "failed", "error": err}); continue
        alpha_id = child.alpha_id
        a = child if child.metrics else await get_alpha_details(alpha_id)   # slim-alpha shape (see reference/mcp-output-shapes.md)
        metrics = {
            "sharpe": a.metrics.sharpe,
            "fitness": a.metrics.fitness,
            "margin": a.metrics.margin,
            "turnover": a.metrics.turnover,
            "returns": a.metrics.returns,
            "drawdown": a.metrics.drawdown,
            "robust_universe_sharpe": a.metrics.get("robust_universe_sharpe"),
            "sub_universe_sharpe": a.metrics.get("sub_universe_sharpe"),
            "two_year_sharpe": a.metrics.get("two_year_sharpe"),
            "risk_neutralized_sharpe": a.metrics.get("risk_neutralized_sharpe"),
            "investability_sharpe": a.metrics.get("investability_sharpe"),
        }
        checks = a.checks   # {fail:[{name,value?,limit?,…}], warning:[…], pass:[name,…], pending:[name,…]}
        emit sim.succeeded {
            sim_id: sid, candidate_id: c.hypothesis_id, alpha_id,
            metrics, checks_fail_count: len(checks.fail), checks_warning_count: len(checks.warning),
            pyramid_effective: a.pyramids.effective
        }
        results.append({
            "status": "ok",
            "alpha_id": alpha_id,
            "metrics": metrics,
            "checks": checks,                 # was `is_checks` (flat array); now {fail,warning,pass,pending}
            "pyramids": a.pyramids,
        })
    ```

### Phase C — Aggregate & hand-off

15. Count `succeeded = sum(r["status"] == "ok" for r in results)`, `failed = count_failed + count_dispatch_error`, `timed_out = count_timeout`, `unresolved = count_unresolved`.
16. If `succeeded == 0` → emit `batch.all_failed { batch_id, reasons: [top 3 error_codes] }`; outer loop increments `consecutive_empty`.
17. If `0 < succeeded < len(remaining_candidates)` → emit `batch.partial { batch_id, succeeded, failed, timed_out }`.
18. Build `hypotheses_with_metrics`:
    ```python
    hypotheses_with_metrics = [
      { **c.hypothesis_dict, **{
          "alpha_id": r["alpha_id"],
          "is_metrics": r["metrics"],            # incl robust_universe_sharpe / sub_universe_sharpe / two_year_sharpe / risk_neutralized_sharpe / investability_sharpe
          "checks": r["checks"],                 # {fail:[…], warning:[…], pass:[name,…], pending:[name,…]}
          "pyramids": r["pyramids"],             # {effective, list:[{name,multiplier}]}
      }}
      for c, r in zip(remaining_candidates, results) if r["status"] == "ok"
    ]
    ```
19. Return the full output YAML (§3) to caller (`/auto-mine` outer loop → `wqb-quality-gate`).

Unresolved override: if any child is in `sim.unresolved` / `batch.unresolved`, ignore the older all-failed rule above. The outer loop must recover or explicitly mark the children as unrecoverable before it increments `consecutive_empty`, `all_failed_count`, or `mcp_errors`.

## 6. Events emitted (exhaustive)

`batch.started`, `batch.dedup_hit` (×N), `batch.forbidden_checked` (×N), `batch.diversity_checked` (including template skeleton counts), `batch.budget_checked`, `sim.dispatched` (×N), `sim.dispatched_done` (×N), `sim.poll` (optional if the client exposes polling), `sim.succeeded` (×N_succ), `sim.failed` (×N_fail), `sim.timeout` (×N_to), `gate.tier` (×N_succ, even when a compact `batch.results` summary is also emitted), `batch.partial` (if partial), `batch.all_failed` (if 0 succ), `error.mcp` (on exception).

Unresolved children emit `sim.unresolved` and the batch emits `batch.unresolved`; they are not `sim.failed`, not `sim.timeout`, and not eligible for `batch.all_failed` until recovery resolves them.

Trace-diagnostic requirement: do not rely only on `batch.results`. For every successful child, emit a normalized `gate.tier` payload carrying `alpha_id`, `batch_id`, `candidate_id`, `tier`, `failure_category`, `metrics`, `fields`, `task_type`, `paradigm`, `expression`, `correlation_checked`, and `user_submit_qualified`. This lets `scripts/diagnostic/analyze_session.py` attribute failures by field/source/paradigm without reverse-engineering compact records. If using a client that cannot emit per-child events during the run, write equivalent synthetic `gate.tier` events immediately after the batch result is known.

### Trace events emitted (Trace 2.0 schema — see reference/trace-schema-v2.md)

The `candidate` dict carried through dispatch and into `hypotheses_with_metrics` MUST include `track` (`"BFS"` | `"DFS"` | `"unspecified"`) inherited from the upstream `wqb-hypothesis-designer` output. It should also pass through `exploration_exploitation` and `operator_usage_plan` when present so diagnostics can score 50/50 balance, operator coverage, and parameter-depth evidence. This propagates to `wqb-quality-gate` so `gate.tier` events can mirror `track` for objective attribution. Phase 1-3: pass through as `"unspecified"`. Phase 4: real value.

## 7. Constraints (hard rules)

1. **Always dispatch via exact-4 `create_multi_simulation`** (one call per batch with exactly 4 child expressions). **Never call single-sim `create_simulation`** in this skill — concurrency is the platform's job, not the client's.
2. **Never call `submit_alpha`** or `set_alpha_properties`. That's S8 (inline in workflow, guarded by 4-lock).
3. **Never call `check_correlation`**. That's S5.
4. **Never mutate `memory/`** directly. `wqb-memory-writer` is the sole writer.
5. **Exactly one `create_multi_simulation` call per batch.** No client-side fan-out, no semaphore, no single-sim fallback.
6. Budget is pre-subtracted in Phase A §8, NOT per-child in Phase B. A failed child is still billed.
7. Timeout per child sim = 15 minutes from dispatch when the client exposes child polling; otherwise rely on the MCP wrapper's multi-sim wait behavior and record returned timeouts.

## 8. Self-validation checklist (for AI client before returning)

- [ ] `records/<date>.jsonl` contains `track.allocated { batch_id, bfs_slots, dfs_slots }` BEFORE `batch.started` for this batch (or `batch.track_lock_failed` if pre-flight aborted)
- [ ] Every dispatched candidate carries `track ∈ {"BFS", "DFS"}` (warm session) or `track == "BFS"` with `fallback_to_bfs: true` (cold session)
- [ ] `records/<date>.jsonl` contains `batch.started` + `batch.budget_checked { passed: true }` before any `sim.dispatched`
- [ ] `records/<date>.jsonl` contains a `sim.dispatched` + (`sim.succeeded` | `sim.failed` | `sim.timeout`) pair for each candidate
- [ ] Returned `budget_consumed` equals number of `sim.dispatched` events in this batch
- [ ] Exactly one `create_multi_simulation` MCP call per dispatched batch; zero `create_simulation` calls (grep records)
- [ ] `hypotheses_with_metrics` length == number of `sim.succeeded` events

## 9. Example (earnings2 batch from playbook T1 / T3 / T5 / T9)

```yaml
# Input: 4 hypotheses from wqb-hypothesis-designer
hypotheses:
  - {hypothesis_id: h1, task_type: shock, paradigm: P3,
     expression_sketch: "trade_when(days_from_last_change(ern2_earnconfcall_d1_calendar_next) <= 3, -ts_zscore(returns, 20), -1)",
     suggested_params: {decay: 8, truncation: 0.08, neutralization: INDUSTRY}}
  - {hypothesis_id: h2, task_type: persistence, paradigm: P7,
     expression_sketch: "rank(days_from_last_change(ern2_earnconfcall_d1_calendar_next)) - rank(days_from_last_change(ern2_earnconfcall_d1_calendar_prev))",
     suggested_params: {decay: 12, truncation: 0.08, neutralization: INDUSTRY}}
  - {hypothesis_id: h3, task_type: shock, paradigm: P3,
     expression_sketch: "trade_when(days_from_last_change(ern2_earnrelease_d1_calendar_next) <= 5, -group_rank(ts_mean(returns, 5), industry) * (volume > adv20), -1)",
     suggested_params: {decay: 4, truncation: 0.08, neutralization: INDUSTRY}}
  - {hypothesis_id: h4, task_type: persistence, paradigm: P4,
     expression_sketch: "ts_regression(days_from_last_change(ern2_earnconfcall_d1_calendar_prev), ts_step(1), 252, rettype=2)",
     suggested_params: {decay: 15, truncation: 0.08, neutralization: INDUSTRY}}
batch_settings:
  instrument_type: EQUITY
  region: USA
  universe: TOP3000
  delay: 1
  decay: 8
  truncation: 0.08
  neutralization: INDUSTRY
  pasteurization: ON
  unit_handling: VERIFY
  nan_handling: OFF
  language: FASTEXPR
  visualization: false
  reason: "shared setting for this multi-sim; individual suggested_params are advisory"

# Expected:
# - Phase A: all 4 pass; batch.budget_checked { needed: 4, available: 60, after: 56 }
# - Phase B: 4 expressions sent in one create_multi_simulation call with shared settings; typically 10-15 min wall clock
# - Phase C: return hypotheses_with_metrics with 4 items (if all succeed), 3 items if 1 failed, etc.
```
