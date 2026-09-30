---
name: wqb-anti-overfit-gate
description: "Decide whether a SUBMITTABLE_CONFIRMED alpha is genuinely robust enough to receive properties or be considered for submission. This is a pre-property anti-overfit gate: it combines platform checks, correlation, yearly/regime evidence, attribution, parameter-neighborhood tests, structural… Part of the WorldQuant BRAIN auto-mining workflow (S7.5 of workflow/auto-mining.md)."
---

# Skill: wqb-anti-overfit-gate

**Consumers**: Claude Code · GitHub Copilot · Codex · generic assistants
**Stage**: S7.5 of `workflow/auto-mining.md`
**Budget cost**: 0 default; optional perturbation tests cost 4/8/12 child sims via `create_multi_simulation`

> **MCP output shapes** — slimmed (`reference/mcp-output-shapes.md`). **`platform_lock.failed_ra_count` = `a.ra.failed_ra_count`** (precomputed server-side per WebDataScope; `a.ra.ra_failed_checks` = the offending names; PPA-side = `a.ra.failed_ppa_count`) — read it, don't recount. `is.sharpe` → `metrics.sharpe`; `riskNeutralized.sharpe` → `metrics.risk_neutralized_sharpe`; `investabilityConstrained.sharpe`/`.fitness` → `metrics.investability_sharpe`/`metrics.investability_fitness`. `get_alpha_pnl` is downsampled (≤~160 pts, no alpha vector).

## 1. Purpose

Decide whether a `SUBMITTABLE_CONFIRMED` alpha is genuinely robust enough to receive properties or be considered for submission. This is a pre-property anti-overfit gate: it combines platform checks, correlation, yearly/regime evidence, attribution, parameter-neighborhood tests, structural perturbations, settings perturbations, and risk/investability gaps into one objective decision.

This skill exists because robustness is not the same as a parameter search. The final decision must explain what signal layer works, whether nearby choices also work, whether nontrivial structural changes preserve the edge, and which market/regime risks remain.

## 2. Inputs

```yaml
alpha:
  alpha_id: str
  expression: str
  settings: dict
  metrics: dict
  is_checks: list
  tier: SUBMITTABLE_CONFIRMED
  hypothesis:
    dataset_id: str
    task_type: str
    paradigm: str
    fields: [str]
    zero_order_provenance: dict | null
    expected_logic: str
attribution_report:
  path: str | null
  root_cause_layer: str | null
  layer_ablation_summary: list
  yearly_attribution: dict
  risk_attribution: dict
  market_regime_hypothesis: str | null
available_sibling_tests:
  parameter_neighborhood: list  # already-simulated variants, if any
  structural_perturbations: list
  settings_perturbations: list
mode: conservative | aggressive
submit_policy:
  no_submit: bool
  manual_submit_corr_max: 0.70
  auto_submit_corr_max: 0.70
session_state:
  budget_remaining: int
  anti_overfit_budget_max: int  # default 12 child sims per alpha
```

## 3. Outputs

```yaml
anti_overfit_decision:
  alpha_id: str
  decision: PASS | CONDITIONAL_PASS_MANUAL_ONLY | FAIL
  property_eligible: bool
  auto_submit_eligible: bool
  report_path: analytics/overfit-eval-<alpha_id>-<date>.md
  platform_lock:
    failed_ra_count: int
    prod_corr: float | null
    self_corr: float | null
    corr_returned: bool
  warning_diagnostic:
    warnings: [str]
    note: str
  temporal_lock:
    yearly_cv: float | null
    min_yearly_sharpe: float | null
    recent_4y_avg_sharpe: float | null
    recent_4y_slope: float | null
    pnl_concentration_top3: float | null
    flags: [str]
  attribution_lock:
    attribution_present: bool
    root_cause_layer: str | null
    source_layer_has_positive_evidence: bool
    wrapper_only_edge: bool
  perturbation_lock:
    parameter_family: dict
    structural_family: dict
    settings_family: dict
  risk_lock:
    risk_gap: float | null
    investability_gap: float | null
    flags: [str]
  complexity_lock:
    operatorCount_estimate: int | null
    unique_fields: int
    flags: [str]
  failure_categories: [str]
  manual_review_notes: [str]
```

Failed RA is the WebDataScope rule (canonical list and result-value semantics in `reference/submission-gates.md` §9). `failed_ra_count` counts `is.checks[]` entries whose `name` is in `RA_CHECK_NAMES` and whose `result` is neither `PASS` nor `PENDING`. `WARNING` on a name **inside** `RA_CHECK_NAMES` (e.g. `LOW_GLB_AMER_SHARPE`, `LOW_GLB_EMEA_SHARPE`, `LOW_SUB_UNIVERSE_SHARPE`, `LOW_2Y_SHARPE`) **counts as a fail** — the platform itself will reject these at submit time. `WARNING` on names **outside** the list (e.g. `MATCHES_THEMES`) is diagnostic and goes to `warning_diagnostic` only. `failed_ra_count == 0` is the platform RA-check pass.

