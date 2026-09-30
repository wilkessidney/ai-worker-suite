---
name: wqb-robustness-audit
description: "Upgrade SUBMITTABLE_PENDING to SUBMITTABLE_CONFIRMED by verifying temporal stability and sub-universe survival. Downgrade to PROMISING only on hard fail. Part of the WorldQuant BRAIN auto-mining workflow (S6 of workflow/auto-mining.md)."
---

# Skill: wqb-robustness-audit

**Consumers**: Claude Code, GitHub Copilot, Codex, generic assistants
**Stage**: S6 of `workflow/auto-mining.md`
**Budget cost**: 0 by default. Optional Phase D requires an exact-4 child audit batch.

> **MCP output shapes** — slimmed (`reference/mcp-output-shapes.md`). `get_alpha_yearly_stats` now returns `result.records` as labeled dicts (`{year, sharpe, fitness, …}` — no `schema` block; iterate directly). `get_alpha_pnl` is **downsampled to ≤~160 points** + drops the alpha vector — fine for drawdown / PnL-concentration / equity-curve-shape, not for daily-resolution work. Where this skill says "`is.checks[]` must contain …", read it against `checks.pass` / `checks.fail` / `checks.warning` (e.g. `"LOW_SUB_UNIVERSE_SHARPE" in checks.pass`). `is.<metric>` → `metrics.<metric>` (incl `metrics.robust_universe_sharpe`, `metrics.sub_universe_sharpe`, `metrics.two_year_sharpe`).

## 1. Purpose

Upgrade `SUBMITTABLE_PENDING` to `SUBMITTABLE_CONFIRMED` by verifying temporal stability and sub-universe survival. Downgrade to `PROMISING` only on hard fail.

This skill is a robustness triage gate, not a single-year veto. Its job is to estimate whether the alpha is likely to survive IS-to-OS decay. A small isolated bad year is a risk flag and may force `CONDITIONAL_PASS_MANUAL_ONLY`, but it must not automatically block manual property handoff when platform checks, ordered correlations, recent-year behavior, and anti-overfit evidence are otherwise strong.

## 2. Inputs

```yaml
alpha: {id, metrics, is_checks, fingerprint}  # tier == SUBMITTABLE_PENDING
region: "USA"
mode: conservative | aggressive
submit_policy:
  no_submit: bool
  manual_submit_corr_max: 0.70
session_state:
  budget_remaining: int
```

## 3. Outputs

```yaml
alpha_id: <same>
tier: SUBMITTABLE_CONFIRMED | PROMISING
decision: PASS | CONDITIONAL_PASS_MANUAL_ONLY | FAIL
upgrade: bool
property_path_allowed: bool      # false only for FAIL; S7.5 still decides final property_eligible
auto_submit_eligible: bool       # false for conditional manual-only
phase_results:
  yearly_cv: float
  min_yearly_sharpe: float
  negative_year_count: int
  severe_negative_year_count: int
  recent_negative_year_count: int
  recent_4y_avg_sharpe: float | null
  recent_4y_slope: float | null
  sub_universe_checks_ok: bool
  rolling_min_sharpe: float | null
  conditional_flags: [str]
failure_category: <category | null>   # only set if downgraded
```

## 4. MCP tools used

- `get_alpha_yearly_stats(alpha_id)` - Phase A, 0 budget
- `get_alpha_pnl(alpha_id)` - Phase C, 0 budget in conservative mode or when yearly flags are ambiguous
- `create_multi_simulation` - Phase D optional, only when exactly 4 audit expressions can share one settings block

## 5. Steps

### Phase A.1 - Yearly Sharpe stability

1. Call `get_alpha_yearly_stats(alpha_id)`.
2. Compute:
   - `yearly_sharpes = [year.sharpe for year in response.yearly]`
   - `yearly_cv = stdev(yearly_sharpes) / abs(mean(yearly_sharpes))`
   - `min_yearly_sharpe = min(yearly_sharpes)`
   - `negative_years = [year for year.sharpe < 0]`
   - `severe_negative_years = [year for year.sharpe < -0.50]`
   - `recent_years = latest four yearly records`
   - `recent_negative_years = [year in recent_years where sharpe < -0.30]`
