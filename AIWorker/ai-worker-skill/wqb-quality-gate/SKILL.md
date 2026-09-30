---
name: wqb-quality-gate
description: "Classify each simulated alpha into one of 4 tiers: - SUBMITTABLE_CONFIRMED — reserved for robustness-audit output (not set here) - SUBMITTABLE_PENDING — meets all gate criteria; hand to wqb-robustness-audit - PROMISING — partial pass; hand to wqb-alpha-repair - REJECT — clear fail Part of the WorldQuant BRAIN auto-mining workflow (S5 of workflow/auto-mining.md)."
---

# Skill: wqb-quality-gate

**Consumers**: Claude Code · GitHub Copilot · Codex · generic assistants
**Stage**: S5 of `workflow/auto-mining.md`
**Budget cost**: 0 (may call `check_self_correlation` then `check_correlation`, both metadata-only)

> **MCP output shapes** — tool responses are slimmed (`reference/mcp-output-shapes.md`). **Failed RA / Failed PPA are precomputed server-side**: read `a.ra.failed_ra_count` (gate `== 0`) / `a.ra.ra_failed` / `a.ra.ra_failed_checks` (and `a.ra.failed_ppa_count` / `a.ra.ppa_failed`) — do **not** re-bucket `checks` yourself. `is.<metric>` → `metrics.<metric>` (incl `metrics.robust_universe_sharpe`, `metrics.sub_universe_sharpe`, `metrics.two_year_sharpe`). `check_correlation` → `…checks.production.max_correlation` / `…checks.self.max_correlation`; `check_self_correlation` → `…max_correlation`. **`get_alpha_pnl` is downsampled and no longer returns the alpha vector** → the Phase B.2 IC pre-filter is unavailable (see below).

## 1. Purpose

Classify each simulated alpha into one of 4 tiers:
- `SUBMITTABLE_CONFIRMED` — reserved for robustness-audit output (not set here)
- `SUBMITTABLE_PENDING` — meets all gate criteria; hand to `wqb-robustness-audit`
- `PROMISING` — partial pass; hand to `wqb-alpha-repair`
- `REJECT` — clear fail

Also infers `failure_category` (one of 11 in `reference/failure-taxonomy.md`) for non-CONFIRMED alphas.

## 2. Inputs

```yaml
batch_result: <output of wqb-batch-runner>  # hypotheses_with_metrics
region: "USA"   # one of USA/IND/...; gates and corr thresholds may differ per region
user_targets:
  sharpe_min: 1.58
  fitness_min: 1.0
  two_year_sharpe_min: 1.6
  margin_min_bp: 10
  turnover_min: 0.01
  turnover_max: 0.70
  self_corr_max: 0.4        # EFFECTIVE self-corr gate — tighter than the 0.7 platform floor; kills near-self-dups at S5 before S6/S6.5/S7 budget (reference/submission-gates.md §6, §8)
  prod_corr_max: 0.7        # user hard qualification gate; missing prod_corr is not submit-qualified
platform_floor:
  sharpe_min: 1.25
  fitness_min: 1.0
  margin_min_bp: 5
  self_corr_max: 0.7  # platform/submission floor only; the effective gate is user_targets.self_corr_max (0.4)
  prod_corr_max: 0.5  # stricter than platform (community consensus)
dataset_context:
  dataset_id: "news12"
  category: "News"
  source_proof_mode: false
  dataset_selection_mode: high_usage | low_usage | fixed_dataset
```

## 3. Outputs

```yaml
tiers:
  - alpha_id: A1bCdEf
    tier: SUBMITTABLE_PENDING | PROMISING | REJECT
    failure_category: <category_id or null>
    metrics: <copied from batch>
    self_corr: float | null       # from check_self_correlation
    prod_corr: float | null       # from check_correlation, only after self-corr passes
    fingerprint: str              # for memory write
```

## 4. MCP tools used

