---
name: wqb-alpha-repair
description: "For a single PROMISING alpha + its inferred failure_category, synthesize exactly 4 repair variants via the strategies in reference/failure-taxonomy.md, dispatch them in one create_multi_simulation call (server-side handles concurrency), re-gate, and return whether any variant reached… Part of the WorldQuant BRAIN auto-mining workflow (S7 of workflow/auto-mining.md)."
---

# Skill: wqb-alpha-repair

**Consumers**: Claude Code · GitHub Copilot · Codex · generic assistants
**Stage**: S7 of `workflow/auto-mining.md`
**Budget cost**: ≥ 1 unit per invocation; default 4 variants (1 per child). Smaller batches (1–3 children) require an explicit `dispatch_size_reason` per `workflow/auto-mining.md §0.11`.

## 1. Purpose

For a single PROMISING alpha + its inferred `failure_category`, synthesize exactly 4 repair variants via the strategies in `reference/failure-taxonomy.md`, dispatch them in **one** `create_multi_simulation` call (server-side handles concurrency), re-gate, and return whether any variant reached SUBMITTABLE_PENDING.

## 2. Inputs

```yaml
promising_alpha:
  alpha_id: str
  fingerprint: str
  hypothesis: <original 14-key YAML>
  expression: str
  failure_category: <one of 11>
  metrics: dict
attribution_report: <output of wqb-attribution-analyst> | null
region: "USA"   # binds memory/{region}/ when checking variants against fingerprints + forbidden
session_state: ...  # budget, etc
taxonomy: <from reference/failure-taxonomy.md>
memory_snapshot: ...  # for fingerprint + forbidden checks on variants
```

## 3. Outputs

```yaml
attempts: list[dict]
  - variant_id: r1
    expression: str
    fingerprint: str
    tier_after_gate: SUBMITTABLE_PENDING | PROMISING | REJECT
    metrics: dict
    outcome: "succeeded" | "failed" | "dispatch_error"
  - variant_id: r2
    ...
  - variant_id: r3
    ...
  - variant_id: r4
    ...
budget_consumed: int
improved: bool   # true if any variant upgraded to SUBMITTABLE_PENDING or higher
best_variant_id: str | null
```

## 4. MCP tools used

- `create_multi_simulation` (x1 per invocation; carries exactly 4 child expressions plus shared settings)
- `lookINTO_SimError_message` (if any child fails)
- `get_alpha_details` (per successful child)
- `check_correlation` (via `wqb-quality-gate` re-entry on variants)

## 5. Steps

### Step 1. Lookup failure strategies

Read `reference/failure-taxonomy.md` for the given `failure_category`; collect top-4 repair operations (e.g. for `low_margin`: `bump_decay_tier`, `add_group_neutralize`, plus two compatible controls or nearby variants).

If `attribution_report` is present, it overrides generic taxonomy priority. Choose repair ops by `root_cause_layer`:

| root_cause_layer | Primary repair |
|---|---|
| `raw_field` | abandon/swap raw field; do not wrap |
| `l0_construction` | rebuild two-field formula: spread↔ratio↔surprise↔interaction |
| `l1_temporal` | change temporal extractor/window/backfill, keep L0 fixed |
| `l2_bucket` | redesign bucket axis or remove L2 |
| `settings_neutralization` | test alternate shared neutralization/settings |
| `coverage_axis` | choose date vs instrument coverage repair; do not add generic wrapper |
| `liquidity` | add liquidity/size bucket or improve investability; avoid pure wrapper |
| `canonical_crowding` | rebuild source pair or meaningful cohort axis; avoid wrapper-only decrowding |
| `regime` | add explicit regime/event gate or mark as non-submit seed |
| `unknown` | use taxonomy fallback only after one ablation attempt |

Do not repair by adding wrappers to a layer that attribution showed was irrelevant. In particular, do not add `trade_when`, hard thresholds, or event gates as a generic low-Sharpe/low-Fitness fix. Gate-style repairs are allowed only when attribution shows (a) an ungated source edge exists, (b) the gate has economic causality, and (c) negative-control or nearby-threshold tests are planned.

