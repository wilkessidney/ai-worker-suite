---
name: wqb-field-explorer
description: "Produce a ≤40-field shortlist for a given dataset, ranked by a composite score combining WebDataScope OS/IS decay prior + memory effectiveness + platform popularity + coverage. Output feeds into wqb-hypothesis-designer. Part of the WorldQuant BRAIN auto-mining workflow (S2 of workflow/auto-mining.md)."
---

# Skill: wqb-field-explorer

**Consumers**: Claude Code · GitHub Copilot · Codex · generic assistants
**Stage**: S2 of `workflow/auto-mining.md`
**Budget cost**: 0

## 1. Purpose

Produce a ≤40-field shortlist for a given dataset, ranked by a composite score combining WebDataScope OS/IS decay prior + memory effectiveness + platform popularity + coverage. Output feeds into `wqb-hypothesis-designer`.

This skill does **not** create alpha expressions. It provides the raw material for `wqb-zero-order-field-factory`, which constructs economically meaningful L0 synthetic fields before S3.

**Template-aware shortlisting (2026-07-03):** when S3 is about to transfer a validated template (template-first driver), bias the ≤40 shortlist toward fields whose semantic role matches the template's carrier `l0_economic_role` / `dataset_category` (consult `data/templates/canonical_carriers.json` for the category's representative carriers). The shortlist then supplies region-valid carrier fields to `scripts/template_transfer.py transfer(..., fields=carrier_shortlist)`, replacing the pv-primitive placeholders used only during on-platform template *validation*.

## 2. Inputs (YAML)

```yaml
dataset_id: "earnings2"
region: "USA"
universe: "TOP3000"
delay: 1
memory_snapshot:
  field_effectiveness: list   # memory/{region}/field_effectiveness.jsonl, filtered to dataset_id first
  region_category_templates: list # memory/{region}/template_effectiveness.jsonl or structural_features.jsonl, advisory only
  global_strategy_templates: list # memory/global/*.jsonl, advisory cross-region priors only
submitted_alpha_overlap:        # from `python scripts/submitted_field_overlap.py --region <R> --recent-days 90 --dataset-fields-file data/platform/<dataset>_datafields.json`
  submitted_fields: dict        # { field_id: submit_count } across the user's submitted REGULAR alphas in this region
  dataset_overlap: dict         # subset of submitted_fields that are actual fields of <dataset_id> (the ones that matter here)
  recent_submitted_fields: dict # hard-ban fields used by submitted REGULAR alphas in the rolling last 90 days
  dataset_recent_banned_fields: dict # subset of recent_submitted_fields in this dataset; these are removed before scoring
  submitted_field_pairs: list   # [[a, b, count], ...] field pairs that were submitted together
  n_submitted_codes: int
platform_snapshot:
  datafields: list            # from data/platform/<dataset>_datafields.json
priors_snapshot:
  os_is_sharpe_per_field: dict  # from data/priors/{region}_{delay}_<dataset>.json
playbook_snapshot:
  starter_priority: dict      # from reference/<dataset>-playbook.md §1 (T1/T2/T3 tags)
auto_mode: true
dataset_selection_mode: high_usage | low_usage | fixed_dataset  # high_usage is the default broad-selection mode; low_usage requires an explicit user request
dataset_randomization:
  enabled: bool
  seed_or_nonce: str
  selection_policy_path: "reference/dataset-selection-policy.md"
```

## 3. Outputs (YAML)

