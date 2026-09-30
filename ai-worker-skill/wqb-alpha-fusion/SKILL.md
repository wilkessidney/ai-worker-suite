---
name: wqb-alpha-fusion
description: "Combine two validated L1 parents into an enhanced L1 alpha that improves sharpe / fitness / 2y_sharpe over the best parent, by exploiting low cross-correlation. This is the layer that pushes near-gate parents past the strict gate. Part of the WorldQuant BRAIN auto-mining workflow (S4.5 of workflow/auto-mining.md (new stage, between S5 first-pass and S6 robustness))."
---

# Skill: wqb-alpha-fusion

**Consumers**: Claude Code · GitHub Copilot · Codex · generic assistants
**Stage**: S4.5 of `workflow/auto-mining.md` (new stage, between S5 first-pass and S6 robustness)
**Budget cost**: 4 child sims per fusion batch (one shared `create_multi_simulation` call)
**Reference contract**: `reference/two-field-deep-construction-2026-05-08.md` §4 (Alpha Fusion).

---

## 1. Purpose

Combine **two validated L1 parents** into an enhanced L1 alpha that improves sharpe / fitness / 2y_sharpe over the best parent, by exploiting low cross-correlation. This is the layer that pushes near-gate parents past the strict gate.

This skill does NOT generate new fields or new L0 constructions. It only fuses *existing* L1 parents that already passed `parent_basic_strength`.

---

## 2. Inputs (YAML)

```yaml
session_id: str
region: USA | IND | EUR
universe: TOP3000 | TOP500 | TOP2500
delay: 1
campaign_dataset_ids: [str]   # one or more datasets where parents originated; all must be in same pyramid for property eligibility
parents:
  - alpha_id: str
    expression: str
    settings:
      neutralization: str
      decay: int
      truncation: float
    metrics:
      sharpe: float
      fitness: float
      two_year_sharpe: float
      sub_universe_sharpe: float
      margin_bp: float
      prod_corr_max: null | float   # if measured
    construction_mode: math_relation | pairwise_operator | custom_group_axis | main_aux_complement
    raw_fields: [str]
    role_in_fusion: main | auxiliary | confidence | risk_aux | reverse_control | unspecified
target_metric_priority: sharpe | fitness | two_year_sharpe   # which metric to maximize lift on
budget_units: 4   # exactly 4 fusion children per call
```

## 3. Outputs (YAML)

```yaml
fusion_batch:
  - fusion_id: f1..f4
    fusion_family: F1_rank_sum | F2_confidence_weighted | F3_vector_neut | F4_ts_pairwise
    expression: str   # complete Fast Expression
    parents_used: [parent_alpha_id_a, parent_alpha_id_b]
    fusion_mechanism: str
    expected_lift_basis: str   # which parent strength + which fusion family rationale
shared_settings:
  region: str
  universe: str
  delay: int
  decay: int   # adopt strongest-parent's decay; use majority if equal
  neutralization: str   # adopt strongest-parent's neut; if mismatch and no consensus, use INDUSTRY
  truncation: 0.08
  pasteurization: ON
  nan_handling: OFF
  unit_handling: VERIFY
```

Plus events:
- `fusion.eligibility_checked` (1 per pair)
- `fusion.batch_dispatched` (1 per batch)
- `fusion.gate.tier` (1 per fusion child after S5 re-gate)

---

## 4. MCP tools used

- `mcp__wqb-mcp__check_self_correlation(parent_a)` — to estimate cross-correlation between parents (parents are themselves OS alphas in the local cache, so self_corr against the local pool gives an indirect signal).
- `mcp__wqb-mcp__create_multi_simulation(...)` — exactly 4 fusion children, server-side concurrency.
- `mcp__wqb-mcp__lookINTO_SimError_message(...)` — only on error.

---

## 5. Method

### Step 1 — Eligibility gate

For each candidate pair (A, B) of parents:

```yaml
eligibility:
  parent_a_strength_pass:
    sharpe: ">= 0.8"
    two_year_sharpe: ">= 1.2"
    sub_universe_sharpe: "PASS or >= 0.3"
    fitness: ">= 0.25"
    no_core_ra_fail: true
  parent_b_strength_pass: "(same)"
  cross_correlation_estimate: "< 0.5"
    method: "if both parents are saved alphas, call check_self_correlation on B with A in its OS pool; OR compare expression_overlap"
    expression_overlap_score:
      same_raw_field_set: 0.4
      same_construction_family: 0.2
      same_outer_wrapper: 0.1
      same_neutralization: 0.1
      same_decay_window: 0.1
    # if expression_overlap_score >= 0.7, treat as too similar → reject pair
  diversity:
    different_raw_field_pair_OR_different_construction_mode: true
```

If eligibility fails, emit `fusion.eligibility_failed { reason }` and skip this pair.

### Step 2 — Fusion family selection

Pick which of the 4 families (F1–F4) to instantiate based on parent characteristics:

| Pair shape | Recommended family |
|---|---|
| Two strong parents, similar sharpe, low corr | F1 (rank-sum) — symmetric combination |
| One parent has confidence/quality signal | F2 (confidence-weighted) — main × aux scaling |
| Parents share factor exposure (corr 0.3–0.5) | F3 (vector_neut) — orthogonalize and add residual |
| Parents have time-varying agreement | F4 (ts pairwise) — gate via rolling corr / regression |

Default: **emit one of each (F1, F2, F3, F4)** in a 4-child fusion batch, unless inputs preclude one (e.g., no confidence aux available → replace F2 with second F1 variant using rank-product instead of rank-sum).

### Step 3 — Construct expressions

For parents `A_expr` and `B_expr`, build:

#### F1: rank-sum (Alpha101 mega-alpha)

```text
add(rank(A_expr), rank(B_expr))
```

Variant if A is the dominant parent:
```text
add(multiply(rank(A_expr), 1.5), rank(B_expr))
```
(weighted sum; require documenting why the weight is non-equal.)

#### F2: confidence-weighted main_aux

If B is the confidence/quality signal:
```text
multiply(rank(A_expr), rank(B_expr))
```

Stronger amplification (verified empirically, signed_power 1.5–2 sweet spot):
```text
multiply(rank(A_expr), signed_power(rank(B_expr), 1.5))
```

Confidence-gated activation:
```text
if_else(greater(rank(B_expr), 0.5), rank(A_expr), 0)
```

#### F3: cross-sectional orthogonalization

Strip B from A, then add residual to A:
```text
add(rank(A_expr), rank(vector_neut(B_expr, A_expr)))
```

Pure residual (A residualized by B):
```text
vector_neut(rank(A_expr), rank(B_expr))
```

Chained two-stage neutralization (forum ZW13908):
```text
vector_neut(vector_neut(rank(A_expr), rank(B_expr)), rank(C_risk_factor))
```
(only if a third risk factor exists and is justified)

#### F4: ts-coordinated pairwise

ts_corr-gated (when A leads B, signal is reliable):
```text
multiply(rank(A_expr), ts_corr(A_expr, B_expr, 60))
```