Strict order is mandatory: call `check_self_correlation(alpha_id)` first, and call `check_correlation(alpha_id)` only after the self-correlation result has returned and passed.

Legacy shorthand: `check_correlation(alpha_id)` is a production-correlation call and is legal only after `check_self_correlation(alpha_id)` has passed.

## 5. Steps

### Phase A — Fatal check (Failed RA)

For each alpha in `batch_result.hypotheses_with_metrics`:
1. Read `failed_checks_count = a.ra.failed_ra_count` (and `a.ra.ra_failed_checks` for the names) — the MCP precomputes the WebDataScope Failed RA rule, single source of truth `reference/submission-gates.md` §9 (`RA_CHECK_NAMES` ported from `WebDataScope-0.10.20/src/scripts/background.js` `getAlphaCheckStates`). The rule it applies: count `is.checks[]` entries whose `name` is in `RA_CHECK_NAMES` and whose `result` is neither `PASS` nor `PENDING` (so a `WARNING` on an in-list name — `LOW_GLB_AMER_SHARPE`, `LOW_SUB_UNIVERSE_SHARPE`, `LOW_2Y_SHARPE`, `IS_LADDER_SHARPE`, `CONCENTRATED_WEIGHT`, … — is counted; a `WARNING` on `MATCHES_THEMES` etc. is not). Any names that landed in `checks.warning` but are *not* in `a.ra.ra_failed_checks` go to `warning_diagnostic`. (If you ever need to recompute manually: `#{c in checks.fail if c.name in RA_CHECK_NAMES} + #{c in checks.warning if c.name in RA_CHECK_NAMES}`.)
2. If `failed_checks > 0` →tier = REJECT, failure_category = by-check-name:
   - `LOW_SHARPE` →`low_sharpe`
   - `LOW_FITNESS` →`low_fitness`
   - `LOW_MARGIN` →`low_margin`
   - `CONCENTRATED_WEIGHT` | `WEIGHT` →`concentrated_weight`
   - `LOW_SUB_UNIVERSE_SHARPE` →`sub_universe_fail`
   - `HT_LIQUID_TOP200_SHARPE` →`sub_universe_fail`
   - `HIGH_TURNOVER` →`high_turnover`
   - else →`other_failed_ra`
3. Emit `gate.decided { alpha_id, decision: "REJECT", failed_checks: [...] }`

### Phase B — Threshold gate (for non-REJECT)

For each non-REJECT alpha:
4. Evaluate against `user_targets`:
   - `sharpe >= 1.58` AND `fitness >= 1.0` AND `two_year_sharpe >= 1.6` AND `margin * 10000 >= 10` AND `0.01 < turnover < 0.70`
   - →CANDIDATE for SUBMITTABLE_PENDING
   - Otherwise →PROMISING if `sharpe >= 1.25 AND fitness >= 1.0` else REJECT
5. If REJECT, infer failure_category by which threshold failed:
   - `sharpe < 1.25` →`low_sharpe`
   - `fitness < 1.0` →`low_fitness`
   - `two_year_sharpe < user_targets.two_year_sharpe_min` →`unstable_yearly`
   - `margin < 5bp` →`low_margin`
   - `turnover > 0.70` →`high_turnover`
   - `turnover < 0.01` →`low_turnover`

### Phase B.2 — IC pre-filter (Cluster 5 / G5, 2026-05-09)

**Status (2026-05-12): currently disabled by the slimmed MCP.** The IC pre-filter needed the per-stock alpha vector + the full daily PnL series; the slimmed `get_alpha_pnl` no longer returns the alpha vector and downsamples PnL to ≤~160 points, so the Spearman IC can't be computed as designed. Until `get_alpha_pnl` is exempted from slimming in `world-quant-brain-mcp/main.py` (raise `_slim_pnl`'s `max_rows` and re-expose the vector), record `ic_filter_skipped: true, skip_reason: "pnl_slimmed"` on the gate payload and pass through to Phase C without IC enforcement. Original design kept below for reference / for if/when the data is re-exposed:

> After Phase B headline thresholds pass (CANDIDATE or PROMISING) and **before** Phase C correlation calls, run IC pre-filter using `get_alpha_pnl(alpha_id)` (0 budget):
> ```python
> pnl_series = get_alpha_pnl(alpha_id).pnl                    # full daily PnL series
> alpha_vector = get_alpha_pnl(alpha_id).alpha or get_alpha_details(alpha_id).is.alpha_vector
> ic_daily = [spearman_rho(alpha_vector_aligned[i], pnl_series[i+1]) for i in range(len(pnl_series)-1)]
> ic = mean(ic_daily); ic_volatility_monthly = stddev(monthly_resample(ic_daily))
> ```
> Thresholds (canonical in `reference/submission-gates.md §12`): `|ic| > 0.01` AND `ic_volatility_monthly < 0.30` → PASS; `|ic| <= 0.01` → REJECT `low_ic_signal`; `ic_volatility_monthly >= 0.30` → REJECT `unstable_ic`. Emit `gate.ic_filter { alpha_id, ic, ic_volatility_monthly, passed, failure_category }`. Insufficient history (< 252 trading days) → `ic_filter_skipped: true, skip_reason: "insufficient_pnl_history"`, pass through.

### Phase B.1 - News source-proof annotation

For category `News` in source-proof mode, do not route weak reaction/context
parents to repair just because one diagnostic looks positive. Add
`source_layer_status` to the gate payload:

```yaml
source_layer_status:
  mode: news_source_proof
  passed: bool
  reason: null | news_source_layer_weak
```

`passed` requires Sharpe >= 1.25, Fitness >= 0.70, sub-universe PASS, and no
failed RA checks. If it fails, keep the normal tier result, but downstream S6.5
and S7 must not treat it as repair-eligible. This is compatible with the 11
failure categories because the normal `failure_category` remains unchanged.

### Phase C — Correlation check (for non-REJECT only)

6. For each CANDIDATE or PROMISING:
   - If a user-buffer headline gate is active and any of Sharpe/Fitness/2Y/Margin/Turnover failed, do **not** call `check_self_correlation` or `check_correlation`; emit `self_corr=null`, `prod_corr=null`, `prod_corr_required=true`, and `reason="failed_user_headline_gate_before_correlation"`.
   - Otherwise call `check_self_correlation(alpha_id)` first; parse the authoritative platform self-correlation value when available. **Effective self-corr threshold = `user_targets.self_corr_max` when provided (for this user, `0.4`), otherwise `platform_floor.self_corr_max` (0.7).** Self-corr and prod-corr are SEPARATE gates with SEPARATE thresholds; never reuse the prod threshold for self or vice versa.
   - If self-correlation is missing/pending/inconsistent or `self_corr >= effective_self_corr_max` (i.e. `>= 0.4`), demote to REJECT with `failure_category = high_self_corr`, emit `self_correlation.checked { ..., self_corr_max: <effective>, passed: false }`, and do **not** call `check_correlation`. This is intentionally early: it stops the alpha before S6 sub-universe sims / S6.5 ablation sims / S7 repair sims, all of which cost budget.
   - Only after self-correlation passes, call `check_correlation(alpha_id)`; parse production correlation from its production result.
   - Effective production threshold is `user_targets.prod_corr_max` when provided (for this user, 0.7), otherwise `platform_floor.prod_corr_max`.
   - Missing production correlation means not submit-qualified: demote CANDIDATE to PROMISING/REJECT with `failure_category = high_prod_corr` and `correlation_status = prod_corr_pending`; do not route to robustness/property.
   - If `prod_corr >= effective_prod_corr_max` →demote to REJECT with `failure_category = high_prod_corr`.
   - Redundant guard: any later evidence that `self_corr >= effective_self_corr_max` invalidates the production-correlation result and demotes to REJECT with `failure_category = high_self_corr`.
   - In `dataset_context.dataset_selection_mode == high_usage` or when broad mining omitted an explicit mode, always attach `crowding_policy="decrowd_by_two_field_l0_and_corr_gate"`; high usage is allowed, but production correlation is a hard qualification gate.