```yaml
shortlist:
  - field_id: ern2_earnconfcall_d1_calendar_next
    priority_tag: T1
    coverage: 0.852
    alpha_count: 521
    user_count: 237
    os_is_sharpe_ratio: 0.448
    memory_score: 0.0        # submittable / (trials+5); 0.0 on cold start
    recent_submitted_banned: false
    submitted_overlap: none  # none (count 0) | seen (count 1) | heavy (count >=2) — vs the user's submitted REGULAR alphas in this region
    submitted_overlap_count: 0
    composite_score: <float>
    semantic_role: event_gate # level | change | event_gate | persistence
    semantic_detail:
      variable_nature: slow_variable | event_variable | sparse_event | expectation_variable | behavioral_variable | unknown
      field_role: direction | scale | expectation | outcome | confidence | categorical | unknown
      role_type: standalone | context_gate | bucket_axis | source_proof_helper | unknown
      sign_convention: "higher means more bullish/bearish/unknown"
      likely_false_proxy: liquidity | coverage | reporting_frequency | size | post_event_reaction | none | unknown
count: <=40
category: "Earnings"         # from data/platform/datasets_*.json
pyramid_multiplier: 1.3
alpha_count_dataset: 2320
region_group_context:         # present when region in {EUR, GLB}
  standard_groups: ["country", "market", "sector", "industry", "subindustry"]
  high_coverage_group_fields: []
  country_cross_candidates:
    - "group_cartesian_product(country, subindustry)"
  cohort_axis_candidates:
    - axis_family: liquidity | volatility | size | coverage | confidence
      expression_hint: str
      reason: str
```

## 4. MCP tools used

None. v0.3 reads from `data/platform/<dataset>_datafields.json` (pre-cached by Phase 0). Only re-fetch if file is missing or older than 14 days.

Fallback: if missing, call `get_datafields(region, delay, universe, dataset_id=<dataset>, filter_sharpe=false)`.

## 5. Steps

0. **Universe is the input, not the output.** Universe is taken from `--region` defaults (USA→TOP3000, IND→TOP500 only, EUR→TOP2500) per `reference/<region>-region-notes.md`, **not** inferred from WebDataScope priors — `info_data.bin` is keyed by `region_delay`, so its `count` and `sharpe_ratio` aggregate across all universes (see `reference/webdatascope-priors.md` §"Universe coverage caveat"). When ≥2 universe snapshots are cached for the same region/delay (`data/platform/datasets_<region>_D<delay>_<universe>.json`), call `python scripts/dataset_universe_recommend.py --region <R> --delay <D> --dataset <id>` to compare `valueScore × log1p(alphaCount)` across universes; treat the output `dataset.universe_recommended` event as advisory only — never override an explicit user `--universe` flag, and do not auto-rotate datasets based on this signal.
1. Load `data/platform/<dataset>_datafields.json`; if missing, fall back to MCP.
2. Load `data/priors/{region}_{delay}_<dataset>.json` for OS/IS decay priors.
3. Load hierarchical memory in precedence order:
   - dataset-local rows from `memory/{region}/field_effectiveness.jsonl`, filtered to this `dataset_id`; these determine hard field boosts/penalties.
   - region/category template evidence from `memory/{region}/template_effectiveness.jsonl` if present, otherwise recent compatible `structural_features.jsonl` / `paradigm_effectiveness.jsonl` rows; use only as soft role/category priors.
   - cross-region/global templates from `memory/global/strategy_templates.jsonl` and `template_effectiveness.jsonl`; use only when semantic roles match and local dataset evidence is cold or neutral.
   Dataset-local learned-dead fields override all broader priors.
