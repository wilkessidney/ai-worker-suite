---
name: wqb-attribution-analyst
description: "Explain why an alpha makes or loses money before repair. This skill performs layer ablation, yearly/regime attribution, risk/investability attribution, and root-cause repair recommendations. Part of the WorldQuant BRAIN auto-mining workflow (S6.5 / S7-pre of workflow/auto-mining.md)."
---

# Skill: wqb-attribution-analyst

**Consumers**: Claude Code · GitHub Copilot · Codex · generic assistants
**Stage**: S6.5 / S7-pre of `workflow/auto-mining.md`
**Budget cost**: 0 by default; optional ablation simulations must use exact-4 `create_multi_simulation` batches

> **MCP output shapes** — slimmed (`reference/mcp-output-shapes.md`). `is.sharpe` → `metrics.sharpe`; `riskNeutralized.sharpe` → `metrics.risk_neutralized_sharpe`; `investabilityConstrained.sharpe` → `metrics.investability_sharpe`; `get_alpha_yearly_stats` → `result.records` (labeled dicts); `get_alpha_pnl` downsampled (≤~160 pts, no alpha vector); layer-ablation re-sim children carry `metrics`/`checks` flattened.

## 1. Purpose

Explain **why** an alpha makes or loses money before repair. This skill performs layer ablation, yearly/regime attribution, risk/investability attribution, and root-cause repair recommendations.

Robustness is not parameter search. It is a causal diagnosis of the signal's economic and statistical source.

Special caution: `trade_when`, hard thresholds, and event gates can create attractive in-sample metrics by selecting favorable observations. Attribution must separate true source returns from gate-selection effects, timing effects, risk exposure, liquidity/investability filters, and wrapper reshaping before any repair or property decision.

## 2. Inputs

```yaml
alpha:
  alpha_id: str
  expression: str
  settings: dict
  metrics: dict
  is_checks: list
  hypothesis:
    zero_order_field: str | null
    l0_family: ratio | spread | surprise | intensity | interaction | unknown
    expected_direction: positive | negative | unknown
    economic_hypothesis: str
candidate_context:
  layer_expressions:
    raw_field_baseline: str | null
    l0: str
    l1: str
    l2: str | null
  dataset_id: str
  region: str
mode: conservative | fast
session_state:
  budget_remaining: int
```

## 3. Outputs

```yaml
attribution_report:
  alpha_id: str
  root_cause_layer: raw_field | l0_construction | l1_temporal | l2_bucket | settings_neutralization | coverage_axis | regime | liquidity | canonical_crowding | unknown
  layer_ablation_summary:
    - layer: l0
      expression: str
      metrics: dict | null
      conclusion: str
  yearly_attribution:
    best_years: [int]
    worst_years: [int]
    recent_4y_sharpe_avg: float
    recent_4y_slope: float
    pnl_concentration_top_years: float
  risk_attribution:
    raw_vs_risk_neutralized_gap: float
    raw_vs_investability_gap: float
    likely_exposure: liquidity | sector | country | crowding | sparse_coverage | cap | canonical_crowding | none | unknown
  eur_glb_forum_policy:
    coverage_axis: date | instrument | coverage_proxy | unknown
    cohort_axis_suspect: country | country_x_subindustry | country_x_sector | liquidity | volatility | size | none
    canonical_crowding_risk: low | medium | high
    evidence: [str]
  return_source_attribution:
    source_edge_component: raw_field | l0 | l1 | l2_gate | settings | unknown
    ungated_parent_evidence: positive | weak | absent | not_tested
    gate_selection_effect: positive | negative | neutral | not_applicable
    wrapper_only_edge: bool
  research_rationale_audit:
    economic_mechanism: pass | weak | fail
    statistical_evidence: pass | weak | fail
    signal_processing: pass | weak | fail
    notes: [str]
  market_regime_hypothesis: str
  repair_plan:
    - action: str
      target_layer: str
      reason: str
      expression_hint: str
```

Emit `attribution.generated`.

## 4. MCP tools used

| Tool | When |
|---|---|
| `get_alpha_yearly_stats` | always |
| `get_alpha_pnl` | conservative mode or best-in-family alpha |
| `get_alpha_details` | when metrics/checks are missing |
| `create_multi_simulation` | optional exact-4 ablation sims only; never single-sim |

## 5. Steps

### Phase A — Parse expression layers

Identify:

1. **Raw fields**: every platform field id.
2. **L0 construction**: first arithmetic/vector construction combining raw fields.
3. **L1 extraction**: first `ts_*`, rank/zscore, backfill, winsorize, or event transform applied to L0.
4. **L2 modifiers**: `group_neutralize`, custom `bucket`, `trade_when`, `hump`, `quantile`, `scale`, settings neutralization.

If layers cannot be parsed confidently, ask S3 to include `layer_expressions` in future hypotheses and mark `root_cause_layer: unknown`.

### Phase B — Layer ablation