7. Emit `self_correlation.checked { alpha_id, self_corr, self_corr_max, passed }` before any production-correlation event.
8. Emit `correlation.checked { alpha_id, prod_corr, effective_prod_corr_max, prod_corr_required, prerequisite_self_corr_passed: true }` only after `self_correlation.checked.passed == true`.

### Phase D — Final tier assignment

9. For each alpha:
   - All phases passed AND originally CANDIDATE →`SUBMITTABLE_PENDING`
   - Originally CANDIDATE but demoted by Phase C →REJECT
   - Originally PROMISING (passes platform floor) →PROMISING
   - Else →REJECT
10. Emit `gate.tier { alpha_id, tier, failure_category, fingerprint, metrics }` per alpha. Include `applied_threshold_profile` (Cluster 1 / dataset_tier): `produce_lit` (default 1.58/1.0/10bp) | `explore_unlit` (PROMISING-only at 1.30) | `bridge_edge_lit` (user thresholds with `auto_submit_eligible=false`).

### Phase E — Family-wise inflation aggregator (Cluster 5 / G1, 2026-05-09)

Phase E runs **once per session** at S5 final, after every batch of the same `(session_id, dataset_id)` campaign has been quality-gated. The trigger condition: the campaign accumulated >= 4 candidates with `tier == SUBMITTABLE_PENDING`.

```python
pending = [c for c in session_results
           if c.tier == "SUBMITTABLE_PENDING" and c.dataset_id == campaign_dataset_id]
if len(pending) < 4:
    return  # not enough candidates for FDR — skip aggregator

# Approximate t-statistic from Sharpe and its standard error:
def t_stat(c):
    se = c.metrics.get("sharpe_se") or (c.metrics["sharpe"] / sqrt(c.metrics["is_days"]))
    return c.metrics["sharpe"] / max(se, 1e-9)

# Two-tailed p-value from t-stat under N(0,1) approx:
p_values = [2 * (1 - normal_cdf(abs(t_stat(c)))) for c in pending]

# Benjamini-Hochberg FDR:
sorted_pairs = sorted(zip(p_values, pending), key=lambda x: x[0])
m = len(sorted_pairs)
q_threshold = 0.05
demoted = []
for k, (p, candidate) in enumerate(sorted_pairs, start=1):
    bh_critical = (k / m) * q_threshold
    if p > bh_critical:
        demoted.append(candidate)
```

Each demoted candidate has its tier rewritten from `SUBMITTABLE_PENDING` to `PROMISING` and `failure_category = family_wise_inflation`. Emit:

```json
{"kind":"gate.fdr_adjusted","payload":{
  "session_id":"<sid>",
  "dataset_id":"<id>",
  "candidates_tested":<int>,
  "fdr_q_threshold":0.05,
  "method":"benjamini_hochberg",
  "demoted_alpha_ids":["..."],
  "kept_alpha_ids":["..."]
}}
```

Then for each demoted alpha emit a fresh `gate.tier` with the new tier so downstream stages (S6 robustness routing, post-S9 memory aggregator) see the corrected truth.

Phase E is mandatory only when the trigger condition is met. Sessions with <4 PENDING candidates skip the aggregator silently (no event); the family-wise inflation risk doesn't bind under that sample size.

## 6. Events emitted

Required order: `gate.decided` -> `self_correlation.checked` -> `correlation.checked` -> `gate.tier`. The `correlation.checked` event is legal only when the immediately preceding self-correlation event passed.

`gate.decided` (xN), `self_correlation.checked` (eligible), `correlation.checked` (self-pass only), `gate.tier` (xN)