ts-residual (A's ts-component orthogonal to B over 60d):
```text
ts_vector_neut(A_expr, B_expr, 60)
```

ts-regression residual (A's component independent of B's slope):
```text
ts_regression(A_expr, B_expr, 60, lag=0, rettype=0)
```

### Step 4 — Shared-settings selection

`create_multi_simulation` requires ONE shared settings block for all 4 children. Strategy:

```python
def select_shared_settings(parents):
    # neutralization: pick strongest parent's neut
    by_strength = sorted(parents, key=lambda p: -p.metrics.sharpe)
    neut = by_strength[0].settings.neutralization

    # decay: median of parents' decay
    decay = int(median(p.settings.decay for p in parents))
    if decay not in [4, 8, 12]:
        decay = 8  # safe default

    # truncation: 0.08 universally
    return {
        "neutralization": neut,
        "decay": decay,
        "truncation": 0.08,
        "pasteurization": "ON",
        "nan_handling": "OFF",
        "unit_handling": "VERIFY",
    }
```

If parents have wildly different optimal neuts (e.g., one prefers INDUSTRY, other STATISTICAL), prefer the strongest parent's neut and emit `fusion.settings_compromise` event.

### Step 5 — Pre-flight self-checks

Apply `reference/diversity-contract.md §5 Pre-dispatch six-lock check` (fingerprint, forbidden, ghost, budget, diversity, track) plus the fusion-specific overlays:

1. **Field count override**: each fusion child uses ≤ 6 distinct raw fields total (across parent A + parent B); count via AST walk. Two-field parents fused → 4 raw fields max.
2. **OperatorCount estimate override**: ≤ 12 (parents have 4–8 each + fusion adds 1–3).
3. **Fusion-family diversity**: 4 fusion children must use ≥ 2 distinct fusion families (overrides the 4-axis batch diversity from §1–§4 of `diversity-contract.md`).

### Step 6 — Dispatch

```python
result = mcp__wqb_mcp__create_multi_simulation(
    alpha_expressions=[f1.expression, f2.expression, f3.expression, f4.expression],
    region=region, universe=universe, delay=delay,
    decay=shared.decay,
    neutralization=shared.neutralization,
    truncation=shared.truncation,
    pasteurization=shared.pasteurization,
    nan_handling=shared.nan_handling,
    unit_handling=shared.unit_handling,
)
```

Emit `fusion.batch_dispatched { batch_id, parents, fusion_families, settings }`.

### Step 7 — Post-sim re-gate

For each fusion child, apply `wqb-quality-gate` standard tiering. Additionally compute lift vs. best parent:

```yaml
lift_vs_best_parent:
  sharpe_lift: float   # fused.sharpe - max(parent.sharpe)
  fitness_lift: float
  two_y_lift: float
  sub_univ_pass_preserved: bool
  prod_corr_no_explosion: bool   # fused.prod_corr < 0.7 if measured
fusion_verdict:
  - kept_fusion: "lift >= 0.10 sharpe AND no regression on 2Y/sub_univ"
  - kept_parent: "lift < 0.10 sharpe OR fitness regression OR prod_corr > 0.7"
  - kept_neither: "fusion underperforms parent on all metrics"
```

Emit `fusion.gate.tier` with verdict.

---

## 6. Events emitted

- `fusion.eligibility_checked` (×N pairs evaluated)
- `fusion.eligibility_failed` (×0+ rejected pairs)
- `fusion.batch_dispatched` (×1 per fusion batch)
- `fusion.settings_compromise` (×0+ when parents disagree on settings)
- `fusion.gate.tier` (×4 per batch after sim completes)

Schema additions to `reference/trace-schema-v2.md` (Phase 6 update):

```json
{
  "kind": "fusion.batch_dispatched",
  "payload": {
    "batch_id": "fusion_b1",
    "parents": [{"alpha_id": "...", "sharpe": ..., "two_y": ...}, ...],
    "fusion_families": ["F1_rank_sum", "F2_confidence_weighted", "F3_vector_neut", "F4_ts_pairwise"],
    "shared_settings": {...},
    "expected_lift_target": "sharpe"
  }
}
```

---

## 7. Constraints

- Exactly 4 fusion children per `create_multi_simulation` call (iron law 17 + 30).
- Use ≤ 2 parents per fusion child (avoid 3+ parent mega-fusion).
- Total raw fields per fusion child ≤ 6 (typically 4: 2 from each parent).
- Only fuse parents that pass `parent_basic_strength` (ref: `two-field-construction-contract.md` §4).
- No fusion if both parents are in same `(dataset_id, fingerprint, raw_fields)` cluster (same parent in disguise).
- Fusion does NOT bypass the post-S5 robustness audit (S6) or anti-overfit gate (S7.5).
- Apply news source-proof gate (workflow rule 27) if any parent originates from News dataset: parent must have sharpe ≥ 1.25, fitness ≥ 0.70, sub_univ PASS, no failed RA — otherwise fusion forbidden.
- Auto-submit (S8) for a fused alpha requires: SUBMITTABLE_CONFIRMED tier (post-S6) + property_eligible (post-S7.5) + `--no-submit` off + cross-corr to existing OS pool < 0.7 (`check_correlation`) — same locks as a regular L1 alpha.

---

## 8. Self-validation checklist

- [ ] Both parents pass `parent_basic_strength` before fusion.
- [ ] Cross-correlation estimate < 0.5 (or expression_overlap_score < 0.7).
- [ ] 4 fusion children cover ≥ 2 distinct fusion families (F1-F4).
- [ ] Shared settings select strongest-parent's neut + median decay.
- [ ] Each fusion expression has operatorCount ≤ 12 and no ghost ops.
- [ ] No fingerprint collision with prior alphas.
- [ ] Post-sim, lift vs best parent computed and `fusion_verdict` emitted.
- [ ] If any fusion child reaches `SUBMITTABLE_PENDING`, S6 robustness audit is queued.

---

## 9. Failure modes

| Failure | Diagnosis | Action |
|---|---|---|
| All 4 fusion children regress vs best parent | Parents are not as low-corr as estimated | Re-check cross-corr via platform `check_correlation`; may need to fuse more diverse pair |
| F3 (vector_neut) returns null/zero | Parents are highly aligned at cross-section → residual is noise | Skip F3; use F4 (ts-pairwise) instead |
| Sub_univ_sharpe drops in fusion | Fusion introduces factor exposure not present in either parent | Add `vector_neut` against risk factors before final wrapping |
| Prod_corr explodes (> 0.7) | Fused alpha is now too close to existing OS pool | Try the orthogonalized variant: `vector_neut(fused, ts_zscore(market_factor, 252))` |
| Operator count > 12 | Too much wrapping | Strip outer wrappers; fuse cleaner inner expressions |

---

## 10. Example invocation (production)

Empirical case from session s-20260508-a:
- Parent A = `bloz7JVM` (news94, sharpe 1.37, 2Y 2.18 PASS, fit 0.44, INDUSTRY neut decay=4)
  ```
  signed_power(ts_rank(ts_backfill(winsorize(vec_avg(nws94_v2_comp_returnafterevent) - vec_avg(nws94_v2_comp_returnbeforeevent), std=4), lookback=63), 252), 1.5)
  ```
- Parent B = `0megvlEv` (earnings2, sharpe 1.06, 2Y 1.53, fit 0.76, CROWDING neut decay=12)
  ```
  rank(days_from_last_change(ern2_earnconfcall_d1_calendar_prev)) - rank(days_from_last_change(ern2_earnconfcall_d1_calendar_next))
  ```

These come from different datasets (news94, earnings2), different pyramids (news 1.2x, earnings 1.3x), different construction modes (math_relation_cross_session, math_relation_event_spacing). Cross-correlation likely low (no shared field).

**Caveat for THIS pair**: cross-dataset alpha will lose `Single Data Set Alpha` classification. Fusion still produces a valid REGULAR alpha, but it pyramid-matches to one but not both pyramids. Alternative: fuse two parents within the SAME dataset (e.g., `bloz7JVM` + `O0bzwxEq` both in news94) → preserves single-dataset pyramid bonus.

The skill should warn when fusion crosses datasets and ask the workflow whether the user wants single-dataset bonus or cross-dataset diversification.