4. Load `reference/<dataset>-playbook.md` and extract T1/T2/T3 priority tags.
4b. **Load submitted-alpha field overlap (dedup-against-own-book)**. Run `python scripts/submitted_field_overlap.py --region <region> --recent-days 90 --dataset-fields-file data/platform/<dataset>_datafields.json` (0 budget, no MCP — reads `data/platform/my_submitted_<region>_regular.json`, falling back to `my_submitted.json`). Parse `dataset_recent_banned_fields` first: any field used by a submitted REGULAR alpha in the rolling last 90 days is hard-banned and must be removed before scoring. Then parse `dataset_overlap` → for each remaining shortlist candidate, set `submitted_overlap_count` (0 if absent) and `submitted_overlap` tier: `none` (count 0), `seen` (count 1), `heavy` (count ≥ 2). **Rationale**: the field-explorer used to rank by OS/IS prior + popularity + memory + coverage only — so it repeatedly surfaced the exact carrier fields the user's production book already uses, and every "best" candidate came back with high `check_self_correlation` (e.g. `earnings_chart_dl` `prob_quantile_*` already in submitted alpha `YPkXpnLA` → self-corr 0.55). If `my_submitted_<region>_regular.json` is missing or older than 7 days, refresh it first via MCP `get_user_alphas` (filtered to region + REGULAR + submitted), then re-run the script.
5. Determine dataset/field scoring mode:
   - Default `high_usage`: prefer mature/high-alphaCount/high-userCount datasets and fields as reliable, high-coverage source surfaces. Decrowd downstream through exactly two-field L0 construction and production-correlation gates rather than avoiding crowded data.
   - `low_usage`: legacy / explicit-user mode; use pyramid/distribution preference and avoid over-used surfaces unless they have strong memory or priors. **Exception (2026-06-19 user directive): even in low_usage / unlit exploration, prefer the highest-`alphaCount`/`userCount` *fields* within the chosen dataset as primary carriers** — submitted-alpha volume is a field-quality proxy (dense, stable, robust-universe-friendly). Reserve sparse/event-spiky low-volume fields (single-event VECTOR sentiment, <100 alphas) as diversifiers only, never as the sole carrier — they fail CONCENTRATED_WEIGHT/margin even when the pyramid multiplier is attractive (IND earnings11 evidence). "Un-lit pyramid" restricts the category, not the dataset's maturity; pick the highest-volume dataset within the un-lit pool (`reference/dataset-selection-policy.md §3`).
   - `fixed_dataset`: respect the requested dataset and rank fields normally; do not switch just because the dataset is crowded.
   - `high_usage`: activate `reference/dataset-selection-policy.md §2`. In this mode, high `alpha_count` / `user_count` is treated as evidence of mature coverage and reliable prior estimates, not as an automatic crowding penalty. Still record crowding risk and require downstream two-field decrowding plus production-correlation gates.
   - `stochastic_pyramid`: activate `reference/dataset-selection-policy.md §3`;
     in this repository prefer `python scripts/stochastic_dataset_selection.py`
     for the actual draw and `dataset.selection_sampled` record.
     Use this only when the user asks for unlit pyramid mining without naming a
     fixed dataset, explicitly asks for low-usage selection, or asks for randomness. Prioritize unlit /
     under-lit pyramid categories first, then apply weighted randomness inside
     the eligible pool. Include recently selected datasets as soft repeat
     penalties so the workflow does not always re-enter the same dataset. Do
     not hard-code a first dataset. Sample a category and dataset with recorded
     weights, then treat the sampled dataset as `fixed_dataset` until the
     user's stickiness cap, platform invalidity, or target completion.
6. For each field, compute:
   ```python
   os_is_weight = 0.5 + 0.5 * clip(os_is_sharpe_ratio, 0, 1)   # 0.5..1.0
   popularity = log(1 + alpha_count)                          # scale; capped in high_usage mode to avoid one field dominating solely by usage
   memory_score = (submittable*2 + promising + 1) / (trials + 5)  # add-k smoothing
   coverage_penalty = 0.8 if coverage < 0.5 else 1.0
   tag_boost = {"T1": 1.2, "T2": 1.0, "T3": 0.8, "avoid": 0.1}[priority_tag]
   # NEW — penalize fields the user's own submitted alphas already carry (self-corr defense):
   submitted_overlap_penalty = {"none": 1.0, "seen": 0.35, "heavy": 0.10}[submitted_overlap]
   composite = memory_score * popularity * os_is_weight * coverage_penalty * tag_boost * submitted_overlap_penalty
   ```
   In `high_usage` mode, also emit `crowding_role`:
   ```yaml
   crowding_role: mature_source | crowded_standalone | decrowding_axis | source_pair_component | avoid_public_template
  high_usage_reason: high_alpha_count | high_user_count | reliable_os_is_count | strong_memory | coverage | default_high_crowding_priority
   canonical_crowding_risk: low | medium | high
   coverage_axis_hint: date | instrument | coverage_proxy | unknown
   ```
   Fields tagged `crowded_standalone` may remain in the shortlist only as pair components, residualization axes, or ablation baselines; they should not be the sole source of a main candidate.

   **`submitted_overlap` handling (mirrors `crowded_standalone`, but it's the user's *own* book):**
   - `recent_banned` — field appears in `recent_submitted_fields` / `dataset_recent_banned_fields` from the last 90 days. Hard reject from shortlist and emit `field.recent_submitted_banned`; it cannot be a main field, pair component, cohort axis, denominator, confidence field, or diagnostic ablation in the next batch.
   - `none` — eligible main carrier with no extra constraint.
   - `seen` (1 submitted alpha uses it) — may be a main carrier only if the candidate documents a decorrelation mechanism vs that submitted alpha (a *different transform family* AND a *different group/neutralize axis* than the submitted code) and is flagged for mandatory `check_self_correlation < 0.4` before any L2 wrapper. Otherwise pair-component / ablation only.
   - `heavy` (≥ 2 submitted alphas use it) — never the sole source of a main candidate; pair-component / decorrelating-axis / ablation only. Keep it in the shortlist (it may still be a useful diversifier) but its low composite score should naturally push it down.
   These tiers are passed through to `wqb-hypothesis-designer`, which enforces a per-batch fresh-field quota (≥ 2 of 4 candidates built only from `submitted_overlap == none` primary fields).