Before any repair synthesis, enforce `reference/two-field-construction-contract.md`
`parent_basic_strength`. If the parent lacks one return signal plus
`fitness >= 0.25`, robustness/sub-universe PASS, or has a hard core RA `FAIL`,
do not spend a repair batch. At this parent-screening step, treat `WARNING` on
a name in `RA_CHECK_NAMES` (`reference/submission-gates.md` §9) as a soft
indicator of weakness — it is allowed for repair candidacy but the same
`WARNING` will count as a failed RA at S5/S7.5 and must be cleared before
properties or submission. `WARNING` on out-of-list names (e.g. `MATCHES_THEMES`)
is diagnostic at every stage. Emit `repair.skipped { reason:
"parent_basic_strength_failed" }` and hand the case back to S2.5/S3 for source
reconstruction. A strong negative parent must first run a reverse/sign-control
exact-4 batch; wrapper repair is not a substitute for the control.

**Parameter-aware op list** (added 2026-04-28; see `reference/operators-catalog.md §Parameter-aware deep-use patterns` for full signatures):

| op_name | new_expr generation | Key constraint |
|---|---|---|
| `add_hump_0.01` | `hump({expr}, hump=0.01)` | **First-pick for `low_fitness`, `webdatascope_low_robust_univ_sharpe`, `webdatascope_low_sub_univ_sharpe`**. Verified 2026-04-28 to lift sharpe / fitness / margin / robust-univ simultaneously. |
| `hump_param_sweep` | dispatch 4 variants, e.g. `hump=0.005`, `hump=0.01`, `hump=0.02`, and one non-duplicate window/decay control | When `add_hump_0.01` close-but-not-quite. `hump=0.05` over-smooths — DON'T sweep that high. |
| `add_winsorize_std4` | `winsorize({expr}, std=4)` | **MUST use keyword `std=`**. Positional `winsorize({expr}, 4)` triggers `Invalid number of inputs: 2` and cancels the entire multi-sim batch. For `tail_risk_high`. |
| `add_bucket_group_neutralize` | `group_neutralize({expr}, bucket(rank(<meaningful_field>), range='<match_data>'))` | Stage-2 custom group. `meaningful_field` ∈ {cap, split, sentiment, indicator}. Range must match field distribution. **Don't combine with same-axis settings.neutralization** (e.g. industry+INDUSTRY = signal-killing). |
| `add_country_crossed_cohort` | use `group_cartesian_product(country, <semantic_axis>)` as a group/backfill/residual axis | EUR/GLB only when the field story supports country x market/sector/industry/subindustry peer comparability. Not a mandatory wrapper. |
| `coverage_axis_backfill` | `ts_backfill` for date gaps, `group_backfill` for instrument gaps | Requires S6.5 coverage-axis diagnosis. Do not backfill coverage proxies or news/sentiment fields blindly. |
| `add_quantile_cauchy` | `quantile({expr}, driver="cauchy", sigma=1.0)` | For fat-tailed alpha distributions. `driver` ∈ {gaussian, cauchy, uniform}. |
| `add_vector_neut` | `vector_neut({expr}, <factor_alpha>)` | For `high_prod_corr`. Cross-sectional residualization; complementary to `add_residual_strip_sector`. |
| `add_pasteurize_purify` | `pasteurize(purify({expr}))` | Preventive NaN/INF cleanup. For checks involving INF/NaN. |

### Step 2. Synthesize variants

For each of 4 repair ops:
- Apply the transformation to the original expression per taxonomy docs
- Keep task_type & paradigm identical (repair, not redesign)
- Keep the L0 expression fixed only when attribution says the edge originates at L1/L2/settings. If attribution says L0 is wrong, change L0 and preserve only raw field family.
- For high correlation failures, wrappers are not enough: at least one variant must change L0 construction or custom bucket axis.
- Preserve or deliberately change `two_field_construction_mode`; do not produce
  four wrapper-only children in the same mode. When a source rebuild is allowed,
  prefer changing among `math_relation`, `pairwise_operator`,
  `custom_group_axis`, and `main_aux_complement` instead of adding another
  surface wrapper.