For every best-in-family or PROMISING alpha, compare available child alphas or run an exact-4 ablation batch when budget allows:

| Layer | Required question |
|---|---|
| raw field | Does any single raw field have signal, or is it noise? |
| L0 | Does the two-field economic construction create the edge? |
| L1 | Does temporal abnormality/change produce the edge? |
| L2 | Does bucket/gate/neutralization add true information or just reshape? |
| settings | Does risk neutralization preserve or destroy PnL? |

The report must walk the alpha from simple to complex and assign marginal
return contribution at each layer: raw field -> L0 -> L1 -> L2/wrapper ->
settings. For each added component, classify it as `keep`, `downweight`,
`remove`, or `needs_control`. A component is removable when it improves only
headline Sharpe while worsening 2Y, risk-neutralized, investability-constrained,
sub-universe, turnover/margin, or correlation behavior. The repair plan should
prefer the simplest expression that preserves the validated return source.

Optional ablation expressions must be dispatched in exact-4 groups through `create_multi_simulation`. If fewer than 4 ablations are available after non-duplicate controls or nearby variants, defer rather than using `create_simulation`.

For `trade_when` / threshold / event-gate alphas, always compare or request the nearest available controls:

1. ungated L0/L1 parent with the same sign and settings;
2. relaxed or distribution-matched gate variant;
3. reverse-sign or stale/shifted timing negative control when field semantics allow;
4. same source with a non-gating signal-processing extractor (`ts_rank`, `ts_zscore`, `ts_delta`, `ts_regression`, `hump`) when available.

If the gated expression works but the ungated parent and economically equivalent controls are weak, set `return_source_attribution.wrapper_only_edge=true` and recommend returning to L0/L1 source construction rather than adding more wrappers.

### Phase C — Yearly and recent-trend attribution

Use `get_alpha_yearly_stats`:

1. Sort years by PnL and Sharpe.
2. Compute `pnl_concentration_top_years = top_3_year_pnl / total_positive_pnl`.
3. Compute recent four-year average and slope from the latest four years in the IS window.
4. Flag:
   - `regime_dependent` if top 3 years contribute > 65% of positive PnL.
   - `recent_decay` if recent four-year slope < -0.15 or average Sharpe < 0.5.
   - `yearly_instability` if any year has Sharpe < 0 and the hypothesis is not explicitly regime-gated.

### Phase D — Risk, liquidity, and investability attribution

From `get_alpha_details`:

1. `risk_gap = metrics.sharpe - metrics.risk_neutralized_sharpe`.
2. `investability_gap = metrics.sharpe - metrics.investability_sharpe`.
3. In conservative mode, also call `get_alpha_pnl(alpha_id)` and inspect every
   returned PnL line, not just the raw `pnl` curve. The common line names are
   `pnl`, `risk-neutralized-pnl`, and `investability-constrained-pnl`; some
   regions/alphas return only two of them. Record missing lines explicitly as
   `pnl_line_missing`, and do not infer that a missing line passed.
4. Compare final cumulative value, major drawdown episodes, and curve shape
   across the returned PnL lines:
   - Raw PnL rising while investability-constrained PnL is flat or unstable
     means the edge is likely liquidity/cap/coverage dependent.
   - Raw PnL rising while risk-neutralized PnL is much weaker means the edge is
     likely style/sector/country/risk exposure dependent.
   - A source is attribution-clean only when the raw, risk-neutralized when
     returned, and investability-constrained lines agree in sign and broad
     timing, even if constrained Sharpe is lower.
5. Interpret:
   - Large `risk_gap > 0.5`: likely sector/country/style exposure.
   - Large `investability_gap > 0.5`: liquidity, sparse coverage, or small-name concentration.
   - Sub-universe fail with good raw IS: tail-universe dependency.
   - Risk-neutralized Sharpe near raw Sharpe but low total Sharpe: true signal exists but weak breadth or poor timing.

For every region, add a robust-cohort diagnosis when the alpha shows
`LOW_ROBUST_UNIVERSE_SHARPE`, `LOW_SUB_UNIVERSE_SHARPE`, concentrated-weight
failure, or a large investability/risk-neutralized gap. Test whether size,
liquidity, volatility, source coverage/count, source relevance/attention,
source novelty/similarity, or market-specific cohorts explain the weakness
better than a generic turnover wrapper. If a cohort axis is plausible, emit it
in the repair plan with `cohort_axis_family` and `bucket_axis_hypothesis`; if no
axis is plausible, emit a falsifiable skip reason.

For `region in {"EUR", "GLB"}`, also add a coverage/cohort diagnosis using
`reference/EUR-GLB-forum-lessons-2026-05-05.md`:

1. Separate date coverage from instrument coverage. If failures line up with
   sparse dates, suggest `ts_backfill` only with a cadence reason. If failures
   line up with sparse instruments, suggest semantic `group_backfill` or broader
   source breadth.