7. If `region in {"EUR", "GLB"}`, add region group context from
   `reference/EUR-GLB-forum-lessons-2026-05-05.md`:
   - include platform-valid standard groups when visible: `country`, `market`,
     `sector`, `industry`, `subindustry`, `currency`, `exchange`;
   - include high-coverage GROUP fields as possible cohort axes, but do not
     promote opaque low-coverage identifiers unless their description has a
     clear economic peer-group meaning;
   - mark field-level `coverage_axis_hint` from metadata: low `dateCoverage`
     suggests `date`, low cross-sectional coverage suggests `instrument`,
     count/coverage/source-count fields used alone suggest `coverage_proxy`;
   - mark `canonical_crowding_risk=high` for high-usage, single-role popular
     fields that are likely to form public one-field templates.
8. Sort desc, take top 40. Drop any with `trials >= 5 AND submittable == 0 AND promising == 0` (learned-dead fields), unless `dataset_selection_mode=high_usage` and the field is needed only as a `decrowding_axis` / pair component.
9. Assign `semantic_role` heuristically:
   - contains `_calendar_` → `event_gate`
   - contains `_delta_` or `_change_` → `change`
   - contains `_days_` or `_count_` → `persistence`
   - else → `level`
10. Assign `semantic_detail` using field descriptions:
   - contains buy/sell/call/put/sentiment polarity/transaction direction → `field_role=direction`
   - contains shares/cap/assets/volume/holdings/price/book size → `field_role=scale`
   - contains estimate/forecast/expected/target → `field_role=expectation`
   - contains actual/realized/reported/result → `field_role=outcome`
   - contains count/relevance/source/coverage/confidence → `field_role=confidence`
   - contains split/rating/code/type/category → `field_role=categorical`
   - infer `sign_convention` from the description; use `unknown` if ambiguous
   - infer `likely_false_proxy` from low coverage, sparse reporting, scale words, or liquidity-like wording
   - for News fields, descriptions containing price, volume, minutes, EOD, VWAP, session, high, low, record, or price went up/down imply `likely_false_proxy=post_event_reaction` or `liquidity`; set `role_type=context_gate|bucket_axis` unless the field clearly contains ex-ante sentiment or forecast direction
   - for `news12`, apply `reference/news12-playbook.md`: `*_result*`, `*_sl`, `*_newrecord`, `*_vol_ratio`, `*_curr_vol`, `*_10_min`, `*_120_min`, `*_high*`, `*_low*`, and `*_vwap*` are context/gate/bucket inputs first, not standalone sources