## 4. MCP tools used

| Tool | When |
|---|---|
| `get_alpha_details` | always, unless current-session details are already fresh |
| `get_alpha_yearly_stats` | always, unless S6/S6.5 yearly stats are attached |
| `get_alpha_pnl` | conservative mode or when yearly concentration/regime flags are ambiguous |
| `check_self_correlation` | always first; self correlation must return and pass before production correlation is queried |
| `check_correlation` | only after `check_self_correlation` passes; production correlation must have returned |
| `create_multi_simulation` | optional perturbation tests only, exactly 4 children per call |

Never use `create_simulation`.

## 5. Steps

### Phase A - Platform and correlation lock

1. Read `failed_ra_count = a.ra.failed_ra_count` from a fresh `get_alpha_details(alpha_id)` (or the current-session slim-alpha) — the MCP precomputes the WebDataScope Failed RA rule (`reference/submission-gates.md` §9 / verbatim port of `WebDataScope-0.10.20/src/scripts/background.js` `getAlphaCheckStates`). Require `failed_ra_count == 0`. `a.ra.ra_failed_checks` lists which names tripped it; any in-list-name `WARNING` (sub-universe, 2y, fitness, sharpe, returns, turnover, concentrated_weight, IS_LADDER, …) is already counted there — `WARNING` is not soft-pass at submission. Out-of-list `WARNING`s (e.g. `MATCHES_THEMES`) are in `checks.warning` but excluded from `failed_ra_count` → record under `warning_diagnostic`. (Also note `a.ra.failed_ppa_count` for the PPA-side gate when relevant.)
3. Verify the user-target IS ladder:
   - `Sharpe > 1.58`
   - `Fitness > 1.00`
   - `Margin > 10 bp`
   - `0.01 <= Turnover <= 0.70`
   - `Returns > 0.05` and `abs(Returns) > abs(Drawdown)`
4. Call `check_self_correlation(alpha_id)` first.
5. Hard fail if self-correlation has not returned or `self_corr >= manual_submit_corr_max`; do **not** call `check_correlation`.
6. Only after self-correlation passes, call `check_correlation(alpha_id)` for production correlation.
7. Hard fail if production correlation has not returned.
8. For property/manual eligibility, require `failed_ra_count == 0`, `prod_corr < manual_submit_corr_max`, and `self_corr < manual_submit_corr_max`.
9. For auto-submit eligibility, require `prod_corr < auto_submit_corr_max` and `self_corr < auto_submit_corr_max`.

### Phase B - Temporal and regime lock

Use `get_alpha_yearly_stats` and, in conservative mode, `get_alpha_pnl`:

1. Compute yearly Sharpe CV, min yearly Sharpe, negative-year count, severe-negative-year count, full-window slope, recent four-year average, recent four-year slope, recent negative-year count, and top-three positive-PnL concentration.
2. Hard fail:
   - `min_yearly_sharpe < -0.50`
   - `negative_year_count >= 2` or negative years exceed 20% of available years
   - any latest four-year Sharpe < -0.30 paired with `recent_4y_avg_sharpe < 0.75`
   - `yearly_cv >= 0.90`
   - `recent_4y_avg_sharpe < 0.50`
   - `recent_4y_slope < -0.35`
   - `pnl_concentration_top3 > 0.75`
3. Conditional manual-only:
   - one isolated older negative Sharpe year with `min_yearly_sharpe >= -0.50`
   - `0.50 <= yearly_cv < 0.90`
   - `-0.35 <= recent_4y_slope < -0.20`
   - any latest four-year Sharpe is between `0` and `0.30`
   - `0.65 < pnl_concentration_top3 <= 0.75`
4. A single old mild negative year, for example 2019 Sharpe `-0.14`, is not a hard overfit failure by itself. It should add a temporal watch flag, force `CONDITIONAL_PASS_MANUAL_ONLY`, and remain eligible for manual property handoff only if Phase A, C, D, E, F, G, and all platform/correlation locks pass.

### Phase C - Attribution and causal-source lock

1. Require a current `attribution.generated` report for the alpha or its exact expression family.
2. Require layer decomposition from raw/L0/L1/L2/settings. If missing, run or request S6.5 before this gate.
3. Pass only when the positive edge is traceable to a plausible source layer:
   - L0 economics, L1 temporal extraction, L2 cohort logic, or settings-neutralization interaction.