2. Separate country exposure from sector/industry exposure. A country gap can be
   a source of false returns, a missing cohort axis, or a settings issue.
3. Check whether the alpha is a canonical high-usage template: single popular
   source field, common wrapper, no differentiated L0 pair, and high prod corr.
   If yes, set `root_cause_layer=canonical_crowding` rather than recommending
   wrapper repair.
4. For sub-universe or investability failures, test whether liquidity,
   volatility, size, or country-crossed cohorts explain the weakness better than
   a generic turnover wrapper.

### Phase E — Market regime hypothesis

Write a concise market explanation tied to the field semantics:

Examples:

- Insider abnormal selling works in risk-off / rate-up years because negative private information is repriced faster.
- Analyst estimate revisions decay in high-dispersion earnings seasons but fail when macro beta dominates.
- Option call-put imbalance works around volatility repricing but may invert in meme/liquidity regimes.

The explanation must cite observed yearly behavior, not generic finance theory.

### Phase F — Repair plan

Repair the layer that attribution identified:

| Root cause | Repair |
|---|---|
| weak raw field | abandon field or combine into L0; do not wrap |
| L0 creates edge but L1 weak | change temporal extractor/window |
| L1 creates edge but L2 weak | remove or redesign bucket/gate |
| investability collapse | add liquidity-aware bucket/gate or switch universe/settings |
| risk exposure | custom bucket/group neutralize on the exposure axis |
| coverage axis | date gap -> justified `ts_backfill`; instrument gap -> semantic `group_backfill`; coverage proxy -> rebuild source |
| regime dependence | explicit regime gate or accept as non-submit seed |
| recent decay | shorten lookback or abandon for current quarter |
| high duplicate correlation | change L0 construction, not only wrapper |
| canonical crowding | change source pair or meaningful cohort axis; avoid wrapper-only decrowding |
| wrapper-only gate edge | remove `trade_when`/threshold wrapper; rebuild source L0/L1 and run negative controls before any new gate |

## 6. Events emitted

`attribution.generated`:

```json
{
  "kind": "attribution.generated",
  "payload": {
    "alpha_id": "...",
    "root_cause_layer": "l1_temporal",
    "yearly": {"best_years": [2016, 2017, 2022], "recent_4y_slope": 0.2},
    "risk": {"risk_gap": 0.03, "investability_gap": 0.52, "likely_exposure": "liquidity"},
    "simplification_plan": [{"component": "auxiliary_gate", "action": "remove", "reason": "no positive marginal 2Y or constrained-PnL contribution"}],
    "repair_plan": [{"target_layer": "l0_construction", "action": "add liquidity bucket"}]
  }
}
```

## 7. Constraints

- Do not call `submit_alpha` or `set_alpha_properties`.
- Do not treat parameter sweeps as attribution.
- Do not recommend a repair unless it names the failing layer.
- Do not recommend keeping a component unless the layer attribution shows positive
  marginal contribution after robustness, constrained-PnL, and correlation checks.
- If self-correlation has not passed first, or production correlation has not returned after that pass, do not call the alpha manual-submit-ready.
- Always include an economic explanation and a statistical explanation.
- Always include a signal-processing explanation for the chosen transform/window.
- Treat `trade_when`/threshold/event-gate success without ungated source evidence as `wrapper_only_edge`; do not recommend additional gates or threshold sweeps as the primary repair.
- For EUR/GLB, do not collapse robust/sub-universe/weight concentration into one generic failure. Name the most likely coverage/cohort layer and the evidence that would falsify it.
- **Coverage fan-out (added 2026-05-08)**: when invoked at S6.5, emit exactly one `attribution.generated` per **PROMISING** alpha in the batch (and per best-in-family near-miss when no PROMISING exists). Skipping a PROMISING alpha is a workflow defect: the next session's `wqb-self-diagnostic` will flag it as `attribution.coverage_gap`. If an alpha is intentionally skipped (e.g. duplicate of an already-attributed parent), emit `attribution.skipped { alpha_id, reason }` so guards can distinguish skipped-on-purpose from forgotten.

## 8. Self-validation

- [ ] Yearly stats were checked for every analyzed alpha
- [ ] Risk-neutralized and investability metrics were compared when available
- [ ] Repair targets a specific layer
- [ ] Simplification plan marks every non-source component as keep/downweight/remove/needs_control
- [ ] Market regime explanation is tied to observed years
- [ ] `trade_when` / threshold alphas were audited against ungated parent or negative-control evidence before repair
- [ ] Robust/sub-universe/investability failures were checked for a plausible custom cohort axis across all regions
- [ ] EUR/GLB attribution includes coverage/cohort/canonical-crowding diagnosis when applicable
- [ ] **Per-PROMISING coverage**: count `attribution.generated` events for this batch matches the count of `gate.tier { tier: "PROMISING" | "PROMISING_BEST" | ... }`, OR each missing PROMISING has a matching `attribution.skipped` with a stated reason
