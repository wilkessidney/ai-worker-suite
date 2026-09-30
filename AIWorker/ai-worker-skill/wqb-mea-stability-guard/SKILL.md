---
name: wqb-mea-stability-guard
description: "MEA alphas are fragile because the surface is small (TOP300), multi-country, sector/commodity sensitive, and prone to country, liquidity, drawdown, and investability concentration. This skill is a region-specific stability guard and regional tail-risk radar. It does not make an alpha 'safe'; it… Part of the WorldQuant BRAIN auto-mining workflow (MEA-only S1 macro refresh, S5.5 regional tail-risk guard, and pre-property S7.6 overlay in workflow/auto-mining.md)."
---

# Skill: wqb-mea-stability-guard

**Consumers**: Claude Code / GitHub Copilot / Codex / generic assistants
**Stage**: MEA-only S1 macro refresh, S5.5 regional tail-risk guard, and pre-property S7.6 overlay in `workflow/auto-mining.md`
**Budget cost**: 0 default; optional settings/structure confirmation costs exactly 4 child sims per `create_multi_simulation` call

> **MCP output shapes** — slimmed (`reference/mcp-output-shapes.md`). `investabilityConstrained.sharpe` → `metrics.investability_sharpe` (now always present in `metrics` when the platform reports it; "missing" means it's genuinely absent). `is.<metric>` → `metrics.<metric>`; `is.checks[]` → `checks.fail/.warning/.pass/.pending`; `get_alpha_pnl` downsampled (≤~160 pts).

## 1. Purpose

MEA alphas are fragile because the surface is small (`TOP300`), multi-country, sector/commodity sensitive, and prone to country, liquidity, drawdown, and investability concentration. This skill is a region-specific stability guard and regional tail-risk radar. It does not make an alpha "safe"; it blocks MEA candidates whose apparent IS quality is likely a market/regime/coverage artifact or whose current regional tail-risk ranking makes the alpha hard to hedge or exit.

Use this skill whenever `region == "MEA"` before robustness/property decisions. A MEA alpha is not property-eligible until this guard emits `mea_stability.checked` with `decision: PASS` and the regional tail-risk state is not `HALT`.

Here "blow up" means region-level tail risk, not just weak backtest metrics:

- sudden signal reversal or IC collapse;
- hedge failure from country/sector/currency/oil beta;
- trading costs overwhelming expected edge;
- inability to exit normally because of policy, liquidity, foreign-access, shorting/borrow, or geopolitical gap risk;
- crowding-driven alpha decay or production-correlation shock.

## 2. Inputs

```yaml
region: "MEA"
universe: "TOP300"
delay: 1
candidate:
  alpha_id: str | null
  expression: str
  settings: dict
  metrics: dict | null
  is_checks: list | null
  hypothesis:
    dataset_id: str
    category: str
    fields: list[str]
    expected_logic: str
    market_regime_hypothesis: str | null
macro_context:
  as_of: date | null
  sources_checked: list[str]
  middle_east_conflict_level: low|medium|high|unknown
  oil_price_pressure: low|medium|high|unknown
  inflation_pressure: low|medium|high|unknown
  usd_liquidity_pressure: low|medium|high|unknown
  em_risk_sentiment: low|medium|high|unknown
  market_access_restriction_risk: low|medium|high|unknown
stage: "pre_dispatch|post_gate|pre_property"
submit_policy:
  manual_submit_corr_max: 0.70
  no_submit: bool
available_sibling_tests:
  settings_variants: list
  structural_variants: list
session_state:
  budget_remaining: int
```

## 3. Outputs

```yaml
mea_stability_decision:
  alpha_id: str | null
  decision: PASS | CONDITIONAL_REVIEW | FAIL
  property_eligible: bool
  reasons: list[str]
  required_next_tests: list[str]
  market_lock:
    neutralization_ok: bool
    long_short_ok: bool
    country_or_sector_artifact_risk: low|medium|high
  temporal_lock:
    min_yearly_sharpe: float | null
    stress_year_failures: list[int]
    recent_4y_avg_sharpe: float | null
    recent_4y_slope: float | null
  investability_lock:
    raw_sharpe: float | null
    investability_sharpe: float | null
    investability_gap: float | null
    drawdown: float | null
  perturbation_lock:
    primary_setting: dict
    alternate_setting_evidence: list
    sign_preserved: bool | null
  regional_tail_risk:
    as_of: date
    score_0_100: float
    state: NORMAL | ELEVATED | HIGH | HALT
    ranking_bucket: int
    components:
      geopolitical_gap: float
      oil_terms_of_trade: float
      inflation_usd_liquidity: float
      tradability_exit: float
      hedge_failure: float
      crowding_decay: float
    top_drivers: list[str]
    required_positioning_response: list[str]
  event: "mea_stability.checked"
```

## 4. MCP tools used

| Tool | When |
|---|---|
| `get_alpha_details` | post-gate/pre-property if current details are stale |
| `get_alpha_yearly_stats` | pre-property, always |
| `get_alpha_pnl` | pre-property in conservative/manual-review mode |
| `create_multi_simulation` | optional settings or structural confirmation only; exactly 4 children; never short batches |

External/context tools:

- Use `scripts/external/consult.py` or the client web/forum tools when available to refresh macro/geopolitical context. Prefer official sources: IMF GFSR/WEO, central-bank/regulator notes, exchange/market-access documentation, and current market-regime notes.
- Emit `external.consulted` with `budget_charged: 0` for each refresh.
- If live external lookup is unavailable or stale by more than 7 calendar days during an MEA run, set `regional_tail_risk.state = HIGH` at minimum and require manual review before properties.

Never call `check_correlation`, `set_alpha_properties`, `submit_alpha`, or `create_simulation`.

## 5. MEA market assumptions

Read `reference/MEA-region-notes.md` before applying this guard.

Hard assumptions:

- MEA uses `TOP300`, so breadth is limited. Sub-universe/investability checks are more informative than headline Sharpe.
- MEA is multi-country. `COUNTRY` and `SECTOR` are stabilizing neutralizations; `NONE` is high-risk unless long/short balance and investability are strong.
- A high-Fitness `NONE` alpha with `shortCount == 0`, extreme long/short imbalance, high drawdown, or weak investability is not stable.
- Oil/commodity, rates, USD liquidity, and geopolitical regimes can dominate returns. Stress-year behavior matters.
- One-field MEA alphas are allowed when requested by the user, but they need stricter stability evidence because there is no cross-source confirmation.
- Current macro shocks can override alpha-level evidence. During active Middle East conflict / oil / inflation / USD liquidity stress, the guard must rank region-level blow-up risk before allowing properties.

## 6. Regional Tail-Risk Scorecard

Run this scorecard at S1 for the MEA session and refresh before property handoff if the context is older than 7 days or if a new high-impact event is known.

Score each component, then sum to `score_0_100`:

| Component | Max | What to measure |
|---|---:|---|
| `geopolitical_gap` | 20 | Middle East conflict escalation, sanctions, exchange closures, policy surprise, overnight gap risk |
| `oil_terms_of_trade` | 15 | oil/gas price shock, volatility, exporter/importer split, petro-linked sector concentration |
| `inflation_usd_liquidity` | 15 | inflation expectations, US yields, dollar strength, EM carry unwind, funding conditions |
| `tradability_exit` | 20 | shorting/borrow limits, foreign ownership/access restrictions, local liquidity, turnover/cost, exit capacity |
| `hedge_failure` | 15 | country/sector/currency/oil beta not neutralized; weak hedge under `NONE`; stress-year sign flips |
| `crowding_decay` | 15 | production/self correlation, expression-family crowding, same-field saturation, recent IC/Sharpe decay |

State mapping:

- `NORMAL`: score `< 35`. Normal MEA guard still applies.
- `ELEVATED`: `35 <= score < 55`. Require `COUNTRY`/`SECTOR` default, recent-year evidence, and investability gap `<= 0.25`.
- `HIGH`: `55 <= score < 75`. No `NONE` property handoff. Require alternate neutralization evidence, PnL concentration pass, long/short ratio `>= 0.65`, and explicit exit/liquidity rationale.
- `HALT`: score `>= 75` or any hard trigger below. Do not set properties for new MEA alphas; keep only watchlist/repair research.

Hard `HALT` triggers:

- credible current evidence of exchange closure, foreign-access restriction, capital-control shock, shorting/borrow freeze, or broad local liquidity seizure;
- active geopolitical escalation with large overnight gaps in local or oil-linked assets and no reliable exit path;
- strategy depends on shorting/hedging that is unavailable or unreliable on the target MEA venue;
- alpha's positive PnL is dominated by a few geopolitical/oil shock days and alternate neutralization fails.

The regional score is a ranking tool. It does not replace alpha-level gates; it can only tighten them.

## 7. Steps

### Phase A - Pre-dispatch MEA design lock

Apply before S4 when generating MEA expressions:

1. Require a market-aware hypothesis:
   - which country/sector/commodity/rate exposure could falsely create the signal;
   - why the chosen neutralization should preserve the intended source;
   - what opposite or alternate setting would refute the idea.
2. Default settings:
   - For fundamental/model/analyst/earnings: prefer `COUNTRY` or `SECTOR`.
   - `NONE` is allowed only as an explicit ablation or when the expression is naturally balanced after cross-sectional standardization.
3. Reject pre-dispatch:
   - `trade_when` or hard event gates unless a separate source-proof parent already passed;
   - raw unstandardized level expressions under `NONE`;
   - expressions expected to become long-only/short-only;
   - expressions with no stress/regime risk statement.
4. Emit or attach `mea_stability.plan` to the hypothesis:

```yaml
mea_stability_plan:
  primary_neutralization: COUNTRY|SECTOR|INDUSTRY|SUBINDUSTRY|NONE
  alternate_neutralization_to_test: COUNTRY|SECTOR|NONE|null
  expected_false_positive: country_beta|sector_beta|commodity_cycle|liquidity|valuation_regime|unknown
  stability_negative_control: str
  regional_tail_risk_snapshot:
    score_0_100: float
    state: NORMAL|ELEVATED|HIGH|HALT
    top_drivers: list[str]
```

### Phase B - Regional macro/tradability/crowding lock

Apply before evaluating alpha-level stability.

1. Refresh or load macro context:
   - official IMF GFSR/WEO or equivalent macro-financial source;
   - current oil/energy and USD/rates/liquidity regime;
   - market-access and shorting/borrow constraints if documented;
   - recent MEA session memory for same dataset/field/expression family crowding and decay.
2. Compute the Regional Tail-Risk Scorecard.
3. Hard fail property eligibility when `state = HALT`.
4. For `state = HIGH`, tighten alpha gates:
   - no `NONE` property handoff;
   - long/short ratio must be `>= 0.65`;
   - investability gap must be `<= 0.20`;
   - top 3 positive PnL days must contribute `<= 0.30`;
   - at least one alternate neutralization must preserve sign and pass platform floor.
5. For `state = ELEVATED`, require an explicit exit/tradability rationale and prohibit one-field MEA properties unless alternate setting or negative-control evidence exists.

### Phase C - Post-gate MEA sanity lock

Apply after S5 for every MEA `SUBMITTABLE_PENDING`, `PROMISING`, and best-in-family near miss.

Hard fail:

- Any failed RA check except PENDING correlation checks.
- `LOW_SUB_UNIVERSE_SHARPE` fail or `CONCENTRATED_WEIGHT` fail.
- `turnover < 0.01` or `turnover > 0.70`.
- `longCount == 0` or `shortCount == 0`.
- `min(longCount, shortCount) / max(longCount, shortCount) < 0.45`.
- `drawdown > 0.20` unless yearly and PnL analysis prove a documented regime alpha.
- `metrics.investability_sharpe` missing for a property candidate.
- `raw_sharpe - investability_sharpe > 0.35`.

Conditional review:

- `0.35 >= investability_gap > 0.20`.
- `0.45 <= long_short_ratio < 0.65`.
- `0.15 < drawdown <= 0.20`.
- Alpha works only under `NONE` and no alternate setting has been tested.
- One-field alpha with no sibling negative control.

### Phase D - Temporal and stress-regime lock

Apply before `set_alpha_properties` eligibility.

1. Call `get_alpha_yearly_stats`.
2. Compute yearly Sharpe list, `min_yearly_sharpe`, full-window slope, latest four-year average, latest four-year slope.
3. Mark MEA stress years when available:
   - 2015: oil/commodity drawdown regime.
   - 2018: EM/USD/rates stress.
   - 2020: COVID plus oil shock.
   - 2022: inflation/rates/commodity repricing.
4. Hard fail:
   - `min_yearly_sharpe < -0.20`.
   - two or more stress years have Sharpe `< 0`.
   - `recent_4y_avg_sharpe < 0.60`.
   - `recent_4y_slope < -0.25`.
5. Conditional review:
   - exactly one stress year Sharpe `< 0`;
   - `0.60 <= recent_4y_avg_sharpe < 0.80`;
   - `-0.25 <= recent_4y_slope < -0.10`.

### Phase E - PnL concentration and crash lock

Apply before property eligibility in conservative mode.

1. Call `get_alpha_pnl`.
2. Compute:
   - fraction of total positive PnL from top 1, top 3, and top 5 positive days;
   - max drawdown duration in trading days;
   - rolling 252-day Sharpe minimum.
3. Hard fail:
   - top 3 positive days contribute `> 0.45` of total positive PnL;
   - max drawdown duration `> 160` trading days;
   - rolling 252-day Sharpe minimum `< -0.50`.
4. Conditional review:
   - top 3 positive days contribute `0.30-0.45`;
   - max drawdown duration `100-160` trading days.

### Phase F - Settings perturbation lock

MEA property candidates need evidence that the alpha is not only a settings artifact.

Use already-simulated siblings first. If missing and budget allows, run confirmation batches through `create_multi_simulation`.

Important platform constraint: one `create_multi_simulation` call has one shared settings block. Do not put different neutralizations inside one payload. For each alternate neutralization, create a separate exact-4 child payload under that shared setting by combining the target expression with non-duplicate siblings, negative controls, or materially close structural variants. If fewer than 4 children are available for an alternate setting, defer the test until the exact-4 set exists; never fall back to `create_simulation`.

Examples:

- If primary is `NONE`, test `SECTOR` and `COUNTRY` in separate exact-4 shared-setting payloads when 4 children exist.
- If primary is `SECTOR`, test `COUNTRY` and `INDUSTRY` in separate exact-4 shared-setting payloads when 4 children exist.
- If primary is `COUNTRY`, test `SECTOR` in an exact-4 shared-setting payload when 4 children exist.

Pass:

- Primary alpha passes the user headline gate.
- At least one alternate setting preserves sign and passes platform floor: Sharpe `>= 1.25`, Fitness `>= 0.70`, no failed sub-universe or concentration checks.

Fail:

- Every alternate setting collapses or flips sign.
- Only `NONE` works and `NONE` also has long/short imbalance, high drawdown, or investability gap.

Conditional review:

- Alternate setting is directionally positive but below platform floor.

### Phase G - Decision

`PASS`:

- Regional tail-risk state is not `HALT`.
- No hard fail in Phases B-F.
- At most one conditional review item, and it is explained by the market hypothesis.
- Correlation locks are not checked here, but the alpha must still satisfy ordered self-corr then prod-corr in the normal gate.

`CONDITIONAL_REVIEW`:

- No hard fail, but two or more conditional items remain.
- Not property-eligible. Keep as manual watchlist or feed S6.5/S7.

`FAIL`:

- Any hard fail.
- Regional tail-risk state is `HALT`.
- Not property-eligible. Do not set properties.

## 8. Events emitted

- `mea_stability.plan { dataset_id, expression_fingerprint, primary_neutralization, alternate_neutralization_to_test, expected_false_positive, regional_tail_risk_snapshot }`
- `mea_stability.checked { alpha_id, decision, property_eligible, reasons, market_lock, temporal_lock, investability_lock, perturbation_lock, regional_tail_risk }`

## 9. Constraints

- MEA `PASS` is required before `set_alpha_properties`.
- MEA regional tail-risk `HALT` blocks new property setting even when alpha-level metrics pass.
- Does not submit.
- Does not set properties.
- Does not call correlation tools.
- Does not use `create_simulation`.
- Optional perturbation sims must use exact-4 `create_multi_simulation` batches.
- Do not use `trade_when` as a stability patch. If a regime gate is needed, treat it as a research hypothesis requiring separate source proof and negative controls.

## 10. Self-validation

- [ ] `reference/MEA-region-notes.md` was read.
- [ ] Current MEA regional tail-risk score was computed or marked stale with a conservative state.
- [ ] `mea_stability.plan` exists before MEA dispatch or a reason is recorded.
- [ ] Every MEA property candidate has `mea_stability.checked`.
- [ ] `decision=PASS` only when regional tail-risk, long/short balance, drawdown, investability, yearly, stress-year, PnL concentration, tradability/exit, crowding/decay, and settings evidence are acceptable.
- [ ] No `set_alpha_properties` or `submit_alpha` is called by this skill.