3. Temporal decision thresholds:
   - `PASS`: `yearly_cv < 0.50`, `min_yearly_sharpe >= 0`, and no recent weakness flags.
   - `CONDITIONAL_PASS_MANUAL_ONLY`: no hard fail, with any of:
     - `0.50 <= yearly_cv < 0.90`
     - one isolated negative year with `min_yearly_sharpe >= -0.50`
     - a mild recent-year dip where recent four-year average and slope remain healthy.
   - `FAIL`: any of:
     - `yearly_cv >= 0.90`
     - `min_yearly_sharpe < -0.50`
     - `recent_negative_year_count > 0` and `recent_4y_avg_sharpe < 0.75`
     - `negative_year_count >= 2` or negative years exceed 20% of available years
     - yearly data is missing or malformed.
4. A single older mild negative year, such as `-0.14` in a ten-year IS window with strong recent four-year Sharpe, is `CONDITIONAL_PASS_MANUAL_ONLY`, not `FAIL`.
5. **Recent-strength override (user-authorized 2026-07-11).** When the candidate is *near-pass* — every platform gate passes AND `failed_ra_count == 0` AND `failed_ppa_count == 0` AND `self_corr < 0.40` AND `prod_corr < 0.70` (these four locks are NEVER relaxed), with only this temporal layer failing — evaluate the latest three full years (currently 2021/2022/2023):
   - If `mean(recent_3y_sharpe) >= 1.58` AND every one of the three years `>= 0.5`, the override supersedes `yearly_cv >= 0.50/0.90`, `negative_year_count >= 2`, and `min_yearly_sharpe < -0.50` **for years outside the recent-3y window** (including old crisis-year flags such as COVID-2020). Emit `decision = PASS` with `recent_strength_override: true` and list the overridden years in `override_tolerated_years`.
   - The override never covers: a negative or `< 0.5` year inside the recent-3y window, sub-universe failure, single-year PnL concentration `> 0.60`, heavy tails / slow recovery in the recent window, or any of the four hard locks above. S8 auto-submit locks apply unchanged.

### Phase A.2 - Regime and trend

From the same `yearly_stats` response:

1. **Crisis-year check**: for each `{COVID: 2020, RATE_HIKE: 2022}`:
   - If `sharpe < -0.50`, add a hard `REGIME_SEVERE_NEGATIVE` flag.
   - If `-0.50 <= sharpe < 0`, add conditional `REGIME_WATCH`.
   - Under an active recent-strength override (Phase A.1 §5), a `REGIME_SEVERE_NEGATIVE` on a crisis year **outside the recent-3y window** is demoted to `REGIME_WATCH` (recorded, non-blocking); crisis years inside the recent-3y window are never demoted.
2. **Full-window slope**:
   - `slope = cov(x,y) / var(x)` where `x = 0..n-1`, `y = yearly_sharpes`.
   - `slope < -0.35` is hard `SIGNAL_DECAY_TREND`.
   - `-0.35 <= slope < -0.15` is conditional `SIGNAL_DECAY_WATCH`.
3. **Recent four-year trend**:
   - Compute `recent_4y_avg_sharpe` and `recent_4y_slope`.
   - If `recent_4y_avg_sharpe < 0.50` or `recent_4y_slope < -0.35`, add hard `RECENT_4Y_HARD_WEAKNESS`.
   - If `0.50 <= recent_4y_avg_sharpe < 1.00` or `-0.35 <= recent_4y_slope < -0.20`, add conditional `RECENT_4Y_WATCH`.
4. **Drawdown consistency**:
   - If yearly drawdowns are available and `max(yearly_drawdowns) > 0.30`, add hard `LARGE_YEARLY_DRAWDOWN`.
   - If `0.20 < max(yearly_drawdowns) <= 0.30`, add conditional `YEARLY_DRAWDOWN_WATCH`.

Hard regime flags downgrade to `PROMISING`. Conditional regime flags keep the alpha in `SUBMITTABLE_CONFIRMED` but set `decision=CONDITIONAL_PASS_MANUAL_ONLY`.

### Phase B - Sub-universe survival

Read `alpha.is_checks`; look for:

- `LOW_SUB_UNIVERSE_SHARPE` with result == `FAIL`
- `HT_LIQUID_TOP200_SHARPE` with result == `FAIL`
- concentrated-weight or investability RA checks with result neither `PASS` nor `PENDING`

Any hard platform sub-universe/investability fail downgrades to `PROMISING`, `failure_category = sub_universe_fail`.