### Trace events emitted (Trace 2.0 schema — see reference/trace-schema-v2.md)

Each `gate.tier` payload MUST carry `track` (`"BFS"` | `"DFS"` | `"unspecified"`), copied from the originating hypothesis. When available, also mirror `exploration_exploitation` and `operator_usage_plan` so `wqb-self-diagnostic` can score 50/50 balance, operator usage, and parameter-depth evidence. This lets diagnostics attribute outcomes back to both legacy BFS-vs-DFS allocation and the newer exploration/exploitation policy. In Phase 1-3 the value is `"unspecified"` (controller not yet wired); Phase 4 fills with the real value carried by `wqb-batch-runner` candidate dict.

```json
{
  "alpha_id": "...", "tier": "REJECT", "failure_category": "low_sharpe",
  "fingerprint": "...", "metrics": {...},
  "task_type": "shock", "paradigm": "P3", "fields": [...], "expression": "...",
  "track": "unspecified",
  "exploration_exploitation": {"track_role": "exploration"},
  "operator_usage_plan": {"operators_used": ["rank", "ts_zscore"], "parameter_values_used": {}}
}
```

Schema: `reference/trace-schema-v2.md §4.3`.

When `dataset_context.source_proof_mode == true`, `gate.tier` MUST also carry
`source_layer_status` so S7 can distinguish a repairable parent from a weak News
context reaction.

## 7. Constraints

- Do NOT call `submit_alpha`, `set_alpha_properties`, or `get_alpha_yearly_stats`. Those are S6/S8.
- `get_alpha_pnl` is allowed **only** in Phase B.2 (IC pre-filter). It is 0-budget and gated behind Phase A+B headline pass to avoid wasting calls on REJECT candidates.
- `failure_category` must be one of the 11 in `reference/failure-taxonomy.md`. Use `unknown_failure` as last resort and emit `error.unknown_check`.
- Effective correlation gates for this user: **`self_corr < 0.40`** (`user_targets.self_corr_max` — tighter than the community-mode 0.5 and the 0.7 platform floor; the rationale is efficiency — kill near-self-dups at S5 before S6/S6.5/S7 spend budget; see `reference/submission-gates.md §6/§8`) and **`prod_corr < 0.70`** (`user_targets.prod_corr_max` — looser than the community-mode 0.5). Self-corr and prod-corr are separate gates; never swap their thresholds.
- Production correlation missing or above the effective threshold blocks robustness/property in both low-usage and high-usage modes.
- Production correlation must never be queried unless the same gate pass already has a passing `self_correlation.checked` event for that alpha.
- **Robustness routing lock (added 2026-05-08)**: whenever this batch produced at least one `gate.tier { tier: "SUBMITTABLE_PENDING" }`, the downstream S6 step MUST emit `robustness.audited` (with decision in `{PASS, CONDITIONAL_PASS_MANUAL_ONLY, FAIL}`) for **each** such alpha. The `robustness.skipped` event is then forbidden at the batch level — including reasons like `"no child passed headline gate"`, which contradict the existence of a PENDING child. Skipping is allowed only when the batch has zero PENDING and zero PROMISING tiers. Violators must instead emit `robustness.audited { decision: "FAIL", reason: <specific_reason> }` per pending alpha.

## 8. Self-validation

- [ ] For each alpha in input, exactly 1 `gate.tier` event written
- [ ] All eligible non-REJECT alphas have a `self_correlation.checked` event before any `correlation.checked` event
- [ ] No alpha has `correlation.checked` unless `self_correlation.checked.passed == true`
- [ ] No alpha has `tier = SUBMITTABLE_CONFIRMED` (only robustness-audit sets that)
- [ ] `failure_category` present on every non-CONFIRMED tier
- [ ] If any `gate.tier.tier == "SUBMITTABLE_PENDING"` was emitted, downstream MUST NOT emit `robustness.skipped` for this batch (constraint §7 robustness routing lock)