- For EUR/GLB `coverage_axis` failures, at least one variant must test the diagnosed coverage route and at least one must be a control that changes source breadth or cohort axis rather than only adding smoothing.
- For `canonical_crowding`, do not try four wrappers. Change the source pair, the source role, or a meaningful country/liquidity/volatility/size cohort axis.
- Recompute fingerprint
- Self-check (same as `wqb-hypothesis-designer` Step 3): no ghost ops, no forbidden regex, no fingerprint collision (against batch + memory)
- If collision: try the next repair op from taxonomy; if ALL repair ops collide, emit `repair.skipped { alpha_id, reason: "all_variants_collide" }` and return `improved: false`
- If a proposed variant introduces or tightens `trade_when` / hard thresholds, require attribution_report.return_source_attribution.ungated_parent_evidence in `{positive}` and a written negative-control/nearby-threshold test plan; otherwise emit `repair.step { rejected_reason: "surface_metric_gate" }` and choose a source-layer repair instead.

### Step 2.5. Per-parent repair-round cap (Cluster 2 / Iron Law §16b, 2026-05-09)

Maintain a session-local counter `repair_rounds_per_parent[parent_alpha_id]` initialized to 0 at session start. Before reserving budget:

```python
parent = parent_alpha_id  # the alpha being repaired this round
session_state.repair_rounds_per_parent.setdefault(parent, 0)
session_state.repair_rounds_per_parent[parent] += 1
if session_state.repair_rounds_per_parent[parent] > 1:
    emit repair.skipped {
        parent_alpha_id: parent,
        reason: "iron_law_16b_repair_round_cap",
        round: session_state.repair_rounds_per_parent[parent],
        cap: 1,
    }
    return improved: false
```

Counter is keyed by `parent_alpha_id`, not `parent_fingerprint`, so cross-batch retries with different fingerprints still hit the cap. Wrapper-only second-round repair on a parent that already had its diagnosed layer touched is forbidden — instead, downgrade the parent to REJECT, log to memory, and let S2.5/S3 rebuild the L0 source. The continuation gate observes `repair.skipped { reason: "iron_law_16b_repair_round_cap" }` events to detect chronic violators across sessions.

`pre_final_workflow_guard.py --require-attribution-before-repair` enforces the complement: every `repair.attempted` must follow `attribution.generated` for the same parent (Cluster 2 / RC2 fuse).

### Step 3. Budget check

Default repair payload size is 4 variants. If `session_state.budget_remaining >= len(variants)` (where `len(variants) ∈ {1,2,3,4}`) → proceed; else emit `repair.skipped { reason: "budget_below_dispatch_size" }` and return `improved: false`. Per `workflow/auto-mining.md §0.11`, repair (S7) accepts ≥ 1 child + same shared settings + explicit `dispatch_size_reason` payload field when fewer add genuine research value.

### Step 4. Dispatch (one `create_multi_simulation` call)

Build the `alpha_expressions` list (1–4 items, default 4) and dispatch with one `create_multi_simulation` call using shared settings inherited from the parent alpha unless the repair op explicitly changes settings for all variants. If fewer than 4 variants survive fingerprint/forbidden checks, prefer filling to 4 with non-duplicate controls, ablations, or nearby parameter variants; otherwise dispatch the survivors with `dispatch_size_reason` (e.g. `"all_other_variants_fingerprint_collide"`, `"single_targeted_repair_with_evidence"`). Single-sim `create_simulation` is still forbidden. Reuse the same multi-sim result handling as `wqb-batch-runner` Phase B. Emit `sim.dispatched` per variant pre-call, then `sim.dispatched_done` per child after the multi response is received, then `sim.poll` if exposed by the client and `sim.succeeded` / `sim.failed` / `sim.timeout` per child as they resolve. Decrement budget by `len(variants)` once, before the multi call.

### Step 5. Re-gate

For each successfully-simulated variant, run `wqb-quality-gate`'s Phase A → Phase D inline (don't call the full skill, but use its logic). Output each variant's post-gate tier.

### Step 6. Decide

- Any variant `tier == SUBMITTABLE_PENDING` → `improved: true`, `best_variant_id` = that id
- Else → `improved: false`
- Emit `repair.attempted { parent_alpha_id, variants: [...], improved, best }`
- Emit `repair.succeeded` or `repair.failed`

## 6. Events emitted

`repair.attempted`, `repair.succeeded | repair.failed`, plus all `sim.*` and `batch.budget_checked` events inherited from batch-runner logic.

### Trace events emitted (Trace 2.0 schema — see reference/trace-schema-v2.md)