### Phase C - PnL deep analysis

Run in conservative mode or when Phase A is ambiguous:

1. Call `get_alpha_pnl(alpha_id)`.
2. Identify every returned curve in `result.properties`, typically raw `pnl`,
   `risk-neutralized-pnl`, and `investability-constrained-pnl`. Some alpha
   surfaces omit the risk-neutralized line; record this as `pnl_line_missing`
   rather than treating the absent line as a pass.
3. Compute the same curve-shape checks for each returned line where enough
   points exist, and summarize raw vs constrained divergence.
4. Compute rolling 252-day Sharpe.
   - `rolling_min_sharpe < -1.00` hard fails as `temporal_instability`.
   - `-1.00 <= rolling_min_sharpe < -0.50` is conditional unless paired with recent-year hard weakness.
5. Drawdown episodes:
   - `max_drawdown_duration_days > 180` hard fails as `slow_recovery`.
   - `120 < max_drawdown_duration_days <= 180` is conditional.
6. Tail days:
   - `tail_days > 45` hard fails as `tail_risk_high`.
   - `30 < tail_days <= 45` is conditional.
7. PnL concentration:
   - `pnl_concentration_top3 > 0.75` hard fails.
   - `0.65 < pnl_concentration_top3 <= 0.75` is conditional.
8. Constrained-line divergence:
   - If investability-constrained endpoint is less than 60% of raw endpoint or
     has materially worse drawdown timing, force `CONDITIONAL_PASS_MANUAL_ONLY`.
   - If a constrained line has the opposite sign or persistent recent
     deterioration while raw PnL is positive, hard fail unless an explicit
     investability repair is planned before properties.

### Phase D - Sub-universe re-sim (REQUIRED for PASS / CONDITIONAL — Cluster 5 / G3, 2026-05-09)

Phase D is no longer optional. Every alpha that would receive `decision in {PASS, CONDITIONAL_PASS_MANUAL_ONLY}` MUST have sub-universe evidence on record before the decision is sealed. Two evidence sources are accepted:

**(a) Existing platform RA evidence** — on the slimmed shape, `checks.pass` must contain BOTH:
- `"LOW_SUB_UNIVERSE_SHARPE"` (i.e. it was `PASS`)
- `"HT_LIQUID_TOP200_SHARPE"` (i.e. it was `PASS` — or the name is absent entirely, only acceptable when an audit batch covers it)
(equivalently: neither name appears in `checks.fail` or `checks.warning`). The numeric sub-universe value is in `metrics.sub_universe_sharpe`.

If both qualify, the alpha passes on existing evidence; record `sub_universe_evidence_source: "existing_check"` in the `robustness.audited` payload.

**(b) Audit batch re-sim** — when (a) is unavailable, dispatch an exact-4 `create_multi_simulation` audit batch with the **same expression** but rotating `universe`:
- Child 1: `TOP500`
- Child 2: `TOP200`
- Child 3: `TOP1000`
- Child 4: `TOP3000` baseline (sanity / non-regression)

All four must return `metrics.sharpe > 1.10` for the audit to PASS. Failure of any child → audit FAIL → `decision = FAIL`, `failure_category = sub_universe_fail`. Record `sub_universe_evidence_source: "audit_batch"` and the per-child Sharpe in `phase_results.audit_batch_sub_universe`.

Budget: each audit costs 4 child sims per CONFIRMED candidate. Per Cluster 1, this cost is calibrated into the dataset_tier policy (produce_lit absorbs the cost; explore_unlit downgrades to PROMISING-only without consuming audit budget).

If neither (a) nor (b) can be obtained for any reason → `decision = FAIL`, `failure_category = sub_universe_evidence_missing`.

Operational rules (preserved from prior Phase D):

1. Use `create_multi_simulation` with 1–4 children and one shared settings block; default 4. Single-sim `create_simulation` is forbidden.
2. Prefer already-simulated siblings before spending budget.
3. If fewer than 4 non-duplicate audit expressions exist, dispatch what is available with `dispatch_size_reason` (e.g. `"single_sub_universe_confirmation"`) instead of deferring outright when the audit is decisive.
4. On timeout or missing children, record unresolved/recovery state and do not immediately duplicate dispatch.

### Phase F - Regime concentration scorecard (Cluster 5 / G4, 2026-05-09)