11. Emit `fields.scanned { dataset, count, top5: [...], submitted_overlap_counts: { none: N, seen: N, heavy: N }, n_submitted_codes }` event. In high-usage mode include `dataset_selection_mode`, `alpha_count_rank_reason`, and `crowding_policy="decrowd_by_two_field_l0_and_corr_gate"`. For EUR/GLB include `region_group_context` and a compact count of fields by `coverage_axis_hint` / `canonical_crowding_risk`. If `submitted_overlap_counts.none == 0` for the whole shortlist (every field is already in the user's book), also set `all_fields_submitted_overlap: true` + `submitted_overlap_advice: "switch dataset or accept self-corr risk; do not burn budget here"` in the same `fields.scanned` payload — this is the signal to rotate datasets, not to grind.

## 6. Events emitted

`fields.scanned { dataset, count, top5, used_cache: bool }`

### Trace events emitted (Trace 2.0 schema — see reference/trace-schema-v2.md)

After Step 5 (per-field composite score computation) and **before** Step 6 (top-40 truncation), emit one `field.scored` event per scored field. Keeps full per-field score breakdown for objective field-attribution by `wqb-self-diagnostic`.

```json
{
  "kind": "field.scored",
  "payload": {
    "dataset": "<dataset_id>",
    "field_id": "<field_id>",
    "components": {
      "memory_score": 0.0,
      "popularity": 6.26,
      "os_is_weight": 0.72,
      "coverage_penalty": 1.0,
      "tag_boost": 1.2,
      "submitted_overlap_penalty": 1.0,
      "neut_prior_top": "INDUSTRY"
    },
    "submitted_overlap": "none",
    "submitted_overlap_count": 0,
    "composite": 0.45,
    "rank": 1
  }
}
```

`components.neut_prior_top` = top-ranked neutralization choice for this field per `data/priors/{region}_{delay}_<dataset>.json` `per_field_neutralization` (or `null` if no per-field prior). Schema: `reference/trace-schema-v2.md §3.1`.

Add `semantic_detail` to each `field.scored` payload so later attribution can distinguish true economic variables from coverage/scale proxies.

For `region in {"EUR", "GLB"}`, also include:

```json
{
  "coverage_axis_hint": "instrument",
  "canonical_crowding_risk": "medium",
  "region_group_context_ref": "reference/EUR-GLB-forum-lessons-2026-05-05.md"
}
```

For category `News`, also include:

```json
{
  "semantic_detail": {
    "role_type": "context_gate",
    "likely_false_proxy": "post_event_reaction",
    "source_layer_note": "requires News source-proof parent before L2 repair"
  }
}
```

**Volume note**: emits N events where N = total scored fields (typically 30–120 per dataset). Acceptable: each <512 bytes.

### v0.4 Phase 3 — Forum/Web consultation at S1 (additive)

Before Step 5 (composite scoring), check whether a fresh per-dataset forum distillation exists. If not, fetch and incorporate.

```bash
# 1) Cache check
python3 scripts/external/consult.py check --source forum \
  --query "<dataset_id> alpha submittable patterns" --stage S1
# → JSON; if cache_hit=true and age_days <= 7, skip MCP fetch
```

If `cache_hit == false`:
1. Call MCP: `search_forum_posts(query="<dataset_id> alpha submittable")` — top 5 posts.
2. For each, optionally `read_forum_post(post_id)` for body.
3. Distill into a markdown summary (≤500 words) with: top fields mentioned, top operators, common patterns, common pitfalls. Save to `/tmp/distilled.md`.
4. Optionally also use the client's web-search tool for `WorldQuant BRAIN <dataset_id> alpha` — top 3 hits, append to distillation.
5. Record:
   ```bash
   python3 scripts/external/consult.py record --source forum \
     --query "<dataset_id> alpha submittable patterns" --stage S1 \
     --hits <N> --distilled-content-file /tmp/distilled.md \
     --session-id <sid>
   ```
6. Re-rank shortlist: any field mentioned ≥2 times in the distillation gets `popularity *= 1.25` boost in Step 5's composite formula.

If `cache_hit == true`: just `python3 scripts/external/consult.py record_hit ... --stage S1` to log a trace event, then read the cached file and apply the same re-ranking.

**Budget impact**: 0 (forum + client web-search are 0-budget; verified by `tests/eval/checks/external_budget.py`).

## 7. Constraints

- Shortlist ≤ 40 fields. Hard cap.
- Drop fields with `trials≥5 ∧ 0 pass` (avoid re-exploring learned-dead).
- Always populate `submitted_overlap` / `submitted_overlap_count` for every shortlisted field (from `scripts/submitted_field_overlap.py`); a missing or stale `my_submitted_<region>_regular.json` must be refreshed first, not skipped — silently treating every field as `none` is the bug this guard exists to prevent.
- Hard-ban any field in `recent_submitted_fields` from the rolling last 90 days (`scripts/submitted_field_overlap.py --recent-days 90`). Do not keep it as a pair component, scale denominator, confidence field, cohort axis, or ablation; rotate to fresh fields or switch dataset if this empties the field inventory.
- Never call simulation-inducing MCP tools here.
- Never add synthetic fields here; synthetic fields belong only in `wqb-zero-order-field-factory`.
- Do not rank News post-event reaction fields as standalone alpha sources solely because OS/IS or alphaCount is high; preserve them as context/gate/bucket fields for S2.5 source-proof construction.
- When `dataset_selection_mode` is absent for broad mining, assume `high_usage`.
- When `dataset_selection_mode=high_usage`, do not reject a dataset solely for `alphaCount > 1000`; instead require S2.5/S3 to form differentiated two-field L0 roots and require S5 to enforce production-correlation qualification before any robustness/property work.
- For EUR/GLB, do not hard-code `group_cartesian_product(country, subindustry)` as always correct. Surface it as a candidate axis and require S2.5/S3 to justify or skip it from field semantics.

### v0.5 Source-identifiability gate for unlit/low-usage datasets

When the user requests unlit / under-lit pyramid mining, do **not** treat low usage as sufficient evidence of opportunity. Before selecting or continuing a dataset, compute a qualitative `economic_expressivity_score` from the field metadata:

```yaml
economic_expressivity_score:
  directional_fields: count     # buy/sell, call/put, upgrade/downgrade, sentiment polarity, expectation/actual pairs
  scale_only_fields: count      # shares, market value, volume, holdings, cap-like fields
  reporting_cadence_fields: count # report dates, filing dates, freshness/cadence only
  opposed_pair_available: bool
  source_role_diversity: low | medium | high
  standalone_source_status: true_source | weak_source | context_only
```

Hard interpretation:

- `true_source`: at least one directional/opposed/surprise variable exists, or prior memory has a same-dataset L1 parent with Sharpe ≥ 0.8 and 2Y Sharpe ≥ 1.2.
- `weak_source`: fields are mostly scale/coverage/reporting cadence but can still support one source-validation batch.
- `context_only`: no plausible causal direction after reading descriptions; use only as bucket/context companion with a stronger external source field, not as a standalone dataset campaign.

Dataset stickiness is conditional on source evidence. For `weak_source` datasets with ≤4 fields and no opposed pair, the workflow may run at most two 4-child source-validation batches before rotating, even if the global 1000-child stickiness cap has not been reached. This prevents burning budget on an unlit dataset whose economic variables are not identifiable.

## 8. Self-validation

- [ ] Output has `count <= 40`
- [ ] Top-1 field has `composite_score > 0` and valid `field_id` in `data/platform/<dataset>_datafields.json`
- [ ] Every field in `dataset_recent_banned_fields` from the rolling last 90 days is removed before shortlist scoring
- [ ] Every shortlisted field has `submitted_overlap` ∈ {none, seen, heavy} and `submitted_overlap_count` set from `scripts/submitted_field_overlap.py` (not all-`none` by omission)
- [ ] At least one `submitted_overlap == none` field is in the top 10 by composite, OR `fields.scanned.all_fields_submitted_overlap == true`
- [ ] `fields.scanned` event written to records (includes `submitted_overlap_counts` and `recent_submitted_banned_count`)
- [ ] EUR/GLB output includes `region_group_context` or a clear reason it could not be built