4. Fail when the only positive evidence is a wrapper-only change (`trade_when`, generic rank, decay, or bucket) without a positive raw/L0/L1 source.
5. If `trade_when`, hard thresholds, or event gates appear in the expression, require an explicit return-source audit: ungated parent evidence must be positive or at least platform-floor directional, nearby gate/threshold variants must not cliff, and negative controls must be weaker or inverted. Otherwise hard fail as `surface_metric_gate_overfit`.
6. If raw single-field controls, reverse-sign controls, or absolute-value controls were run, record them. Negative controls should be weak or inverted in the expected direction; if they work as well as the target, flag `ambiguous_causality`.

### Phase D - Parameter-neighborhood lock

Use existing sibling tests first. If missing and budget allows, dispatch one 4-child `create_multi_simulation` batch around the main numeric choice. Examples:

- threshold: `x - 0.02`, `x`, `x + 0.02`, `x + 0.04`
- decay/window: nearby shorter and longer values
- bucket range: coarser and finer bucket axis

Rules:

1. Count the original alpha as one member only if it shares the same settings block.
2. At least 3 of 4 neighborhood variants must pass the IS ladder.
3. At least the original and one adjacent variant must satisfy manual correlation (`self_corr < 0.40` first — effective gate per `reference/submission-gates.md §6/§8`, not the 0.7 platform floor — then `prod_corr < 0.70`). Do not call `check_correlation` for a variant unless its `check_self_correlation` pass has already succeeded.
4. Hard fail if a tiny nearby parameter move causes Sharpe to drop by more than 30% while all other structure is unchanged.
5. Conditional manual-only if 2 of 4 pass but failures are explainable by correlation or known regime constraints.

### Phase E - Structural perturbation lock

Parameter sweeps are not enough. Use existing sibling tests first; otherwise dispatch perturbation batches through `create_multi_simulation` (1–4 children, default 4; per `workflow/auto-mining.md §0.11`, anti-overfit perturbation accepts ≥ 1 child + same shared settings + explicit `dispatch_size_reason`):

- replace a generic bucket axis with an economically meaningful axis
- change L0 construction while keeping the same economic sign
- add/remove winsorization or neutralization around the same L0
- change exponent/sign transform in a way that preserves the hypothesis

Rules:

1. At least one nontrivial structural perturbation must remain positive and economically consistent.
2. It does not need to beat the parent, but should satisfy platform floor and preserve sign.
3. Fail if every structural perturbation collapses while only the exact parent passes.
4. Conditional manual-only if structural variants preserve sign but fall below the stricter user-target ladder.

### Phase F - Settings perturbation lock

Where valid for the region/dataset, compare neutralization and one other
materially different shared-settings family:

- neutralization: original versus `STATISTICAL`/`INDUSTRY`/`SUBINDUSTRY` when allowed
- truncation: nearby lower/higher truncation
- decay: nearby shared setting if not already tested inside expression

Rules:

1. Dispatch 1–4 children (default 4) in a shared-settings `create_multi_simulation` call; smaller batches require an explicit `dispatch_size_reason` payload field.
2. A strong PASS requires at least two neutralization surfaces in total,
   including the original setting, to keep platform floor, user 2Y ladder, and
   `failed_ra_count == 0`. For example, `REVERSION_AND_MOMENTUM + INDUSTRY`
   can pass; original-only cannot be called settings-robust.
3. Conditional manual-only if alternate neutralization remains directionally
   positive but falls below user target or trips only the 2Y/IS-ladder RA.
4. Fail if every alternate neutralization collapses, or if the alpha only works
   under one brittle setting and risk/investability attribution shows large
   exposure dependence.
5. Do not substitute raw headline Sharpe for this check. If an alternate
   neutralization has Sharpe > 1.58 but fails `IS_LADDER_SHARPE`,
   `LOW_ROBUST_UNIVERSE_SHARPE`, or any other RA check, it is not a pass.

### Phase G - Risk, investability, and complexity lock

From `get_alpha_details` and the attribution report:

1. `risk_gap = metrics.sharpe - metrics.risk_neutralized_sharpe`.
2. `investability_gap = metrics.sharpe - metrics.investability_sharpe`.
3. Pull `get_alpha_pnl(alpha_id)` in conservative mode and require review of
   all returned PnL lines: raw `pnl`, `risk-neutralized-pnl` when returned, and
   `investability-constrained-pnl` when returned. Missing constrained lines
   must be written to the report and treated as unknown, not as a pass.
4. Conditional manual-only:
   - `risk_gap > 0.50`
   - `investability_gap > 0.50`
   - constrained PnL endpoint is less than 60% of raw PnL endpoint, even if
     platform RA checks pass
   - unique fields > 3 or operatorCount_estimate > 8
5. Hard fail:
   - `risk_gap > 0.80` and settings perturbation also fails
   - `investability_gap > 0.80` plus sub-universe or weight-concentration warning
   - constrained PnL has opposite sign or materially negative recent slope while
     raw PnL remains positive
   - unique fields > 3