After Phase A.1 yearly stats are computed, for each year `y` in available history:

```python
share_y = sharpe_y / sum(abs(sharpe_*) for * in years if abs(sharpe_*) > 0)
```

Decision logic:
- `max(share_y) > 0.60` → emit `attribution.regime_concentration_flag { year: argmax_year, share: <float>, threshold: 0.60 }`. Forces `decision = CONDITIONAL_PASS_MANUAL_ONLY` even when Phase A–D would otherwise PASS. Reason: the alpha's positive Sharpe is concentrated in one regime; out-of-regime behavior is unproven.
- `max(share_y) > 0.75` → hard fail, `decision = FAIL`, `failure_category = regime_concentration`.
- `max(share_y) <= 0.60` → no flag.

The Phase F flag is mirrored in `wqb-anti-overfit-gate` Phase B at the 0.75 hard-fail threshold so post-S6 anti-overfit cannot whitewash a regime-concentrated alpha.

### Phase E - Decision

1. `PASS`:
   - all hard checks pass
   - no conditional flags
   - `tier = SUBMITTABLE_CONFIRMED`
   - `upgrade = true`
   - `auto_submit_eligible` may remain true, subject to S7.5 and S8 locks
2. `CONDITIONAL_PASS_MANUAL_ONLY`:
   - no hard fail
   - one or more conditional temporal/regime/PnL flags remain
   - `tier = SUBMITTABLE_CONFIRMED`
   - `upgrade = true`
   - `property_path_allowed = true`
   - `auto_submit_eligible = false`
3. `FAIL`:
   - any hard temporal, regime, sub-universe, investability, drawdown, tail, or concentration failure
   - `tier = PROMISING`
   - `upgrade = false`
   - set `failure_category`

Emit `robustness.audited`:

```yaml
alpha_id: <id>
upgrade: bool
decision: PASS | CONDITIONAL_PASS_MANUAL_ONLY | FAIL
property_path_allowed: bool
auto_submit_eligible: bool
phase_results:
  yearly_cv: float
  min_yearly_sharpe: float
  negative_year_count: int
  severe_negative_year_count: int
  recent_negative_year_count: int
  conditional_flags: []
  regime_failures: []
  yearly_sharpe_slope: float
  recent_4y_avg_sharpe: float|null
  recent_4y_slope: float|null
  covid_year_sharpe: float|null
  rate_hike_year_sharpe: float|null
  sub_universe_checks_ok: bool
  sub_universe_evidence_source: <null | "existing_check" | "audit_batch">
  audit_batch_sub_universe: <null | {top500: float, top200: float, top1000: float, top3000: float}>
  regime_concentration_share: <null | float>          # max(share_y) computed in Phase F
  regime_concentration_flag: <null | "conditional" | "hard_fail">
  rolling_min_sharpe: float|null
  max_drawdown_duration_days: int|null
  drawdown_episode_count_5pct: int|null
  tail_days: int|null
  pnl_concentration_top3: float|null
failure_category: <null | temporal_instability | regime_fragile | sub_universe_fail | sub_universe_evidence_missing | regime_concentration | slow_recovery | tail_risk_high | pnl_concentration_high>
```

## 6. Events emitted

`robustness.audited` per alpha, plus any `batch.budget_checked` and `sim.*` series if Phase D runs.

## 7. Constraints

- Do not call `submit_alpha`, `set_alpha_properties`, or `check_correlation`.
- Phase D is optional and budget-gated.
- Never use `create_simulation`.
- Never chain upgrades. A hard-failed alpha goes to S6.5/S7 repair.
- Do not use parameter search as a substitute for attribution.
- Do not treat a single mild old negative year as a hard failure.

## 8. Self-validation

- [ ] `robustness.audited` event exists for every input alpha.
- [ ] `decision` is one of `PASS`, `CONDITIONAL_PASS_MANUAL_ONLY`, or `FAIL`.
- [ ] Isolated mild negative year is conditional manual-only, not a hard fail.
- [ ] `auto_submit_eligible=false` for every conditional robustness decision.
- [ ] Alphas with `upgrade=true` are tagged only as `SUBMITTABLE_CONFIRMED`.
- [ ] Alphas with `upgrade=false` get a valid `failure_category`.
- [ ] Optional simulations, if any, used `create_multi_simulation` (1–4 children, default 4; smaller batches carry `dispatch_size_reason`).