**(a) Emit `repair.step` per mutation rejected pre-dispatch.** Step 2 currently has a "If collision: try the next repair op" branch — for *each* such pre-dispatch rejection, emit one `repair.step` so `wqb-self-diagnostic` can see which mutation ops are perpetually blocked vs which dispatch but fail re-gate. Schema: `reference/trace-schema-v2.md §3.4`.

```json
{
  "kind": "repair.step",
  "payload": {
    "parent_alpha_id": "<alpha_id>",
    "op_tried": "add_zscore_wrapper",
    "rejected_reason": "fingerprint_collision",
    "fingerprint_attempted": "ff15c397909b47cf"
  }
}
```

`rejected_reason` ∈ `{ghost_op, forbidden_pattern, fingerprint_collision, all_collide, depth_exceeded, field_count_exceeded}`.

**(b) (Phase 3+ only) Extend `repair.attempted` with `external_evidence_used[]`** — when Phase 3's `consult.py` is wired and a forum/web lookup informed the repair-op selection, attach evidence references:

```json
{
  "external_evidence_used": [
    {"source": "forum", "snippet_hash": "abc123", "url": "https://..."}
  ]
}
```

Default `[]` if no consultation occurred. The `external.consulted` event itself is emitted separately by `scripts/external/consult.py`.

### v0.4 Phase 3 — Forum lookup before repair-op selection (additive)

Before Step 1 (lookup failure strategies in `reference/failure-taxonomy.md`), if the failure_category is `low_sharpe` (the dominant failure per historical attribution — 70% of all rejects), AND the agent's confidence in the taxonomy mapping is low (e.g. metrics deviate significantly from the category's typical signature), augment with a forum lookup:

```bash
python3 scripts/external/consult.py check --source forum \
  --query "alpha low_sharpe repair pattern" --stage S7
```

If miss:
1. `search_forum_posts(query="<failure_category> alpha repair")` — top 3.
2. Optionally use the client's web-search tool for `alpha <failure_category> fix Sharpe` — top 3.
3. Distill into a 1-paragraph hint with concrete repair-op names if mentioned (e.g., "Add ts_decay_linear with decay=15", "Try purify wrapper").
4. Use the hint to bias which repair op gets the `r1` slot (priority over taxonomy default if forum is more specific).
5. Record:
   ```bash
   python3 scripts/external/consult.py record --source forum \
     --query "<failure_category> alpha repair" --stage S7 \
     --hits <N> --distilled-content-file /tmp/d.md --session-id <sid>
   ```
6. Attach to `repair.attempted` payload:
   ```json
   "external_evidence_used": [{"source": "forum", "snippet_hash": "<h>", "url": "..."}]
   ```

**Frequency limit**: at most 1 forum lookup per repair invocation. If the LLM judges the taxonomy hint sufficient, skip the lookup.

**Budget impact**: 0.

## 7. Constraints

- **Default 4 variants; smaller batches require `dispatch_size_reason`** per `workflow/auto-mining.md §0.11`. Single-sim `create_simulation` and chain-repair remain forbidden.
- **Same task_type & paradigm** as parent (repair preserves research topic).
- **Do NOT re-enter `wqb-alpha-repair` on a repaired variant**. If variant ends up PROMISING, it goes back to S6 outer loop OR gets skipped (same-session repair budget already spent).
- **Do NOT call `submit_alpha`**. Even a promoted variant goes to S6 robustness first.
- Repair must name `target_layer`; if no target layer is known, run `wqb-attribution-analyst` first unless budget/session constraints prevent it.
- Do not produce more parameter sweeps until the failing economic/statistical layer has been identified.
- Do not use `trade_when` / threshold gates as metric cosmetics; gate repairs must be source-backed and accompanied by negative controls.
- For EUR/GLB, coverage and country/cohort repairs must cite the attribution evidence. If the evidence is weak, emit a diagnostic/control variant rather than pretending the group choice is proven.

## 8. Self-validation

- [ ] `repair.attempted` event written once per invocation
- [ ] `budget_consumed == len(variants)` reflected in records (default 4; smaller dispatches must have `dispatch_size_reason`)
- [ ] Each variant has a corresponding `sim.succeeded | sim.failed` + `gate.tier` event
- [ ] If `improved: true`, the best variant's `gate.tier` is `SUBMITTABLE_PENDING`