### Phase H - Decision

Decision rules:

For `region == "MEA"`, first require a current `mea_stability.checked` event for the same alpha with `decision = PASS` and `property_eligible = true`. If the event is missing, stale, or not PASS, set this gate's `property_eligible = false` even if the generic anti-overfit checks are otherwise acceptable.

1. `FAIL`:
   - any Phase A hard fail
   - any Phase B hard fail
   - attribution missing or wrapper-only edge
   - `trade_when` / threshold / event-gate edge lacks positive ungated source evidence or negative-control support
   - parameter-neighborhood cliff
   - every structural perturbation collapses
   - settings-only dependency with large risk/investability gap
2. `PASS`:
   - all hard locks pass
   - no conditional flags
   - correlation satisfies the submit threshold (`< 0.70`) when auto-submit is enabled
3. `CONDITIONAL_PASS_MANUAL_ONLY`:
   - platform/correlation/user metrics pass for manual threshold (`< 0.70`)
   - no hard fail
   - one or more conditional flags remain
   - `auto_submit_eligible = false`

Property setting is allowed only when `property_eligible = true`. Auto-submit is allowed only when `decision = PASS` and `auto_submit_eligible = true`.

`property_eligible` must be false whenever `platform_lock.failed_ra_count != 0`, production/self correlation has not returned, or either correlation is at/above the manual threshold. A manual-review or `NoSubmit` posture does not relax these locks; it only affects whether `submit_alpha` may be called after properties.

### Phase I - Report

Write `analytics/overfit-eval-<alpha_id>-<date>.md` with:

1. final decision and property/auto-submit eligibility
2. all numeric test outcomes
3. layer-by-layer interpretation from simple to complex
4. simplification plan from the attribution report, including which expression
   components should be kept, downweighted, removed, or controlled
5. economic explanation tied to the dataset fields and observed years
6. statistical explanation of signal extraction and remaining risks
7. rejected alternative explanations
8. repair recommendations when the decision is not `PASS`

If the alpha later reaches S8 property handoff, the English description must be
derived from this report and state: the return source, the main risks, when the
alpha is expected to work, and when it is expected to fail. Do not describe an
alpha as property-ready if those four points are missing.

## 6. Events emitted

Emit `overfit.checked`:

```json
{
  "kind": "overfit.checked",
  "payload": {
    "alpha_id": "...",
    "decision": "CONDITIONAL_PASS_MANUAL_ONLY",
    "property_eligible": true,
    "auto_submit_eligible": false,
    "report_path": "analytics/overfit-eval-...md",
    "platform_lock": {"prod_corr": 0.68, "self_corr": 0.57, "corr_returned": true},
    "warning_diagnostic": {"warnings": ["MATCHES_THEMES"], "note": "diagnostic only; Failed RA is the hard RA-check lock"},
    "temporal_lock": {"recent_4y_slope": -0.31, "flags": ["recent_decay_watch"]},
    "attribution_lock": {"root_cause_layer": "l0_construction", "wrapper_only_edge": false},
    "perturbation_lock": {"parameter_pass_count": 4, "structural_pass_count": 1, "settings_pass_count": 1},
    "risk_lock": {"risk_gap": 0.12, "investability_gap": 0.22, "flags": []},
    "failure_categories": ["signal_decay_trend"],
    "budget_consumed": 8
  }
}
```

Also emit `batch.budget_checked` and `sim.*` events for any perturbation batch that is dispatched.

## 7. Constraints

- Do not call `set_alpha_properties`.
- Do not call `submit_alpha`.
- Do not call `create_simulation`.
- Do not call an alpha property-ready if production/self correlation has not returned.
- Do not substitute parameter search for causal attribution.
- Use already-simulated siblings before spending budget.
- Optional perturbation sims are capped by `session_state.anti_overfit_budget_max`; default 12 child sims per alpha.
- If fewer than 4 perturbation expressions are available after non-duplicate controls or nearby variants, defer the test; never use single-sim fallback.

## 8. Self-validation

- [ ] `overfit.checked` exists before any `set_alpha_properties` call for this alpha
- [ ] `property_eligible=false` for missing correlation, failed platform locks, missing attribution, or wrapper-only edge
- [ ] `property_eligible=false` unless `platform_lock.failed_ra_count == 0`
- [ ] For MEA, `property_eligible=false` unless `mea_stability.checked.decision=PASS`
- [ ] `auto_submit_eligible=false` for every conditional decision
- [ ] Optional sims, if any, used `create_multi_simulation` (1–4 children, default 4; smaller batches carry `dispatch_size_reason`)
- [ ] Report path exists and includes layer, temporal, perturbation, risk, economic, and statistical sections
- [ ] Report includes an English property-description draft covering return source, risks, valid regime, and failure regime
