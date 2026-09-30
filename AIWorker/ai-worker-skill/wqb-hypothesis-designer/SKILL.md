---
name: wqb-hypothesis-designer
description: "Generate 4 structured hypotheses for the next batch, each carrying the 14-key YAML schema (§3). Enforces diversity + fingerprint + forbidden-pattern pre-checks BEFORE handing to wqb-batch-runner. Part of the WorldQuant BRAIN auto-mining workflow (S3 of workflow/auto-mining.md)."
---

# Skill: wqb-hypothesis-designer

**Consumers**: Claude Code · GitHub Copilot · Codex · generic assistants
**Stage**: S3 of `workflow/auto-mining.md`
**Budget cost**: 0 (no MCP calls)

## 1. Purpose

Generate **4 structured hypotheses** for the next batch, each carrying the 14-key YAML schema (§3). Enforces diversity + fingerprint + forbidden-pattern pre-checks BEFORE handing to `wqb-batch-runner`.

**v0.9 (2026-07 template-first 根重构；规范源 `reference/template-standard.md`)**：

- **唯一 bandit 臂 = template-cell** `(region, dataset_category, skeleton_fingerprint)`。后验从
  `memory/{region}/template_effectiveness.jsonl` 流水累加；学习信用记到模板，不再记到 paradigm×field-role。
- **template_ref 先行**：4 个槽每个都先有 `template_ref = {catalog_id, skeleton_fingerprint, lifecycle, source}`，
  再填 slot（field/window/group/settings/sign，域见 `template-standard.md §2`）。「先选骨架后填字段」从约定
  变成数据结构必然。每槽 emit `template.selected`。
- **4 槽结构** = 2 exploitation（Thompson 选 registry 模板 → `template_transfer.transfer()` ≥2 轴变异）
  + 2 exploration（`coverage.empty_cells()` 空格 → skeleton_donor / archetype 现造 `generated_first_principles`
  实例）。50/50 track-allocation 契约不变（exploration=BFS 兼容标签）。
- 旧 4-tuple paradigm-cell `(task_type, paradigm, construction_mode, field_role_signature)` **deprecated-as-arm**：
  只读冷启动先验（模板 cell 全冷时用 `paradigm_effectiveness` 挑 skeleton_family），不再作为采样臂。

（v0.5–v0.8 历史：zero-order-first / template-skeleton-first / operator-class-first / adjacent-category transfer——机制全部并入本版结构，不再单列。）

## 2. Inputs (YAML)

```yaml
shortlist: <output of wqb-field-explorer>  # ≤40 fields; each carries submitted_overlap ∈ {none,seen,heavy} + submitted_overlap_count
submitted_alpha_overlap:                    # from `python scripts/submitted_field_overlap.py --region <R>`
  submitted_fields: dict                    # { field_id: submit_count } in this region's submitted REGULAR alphas
  submitted_field_pairs: list               # [[a, b, count], ...] — pairs already submitted together
  recent_submitted_fields: dict             # hard-ban: rolling last 90 days
  n_submitted_codes: int                    # 0 because cache missing/stale -> stop and refresh; never dispatch S4 blind
zero_order_fields: <output of wqb-zero-order-field-factory>  # field-slot 填充子程序输出, up to 24 L0 fields
dataset_id: "earnings2"
dataset_category: "Earnings"
region: "USA"   # binds memory/{region}/ paths
delay: 1
template_context:                           # v0.9 核心输入
  registry_rows: list                       # scripts/templates/registry.py select(region, category) — proven>promising>runnable
  coverage_empty_cells: list                # scripts/templates/coverage.py empty_cells(region, category) — 未试 skeleton families
  archetypes: list                          # data/templates/archetypes.jsonl（transfer 引擎构造原型库）
  blocked_skeletons: set                    # data/templates/blocked_skeletons.txt — 第 0 道过滤
  transfer_map_edges: list                  # reference/category-template-transfer-map.md 相邻类目边
playbook:
  templates: list                           # reference/<dataset>-playbook.md §3 — 冷启动兜底
  forbidden_seeds: list                     # §5 bootstrap forbidden regex
memory_snapshot:
  template_effectiveness: list              # memory/{region}/template_effectiveness.jsonl — bandit 后验唯一来源
  paradigm_effectiveness: list              # deprecated-as-arm：只读冷启动先验
  forbidden_patterns: list                  # memory/{region}/forbidden_patterns.jsonl (unexpired)
  fingerprints: set                         # memory/{region}/fingerprints.txt
  structural_features: list                 # memory/{region}/structural_features.jsonl
  l1_parent_bank: list                      # recent L1 parents with diagnostics, if available
strategy_diversity_context: { latest_check: dict | null, required_when_due: true, block_same_family_when_decision_block: true }
external_hypothesis_cards: []               # [{card_id, source_type, claim, l0_construction_hint, priority_score}]
field_family_seed: {}                       # wqb-field-family-scout output (focused_family_probe), optional
news_campaign_plan: {}                      # News 类目专项 (dataset_family / lifecycle_slots / source_proof_gate)
region_group_context: {}                    # standard_groups / country_cross_candidates / cohort_axis_candidates
robust_cohort_context:
  trigger_checks: list                      # LOW_ROBUST_UNIVERSE_SHARPE / LOW_SUB_UNIVERSE_SHARPE / concentration / investability
  candidate_axes: list                      # size, liquidity, volatility, source coverage/relevance/novelty, market-specific
  required_next_two_batches: bool
  skip_reason: null | no_semantic_axis | source_validation_first | same_axis_neutralization_risk | operator_budget_risk
operator_coverage_state: { operators_seen: list, operators_unseen: list, underused_operator_families: list, parameterized_operator_depth: dict }
recommended_neutralization: "INDUSTRY"      # reference/alpha-corrected.md §8 fallback
auto_mode: true
aggressive: false
dataset_selection_mode: high_usage | low_usage | fixed_dataset
```

## 3. Outputs (YAML)

Exactly 4 dispatchable hypotheses. If fingerprint dedup or forbidden-pattern filtering shrinks the set below 4,
use reserved hypotheses, controls, ablations, or nearby variants that preserve research value to refill. If S3
cannot produce 4 valid children, defer the batch instead of emitting a 2-child or 3-child payload.

```yaml
hypothesis_id: h-s-<YYYYMMDD>-<letter>-<NNNN>     # globally unique
hypothesis: "1-sentence plain-language description"

template_ref:                      # v0.9 硬前置：先有骨架身份，再填 slot（每槽必填）
  catalog_id: "T01-075" | "H-USA-003" | "G-USA-001" | null   # null 仅限 generated 且尚未注册
  skeleton_fingerprint: "c73e15ad72f32bd3"                   # canonicalize 后 md5[:16]（template-standard §1）
  lifecycle: proven | promising | runnable | generated       # generated = 本 session 现造，未入 registry
  source: registry | generated_first_principles
pending_catalog_registration: false | true   # true ⇒ S9 wqb-memory-writer 注册 H-/G- id；S3 不写 catalog/registry

# RD-Agent style economic 4-tuple — ALL 4 MUST BE NON-EMPTY.
# v0.9 规则：claim/mechanism 可从 template_ref 模板的机制三元组（mechanism / statistical_surgery /
# decorrelation_step）继承改写，但 falsifiable_prediction 必须针对本次实例化现补，不得继承。
claim: "the testable proposition"
mechanism: "economic / behavioral / microstructure mechanism (citation when from external evidence)"
falsifiable_prediction: "concrete pass criteria — e.g. 'SR_year ≥ 1.0 AND IC_5d ≥ 0.04 in ≥ 3/5 years AND reverse-control SR_year ≤ 0.3'"
negative_control: "what should NOT work if the claim is true"

task_type: level | change | shock | persistence
paradigm: P1..P13
direction_type: reversal | continuation | undecided
role_type: standalone | confirmation | interaction | gating | unknown
fields: [field_id_1, ...]         # ≤ 3
external_evidence_ids: []          # data/external_hypotheses/<region>/<dataset>.jsonl card ids; empty ⇒ MUST attach skip reason
external_evidence_skip_reason: null | "S2.2 not triggered" | "no relevant external sources" | "category_template_transfer"
parent_hypothesis_id: null | str
template_skeleton_id: "tskel-<family>-<short-hash>"   # 派生自 template_ref.skeleton_fingerprint（兼容字段）
template_skeleton_family: ratio_standardize | horizon_differential | pairwise_dependence | residual_purification | cohort_relative | regime_state | distribution_shape | coverage_intensity | vector_aggregation | generated_first_principles
template_stage_path: "L0:<construction> -> L1:<transform> -> L2:<normalization/residual/gate>"
template_source: dataset_playbook | proven_registry | forum_template | generated_first_principles | external_card
forum_template_refs: []           # e.g. ["T01-075"]; 未验证条目 inspiration only；registry-validated 条目走 transfer 合法 copy-and-mutate
skeleton_axis_signature:
  l0_construction: ratio | spread | surprise | intensity | interaction | dispersion | event_breadth | bucket_axis | pairwise_dependence | residual
  l1_transform_family: rank | ts_zscore | ts_rank | ts_delta | fast_slow | regression | correlation | nonlinear_distribution | vector_collapse | none
  l2_structure_family: group_rank | group_zscore | group_neutralize | vector_neut | custom_bucket | regime_gate | raw | none
  neutralization_or_cohort_axis: standard_group | custom_bucket | composite_cohort | residual_factor | none
  horizon_bucket: short | medium | long | fast_slow | lead_lag | cross_sectional
operator_class_signature: []       # core signal path classes（Step 2.7a 类目表），not wrapper-only decoration
primary_operator_class_pair: [time_series_level, group_cross_sectional]  # exactly two primary classes driving extraction
excluded_operator_classes: [pairwise_time_series, cohort_bucket]         # classes intentionally absent
operator_class_role_map: {}        # class -> role sentence
underused_operator_class_target: null | pairwise_time_series | cohort_bucket | nonlinear_shape | state_gate | time_series_change
zero_order_provenance:
  zfield_id: z1
  zfield_expression: "<L0 expression>"
  construction_family: ratio | spread | surprise | intensity | interaction | dispersion | event_breadth | bucket_axis
  two_field_construction_mode: math_relation | pairwise_operator | custom_group_axis | main_aux_complement | horizon_complement | conditional_regime_gate | composite_cohort_axis | vector_field_pairing
  source_field_count: 1 | 2 | 3
  source_fields: []
  cohort_axis_field: null | str
  cohort_axis_field_b: null | str         # for composite_cohort_axis: 2nd axis field
  l0_economic_role: spread | disagreement | confirmation | horizon_mismatch | scale | surprise | confidence_weight | cohort_residual | negative_control
  companion_field_role: opposed_side | scale_denominator | expectation | confidence_weight | cohort_axis | auxiliary_signal | reverse_control | regime_gate | vector_collapse_target | none
  derived_from_template_id: null | str    # = template_ref.catalog_id / transfer parent id
  main_aux_structure:                     # required when mode == main_aux_complement
    main_signal: null | str
    auxiliary_signal: null | str
    auxiliary_role: null | confirmation | confidence_weight | horizon_bridge | orthogonal_residual | risk_control | negative_control | sign_anchor | dispersion_normalizer | coverage_filter | persistence_gate | expectation_baseline
  horizon_structure:                      # required when mode == horizon_complement
    fast_horizon: null | int
    slow_horizon: null | int
    lead_lag_offset: null | int
  regime_gate_structure:                  # required when mode == conditional_regime_gate
    regime_variable: null | str
    regime_state: null | high_vol | earnings_window | post_event | attention_spike | crowding_high | tail_state | other
    expected_sign_in_state: null | positive | negative | unknown
    gate_operator: null | if_else | trade_when | keep | nan_mask | clamp_inverse
  composite_cohort_structure:             # required when mode == composite_cohort_axis
    axis_a_field: null | str
    axis_b_field: null | str
    sparse_bucket_guard: null | str       # e.g. "group_count >= 20" or "densify"
  vector_pairing_structure:               # required when mode == vector_field_pairing
    vector_field: null | str
    vec_collapse_op: null | vec_avg | vec_sum | vec_count | vec_stddev | vec_range | vec_max | vec_min | vec_norm
    preserved_facet: null | magnitude | coverage | dispersion | topic_subset | spread
    gate_condition: null | str            # scalar gate after vec_* collapse; never a vector element selector
  expected_direction: positive | negative | unknown
  economic_hypothesis: "..."
  false_positive_risks: []
expression_sketch: "<Fast Expression>"  # complete, settings-substituted
expression_level: L1 | L2 | ablation
layer_expressions:
  raw_field_baseline: null | str
  l0: str
  l1: str
  l2: null | str
parent_l1_evidence:
  parent_alpha_id: null | str
  sharpe: null | float
  fitness: null | float
  two_year_sharpe: null | float
  risk_neutralized_sharpe: null | float
  sub_universe_pass: null | bool
  failed_ra_checks: []
  attribution_supports_l0_l1: null | bool
  parent_basic_strength:
    passed: bool
    reason: str
    reverse_control_required: bool
expected_logic: "why this might work (2-3 sentences)"
research_rationale:
  return_attribution_prior: "which component should earn returns"
  economic_mechanism: "bottom-up causal story tied to dataset field definitions"
  statistical_evidence_plan: "relation to verify; include negative controls when possible"
  signal_processing_rationale: "why the transform/window extracts signal rather than noise"
  trade_when_risk_assessment: null | "required if expression uses trade_when/threshold/event gate"
risks:
  - "specific failure mode 1"
  - "specific failure mode 2"
suggested_params:
  decay: int                      # slot 域 {0,6,12,21,63}；transfer batches[].suggested_settings 优先
  truncation: 0.08                # {0.05, 0.08, 0.15}
  neutralization: INDUSTRY        # region 裁剪后的平台枚举
  pasteurization: "ON"
  nanHandling: "OFF"
  unitHandling: "VERIFY"
  language: "FASTEXPR"
shape: symmetric | asymmetric | one-sided | cross-layer | mono
outer_wrapper: rank_family | zscore_family | neutralize_family | raw_arith | gate_family | decay_family | power_family | trade_when
cohort_axis_family: none | standard_group | custom_bucket_size | custom_bucket_liquidity | custom_bucket_volatility | custom_bucket_source_coverage | custom_bucket_source_relevance | custom_bucket_source_novelty | country_crossed | market_specific
exploration_exploitation:
  track_role: exploration | exploitation
  coverage_target: skeleton_family_gap | operator | parameter | field_role | l0_family | source_validation | parent_repair | none
  exploration_debt: int
  exploit_deficit: int
operator_usage_plan:
  operators_used: []
  parameter_values_used: {}
  underused_operator_reason: str | null
submitted_overlap_summary: { primary_fields: [], max_tier: none|seen|heavy }
```

Plus (optional) `reserved: [...]` — 2 backup hypotheses to swap in if fingerprint collides.

## 4. MCP tools used

**None.** This skill is pure reasoning (optional forum lookup in Step 6 goes through `scripts/external/consult.py` cache first).

## 5. Steps

### Step 1. Memory precedence + template-cell Thompson sampling

**Memory 优先级（单列表，读一遍即可）**：

```text
1. dataset-local hard state    memory/{region}/{fingerprints.txt, forbidden_patterns.jsonl} + learned-dead fields  → 硬约束，任何层不可推翻
2. region 试验流水              memory/{region}/template_effectiveness.jsonl                                        → bandit 后验唯一来源
3. registry 候选池              registry.select(region, category)（global advisory；proven > promising > runnable） → exploitation 模板来源
4. coverage 空格               coverage.empty_cells(region, category)                                              → exploration 目标
5. 相邻类目先验                 reference/category-template-transfer-map.md                                         → exploration 实例化先验
6. paradigm_effectiveness      deprecated-as-arm，只读                                                              → 冷启动 skeleton_family 先验
7. playbook.templates                                                                                             → 冷启动兜底
```

**唯一 bandit 臂 = template-cell** `(region, dataset_category, skeleton_fingerprint)`：

```python
# 后验从 region 流水累加（按 skeleton_fingerprint 分组；category 软匹配同 registry.select）
rows_by_fp = group(memory.template_effectiveness, key="skeleton_fingerprint")
for fp, rows in rows_by_fp.items():
    tc = [r["tier_counts"] for r in rows]
    α = 1 + sum(t.get("promising", 0) + t.get("pending", 0) + t.get("confirmed", 0) for t in tc)
    β = 1 + sum(t.get("reject", 0) for t in tc)
    sampled_value = beta_sample(α, β)
# 采样域 = registry.select(region, category) 返回的模板（blocked/demoted/skeleton_donor 已排除）。
# 流水里没有行的 registry 模板按 (α, β) = (1, 1) 参与采样（乐观均匀先验）。
# top-2 sampled_value → 2 个 exploitation 槽（Step 2）。
```

Emit `bandit.sampled { method: "thompson_template_cell", cells_chosen: [[region, category, fp], ...],
cell_posteriors: [{cell, alpha_post, beta_post, sampled_value, rank, chosen}, ...] }`
（schema：`reference/trace-schema-v2.md §4.1`）。

**冷启动**（该 category 的 template-cell `sum(trials) < 10`，或 registry.select 为空）：

- 用 `paradigm_effectiveness`（**deprecated-as-arm，只读**）挑 1-2 个历史上有效的 `skeleton_family` 方向；
  再在 registry.select 同 family 行中均匀采样；registry 也为空 → `playbook.templates` 均匀采样。
- **MUST emit** `bandit.sampled { mode: "cold_start", method: "uniform_cold_start", dataset_category,
  trials_total, cold_cells_count, cold_start_reason: "trials_total<10" | "no_template_effectiveness_for_category" | "first_session_for_region" }`。
- `is_cold_session=true` 时允许全 exploration，但 `track.allocated` 必须带 `fallback_to_bfs: true` + `exploit_deficit`（铁律 9）。

**10-round strategy-diversity gate（硬输入）**：读最新 `strategy_diversity.checked`；到期缺失先跑
`scripts/session_gate.py strategy-diversity --session-id <sid> --region <R> --universe <U> --delay <D>
--append-record --fail-if-blocked`。`decision == "BLOCK"` ⇒ 不得再从 payload 列出的
`top_strategy_families` / `top_field_sets` 生成候选，除非改 ≥2 结构轴（dataset/category、semantic field set、
`two_field_construction_mode`、`l0_economic_role`、operator family、neutralization/cohort axis——wrapper/window/
sign/decay 不算）；`self_corr_failures_clustered` / `hard_self_corr_block` ⇒ 该 field/source family 未来 10 轮只能
作 negative control / ablation。违规时 emit `hypothesis.regenerate_required { reason: "strategy_diversity_block",
required_axis_changes: [...] }` 而不是填同族变体。

### Step 2. template_ref 先行：4 槽选择 + 实例化（旧 Step 2.0 与 5b 合并）

**硬前置**：每个槽必须先确定 `template_ref = {catalog_id, skeleton_fingerprint, lifecycle, source}`，
然后才允许填 slot（field/window/group/settings/sign）。无 template_ref 的表达式草稿一律作废重来。
每确定一个槽 emit `template.selected { skeleton_fingerprint, catalog_id, lifecycle, source, slot_fill }`
（schema：`trace-schema-v2.md §3.14.1`）。

#### 2a. Exploitation ×2 — Thompson 选模板 → transfer ≥2 轴变异

```python
from templates.registry import select          # scripts/templates/registry.py
from template_transfer import transfer          # scripts/template_transfer.py

cands = select(region, category)                # proven > promising > runnable；排除 blocked/demoted/donor
tmpl  = thompson_pick(cands)                    # Step 1 后验
out = transfer(tmpl, {"region": R, "dataset": ds, "category": cat, "fields": carrier_shortlist},
               n=8, min_axes_changed=2)
# out["variants"][*] = {expression, axis_changes(≥2), skeleton_fingerprint, two_field_mode,
#                       template_skeleton_family, template_stage_path, operator_classes,
#                       novelty, derived_from_template_id}
# out["batches"][*]  = exact-4 quads（已过 diversity contract）+ suggested_settings
#                      （settings 是变异轴：非默认 settings ⇒ axis_changes 追加 neutralization_decay_swap）
```

- 这是 **validated 模板的合法 copy-and-mutate 通道**——「禁止照抄」只约束未验证的原始论坛条目。
  引擎已保证 ≥2 轴变异、fingerprint 不撞 `memory/{region}/fingerprints.txt`、≤3 字段 / ≤8 算子 /
  无 ghost、blocked_skeletons 第 0 道过滤（parent 被 block 时返回 `error: "parent_skeleton_blocked"`
  → 重选下一个模板）。
- `batches[].suggested_settings` 作为 `batch_settings` 种子；候选级 `suggested_params` 之后仅 advisory。
- 变体直接映射进 §3 YAML：`template_ref = {tmpl.catalog_id, variant.skeleton_fingerprint, tmpl.lifecycle,
  "registry"}`、`template_source = proven_registry | forum_template`、
  `zero_order_provenance.derived_from_template_id = tmpl.catalog_id`。
- 同一 parent 模板一个 batch 最多喂 2 个槽（且两个变体的 axis_changes 集合不得相同）。

#### 2b. Exploration ×2 — coverage 空格 → 第一性原理现造

```python
from templates.coverage import empty_cells      # scripts/templates/coverage.py
gaps = empty_cells(region, category)            # 该 (region, category) 从未试过的 skeleton families
```

- 每个 exploration 槽认领一个空格 family（`coverage_target: skeleton_family_gap`）。空格为空集时退回
  次级目标（underused operator class / parameter neighborhood / field role，Step 2.7）。
- 实例化材料二选一：(a) catalog 中同 family 的 `skeleton_donor` 条目（只供学习结构，不直接照抄——
  换 carrier + 换 ≥1 结构轴后重造）；(b) `data/templates/archetypes.jsonl` 原型骨架 + 
  `reference/template-construction-principles.md` 第一性原理配方。产物 `source: generated_first_principles`。
- **相邻类目先验**：沿 `reference/category-template-transfer-map.md` 的边取先验（source category 的已验
  模板机制 → target category 的 carrier）。cross-cluster 边需要非空 `transfer_rationale`；使用时 emit
  `template.transfer_proposed { target_category, source_category, edge, transfer_id, carrier_field, axes_changed }`，
  并标 `external_evidence_skip_reason: "category_template_transfer"`。
- **注册纪律**：新实例的 fingerprint 不在 catalog ⇒ hypothesis 带 `pending_catalog_registration: true`；
  **注册（H-/G- id 分配 + catalog/registry 写入）由 S9 `wqb-memory-writer` 完成**，S3 永不写
  catalog / registry / blocked_skeletons。`template_ref = {catalog_id: null (或 donor id),
  skeleton_fingerprint, lifecycle: "generated", source: "generated_first_principles"}`。

#### 2c. Slot 填充（域 = `template-standard.md §2`，超域 = 非法实例化）

```text
field slot     : S2 carrier shortlist（≤40，已过 submitted-overlap 锁）；优先 zero_order_fields L0 pack
window slot    : {5, 22, 63, 126, 252, 504}（日/周/月/季/年/两年）
group slot     : {sector, industry, subindustry, market, bucket, country*}   # country 仅 EUR/GLB 等支持区
neutralization : region 裁剪后的平台枚举
decay          : {0, 6, 12, 21, 63}   # shock → 低档，persistence → 高档
truncation     : {0.05, 0.08, 0.15}
sign           : {pos, neg}           # 强负/未知符号 parent 必带 reverse/sign control（铁律 2）
```

Neutralization 选择：优先 primary field 的 empirical top neut（样本 `count ≥ 20`）→ dataset top neut（`count ≥ 50`）
→ `recommended_neutralization` 兜底；4 槽全同 neut 时改 1-2 槽为次优兼容设置或记 `neut_diversity_debt`。
exploitation 槽以 `transfer` 的 `suggested_settings` 为准。

#### 2d. Batch 级骨架多样性（硬约束）

1. 4 槽 ≥ 3 个 unique `template_skeleton_family` 且 ≥ 3 个 unique `template_stage_path`；无 family > 2 children。
2. 字段库允许时 ≥ 1 child 非 `ratio_standardize`；优先 `pairwise_dependence` / `residual_purification` /
   `cohort_relative` / `horizon_differential` / `distribution_shape` / `coverage_intensity`。
3. wrapper/sign/window/decay/truncation-only 的差异不算新骨架；新骨架必须动 ≥1 个 L0 构造轴 + ≥1 个
   L1/L2 结构轴，或换 stage path。
4. 可用 family < 3 ⇒ emit `template_skeleton.fallback { reason, families_considered,
   evidence_needed_to_revise }` 并 defer batch；不许花预算跑同族 exact-4。

> **起草前必读**:`skills/wqb-batch-diversity-cheatsheet.md`(SkillOpt 训练产出的 guard 首过清单,实测 sonnet 首过率 0/8→7/8;含算子→类别白名单、裸算术符号不计类、终检流程)。

S4 会用 `scripts/batch_expression_guard.py --require-template-skeleton-diversity` 复检（含
anti-crowding：平台拥挤宏骨架 `group_*/rank/zscore(ts_*(field))` ≤ 1/4，`crowded_skeleton_over_cap`）。

### Step 2.1 — L0 pack 纪律 + two-field 构造契约

契约源：`reference/two-field-construction-contract.md`；模板细表：`reference/two-field-deep-construction-2026-05-08.md §3.4–3.8`。

1. 4 槽优先取不同 `l0_pack_slot`（net_direction / surprise / intensity / interaction / dispersion / bucket_axis）。
2. ≥ 3/4 非 ablation 槽使用 2+ 原始字段（除非 dataset 可行 L0 < 4）。
3. S2 元数据有 opposed pair 时 ≥ 1 槽用 net-direction L0（call-put / buy-sell / upgrade-downgrade / actual-estimate）。
4. **每 batch ≥ 3 个 `two_field_construction_mode`（8 值枚举）+ ≥ 3 个 `l0_economic_role`；无 mode > 2 children。**
   Mode 适用性 gate：`composite_cohort_axis` 需 ≥2 cohort-axis 字段；`vector_field_pairing` 需 ≥1 vector 字段；
   `conditional_regime_gate` 需真实 regime 假设（不是任意阈值）——不适用时回退 v0.1 mode 并 emit
   `two_field_mode.fallback { from, to, reason }`。
5. Parent/source 强负或符号未知 ⇒ 预留 1 child 做 `reverse_control` / paired sign control。
6. `ts_ops(ts_backfill(winsorize(single_field)))` 不占主槽，除非显式 `ablation`。

| mode | 典型模板（1 例） | 必附结构块 |
|---|---|---|
| `math_relation` / `pairwise_operator` | `divide(A,B)` / `ts_corr(A,B,63)` | — |
| `custom_group_axis` | `group_rank(A, bucket(rank(B), range="0,1,0.1"))` | `bucket_axis_hypothesis` |
| `main_aux_complement` | `multiply(rank(main), rank(aux))` | `main_aux_structure` |
| `horizon_complement` | `subtract(ts_mean(A,5), ts_mean(A,252))` | `horizon_structure` |
| `conditional_regime_gate` | `if_else(greater(rank(B),0.7), rank(A), 0)` | `regime_gate_structure`（+`trade_when_risk_assessment` when gated） |
| `composite_cohort_axis` | `group_neutralize(A, group_cartesian_product(bkt1, bkt2))` | `composite_cohort_structure` + 双轴 `bucket_axis_hypothesis` + sparse guard |
| `vector_field_pairing` | `multiply(rank(vec_sum(A_vec)), greater(rank(B), 0.5))` | `vector_pairing_structure`（vector 必先 `vec_*` collapse） |

**External hypothesis cards**：有卡时 ≥1 exploration 槽给最高优先级卡（须真实改 source/task/construction 多样性，
不是换叙事）。**Field-family seeds**：`field_family_seed` 存在时给 1 个 BFS source-validation 批
（`focused_family_probe` 可 4 children 同族，但须变 ≥3 个：field subtype / operator / window / sign / cohort axis；
family 未过 parent-basic-strength 禁 wrapper-only L2 续命）。**GLB**：首个生产批前须有 external cards
（否则 `glb.transfer_scout.skipped`）。

### Step 2.2 — Source identifiability + parent-basic-strength gate

每个 mainline hypothesis 附：

```yaml
source_identifiability:
  source_layer_status: true_source | weak | context_only
  expected_return_sign_basis: directional_pair | surprise | signed_intensity | externally_validated | unknown
  negative_control: "what should fail if the source story is real"
  ablation_role: null | raw_baseline | sign_test | wrapper_test
```

规则：`context_only` 不可 standalone（只作 bucket/gate 伴随）；`weak` ≤ 2 个 4-child 批后必须 rotation
（除非有 child Sharpe ≥ 0.8 或 2Y ≥ 1.2）；paired sign test 算一个实验；source 层弱时禁 wrapper-only 修补。

**L2 队列纪律（parent_basic_strength 门）**：任何 `expression_level: L2` 要求
`parent_l1_evidence.parent_basic_strength.passed = true`——最低：一个 return 信号（`sharpe ≥ 0.8` OR
`two_year_sharpe ≥ 1.2` OR `risk_neutralized_sharpe ≥ 0.8` OR `attribution_supports_l0_l1`）+ `fitness ≥ 0.25`
+ sub-universe/robustness PASS + 无硬 RA FAIL。parent `prod_corr ≥ 0.5` / `self_corr ≥ 0.5`，或任一 primary
field `submitted_overlap ≥ seen` ⇒ **wrapper-only L2 禁止**，必须换 L0 family/pair 或 bucket axis。
同 parent 每 session ≤ 2 个 L2 变体（除非其一 PROMISING）。

每个 L2 候选出现在 `hypothesis.proposed` 前 **必须 emit**：

```json
{"kind":"parent.basic_strength.checked","payload":{
  "session_id":"<sid>","parent_alpha_id":"<pid>","passed":true,
  "evidence_metrics":{"sharpe":1.1,"fitness":0.6,"two_year_sharpe":1.4,"risk_neutralized_sharpe":0.9,"failed_ra_count":0},
  "evidence_layer":"L1_metric","reason":null}}
```

`wqb-batch-runner` Phase A lock #7 读该事件，`passed != true` ⇒ batch abort。designer 侧 `passed: false` 时
拒发 L2 `hypothesis.proposed`，改 emit `hypothesis.regenerate_required { batch_id,
reason: "parent_basic_strength_failed", parent_alpha_id }`。News source-proof 模式下门更严（Step 2.3）。

### Step 2.3 — Mode overlays

| Mode | Trigger | Source contract / Required action |
|---|---|---|
| **High-usage decrowding** | `dataset_selection_mode=high_usage`（默认） | `reference/dataset-selection-policy.md §2`。主候选 2-field L0；one-field 仅 `ablation`。附 `decrowding_mechanism`（写进 `statistical_evidence_plan`）+ `crowding_policy: decrowd_by_two_field_l0_and_corr_gate` + `prod_corr_hard_gate: 0.7`。禁 `rank(ts_delta(popular_field, d))` mainline。 |
| **News source-proof** | category `News` + field `role_type ∈ {context_gate, bucket_axis}` AND `likely_false_proxy ∈ {post_event_reaction, liquidity}` | `reference/news-category-playbook.md`。L1 = 一个 News context + 一个 companion（如 `returns`）；记 `effective_pyramids`。纯双 News reaction = ablation。L2/`hump`/threshold 需 parent `Sharpe ≥ 1.25, Fitness ≥ 0.70, sub_universe_pass, failed_ra_checks=[]`。20 child sims 无 source-proof parent ⇒ 熔断 `news_source_layer_weak`。`news_campaign_plan` 存在时首批覆盖 ≥ 2 个 `news_lifecycle_slot`。 |
| **`trade_when` / threshold 纪律** | 表达式含 `trade_when(` / 硬阈值 / event-date gate | 高过拟合 L2 wrapper。必须写全 `research_rationale`（含 `trade_when_risk_assessment`：ungated parent 证据 + ≥1 negative control + gate 稳定性——quantile/rank 阈值优先于 magic constant）。写不全 ⇒ 降 `ablation`。 |
| **EUR/GLB country/cohort** | `region ∈ {EUR, GLB}` + S2/S2.5 暴露 `region_group_context` | `reference/EUR-GLB-forum-lessons-2026-05-05.md`。前两个 rolling batch 预留 1 槽 country/cohort 假设（source ≥ weak、cohort 轴有字段语义理由、不与 settings.neutralization 同轴）。附 `eur_glb_forum_policy {coverage_axis, cohort_axis_used, country_axis_reason, canonical_crowding_risk, skip_reason}`。source 未证 ⇒ ablation 槽，不做装饰性 country wrapper。 |
| **Universal robust-cohort** | `robust_cohort_context.required_next_two_batches=true`（任意 region） | 未来两个 exact-4 批 ≥ 1 槽用有意义的 cohort 轴（size/liquidity/volatility/source_coverage/relevance/novelty/market-country），附 `bucket_axis_hypothesis` + `cohort_axis_family`；source 未证 ⇒ `expression_level: ablation`（诊断用）。 |

### Step 2.4 — Operator-parameter awareness

全签名与 deep-use patterns 见 `reference/operators-catalog.md`。emit `expression_sketch` 时：

1. **关键字参数**：`winsorize(x, std=4)`（位置参数会 `Invalid number of inputs` 取消整个 multi-sim 批）、
   `hump(x, hump=0.01)`、`bucket(rank(x), range="0,1,0.1", skipBoth=False)`、`quantile(x, driver="cauchy", sigma=1.0)`。
2. **`bucket` `range=` 配分布**：rank 后 `'0,1,0.1'`；sentiment [-1,1] `'-1,1,0.2', skipBoth=True`（不 rank）；
   percentile `'0,100,10'`；整数计数用 `buckets='1,5,10,50,100'`。
3. **多轴 residualization OK，同轴双中和 FORBIDDEN**（如 `group_neutralize(..., industry)` +
   `settings.neutralization=INDUSTRY` 杀信号）。
4. 已验 idioms（catalog §Forum-derived idioms）：stage-2 custom group、sub-univ rescue
   `hump(<alpha>, hump=0.01)`（sweep `[0.005, 0.01, 0.02, 0.05]`）。参数不确定时**用 batch 槽做 sweep**，不要猜。

### Step 2.5 — Bucket-axis design

任何 `bucket(...)` 组轴必须附：

```yaml
bucket_axis_hypothesis:
  axis_family: size | liquidity | split | sentiment | confidence | event_lifecycle | dataset_category | other
  bucket_expression: "bucket(...)"
  cohort_logic: "why stocks in this bucket should be comparable"
  distribution_reason: "why range=/buckets= matches this field"
  same_axis_neutralization_check: "passed"
```

写不出 hypothesis ⇒ 去掉 bucket wrapper。`composite_cohort_axis` 要求**双轴**各一份 + `sparse_bucket_guard`
（TOP3000 上 10×10=100 buckets ≈ 30 stocks/bucket：强制上游 `winsorize(A, std=4)` + `group_count > 20` mask
或 `densify`），且双轴都过 same-axis check。

### Step 2.6 — L0/L1/L2 stack identification

每个 hypothesis 附 `expression_level` + `layer_expressions {raw_field_baseline?, l0, l1, l2}`。
同 dataset 的预处理模板保持稳定 ≥ 100 sims（除非 S6.5 attribution 证明它是失败层）。两个候选共享
`{zfield_id, L1 op, window, sign}` 时只留一个，除非 L2 bucket 轴经济上不同。

### Step 2.7 — Exploration/exploitation balance + operator coverage

`reference/track-allocation.md` 是契约源：rolling exact-4 窗口 2 exploration + 2 exploitation。
- **Exploration**：coverage 空格 skeleton family（首选）、underused operator class/parameter neighborhood、
  negative controls、source ablations。
- **Exploitation**：Thompson 选中的 registry 模板 transfer 变体、attribution-backed parents、PROMISING repairs。

Operator coverage 不搞 cargo-cult：underused operator 只有在数据类型与层匹配 source story 时才占 exploration 槽，
否则记 `underused_operator_reason`。参数化算子要在 rolling 槽里扫有意义的参数
（`winsorize(std)` / `hump(hump)` / `bucket(range/buckets/skipBoth)` / `quantile(driver/sigma)` /
`ts_regression(rettype/lag)` / `ts_backfill(lookback/k)` / `jump_decay(sensitivity/force)` 等）。
每个 hypothesis 附 `exploration_exploitation` + `operator_usage_plan`。

4 候选草拟完成后 emit batch 级 `operator.coverage_check { session_id, batch_id, used_operators_in_session,
used_in_last_50_batches, frontier_unused, frontier_unused_count, target_min_frontier_per_batch: 1,
frontier_used_in_this_batch, frontier_debt, frontier_families_in_window }`——frontier 池 =
`operators-catalog.md §Frontier-20`，窗口 = `memory/{region}/operator_usage.jsonl` rolling 50 批
（文件缺失 ⇒ count=debt=20）。batch-runner Phase A lock #8 读此事件。

### Step 2.7a — Operator-class slot allocation (hard)

Core classes（签名保持不变）：

```yaml
operator_classes:
  vector_collapse: [vec_avg, vec_sum, vec_count, vec_stddev, vec_range, vec_norm, vec_max, vec_min]
  arithmetic_ratio: [divide, subtract, add, multiply, reverse, inverse, abs, sign]
  time_series_level: [ts_mean, ts_rank, ts_zscore, ts_quantile, ts_backfill, ts_std_dev, ts_max, ts_min]
  time_series_change: [ts_delta, ts_av_diff, ts_returns, ts_decay_linear, jump_decay, hump, last_diff_value]
  pairwise_time_series: [ts_corr, ts_regression, ts_covariance, ts_triple_corr, ts_vector_neut]
  group_cross_sectional: [rank, zscore, winsorize, normalize, group_rank, group_zscore, group_neutralize, group_vector_neut]
  cohort_bucket: [bucket, densify, group_cartesian_product, group_count]
  nonlinear_shape: [signed_power, power, arc_tan, log, sqrt, max, min, tail]
  state_gate: [if_else, keep, nan_mask, to_nan, clamp, logical/comparison ops, trade_when]
```

**classify → exclude → pair → instantiate** 顺序（每 exact-4 batch）：

1. classify：按当前字段类型与 L0/L1/L2 层列出兼容 classes；
2. exclude：**起草表达式前**每槽先声明 ≥1 个 `excluded_operator_classes`（intentional absence lock）；
3. pair：从剩余 eligible classes 给每槽选 `primary_operator_class_pair`（必须是提取逻辑，不是装饰性外 wrapper）；
4. instantiate：具体算子必须证实声明的 pair，且 excluded classes 真实缺席。

Batch 硬规则：4 个 unique primary pair；≥ 5 unique classes；≥ 3 个 unique excluded classes（4 槽同一个缺席
class 不算 absence design）；pair 不得批内复用；除文档化 boilerplate（如 VECTOR dataset 的
`vector_collapse`）外无 class 出现在全部 4 children；可行时 ≥1 pair 避开 `arithmetic_ratio`、≥1 避开
`group_cross_sectional`（不可行 ⇒ emit `operator_class.fallback { class, reason }`）；某 useful class 缺席
10 个生产轮 ⇒ 给它一个 exploration 槽或 fallback 事件。**Metadata 是证据不是装饰**：声明的 pair/excluded
必须与 `expression_sketch` 实际一致，S4 以 `operator_class_*_mismatch` 系列 reject 假 metadata。

### Step 3. Self-checks (pre-output)

先过 **`reference/diversity-contract.md §5 六锁**（fingerprint、forbidden regex、ghost-op、budget、4-axis
diversity、track），再过下列 overlay。任一失败 ⇒ 重生成对应槽。

1. **Playbook forbidden_seeds** regex。
2. **template_ref 完整性**：4 槽都有 `template_ref.skeleton_fingerprint`，且都不在 `blocked_skeletons`；
   `source=generated_first_principles` 且不在 catalog ⇒ `pending_catalog_registration: true`。
3. **Zero-order provenance**：非 ablation 必带 `zero_order_provenance.zfield_id`。
4. **Vector safety**：VECTOR/event 字段先 `vec_*` collapse 再进标量逻辑。
5. **L2 parent evidence**：`expression_level: L2` 无正向 parent 诊断 ⇒ 降 L1。
6. **Near-correlation pruning**：`research-root-cause-playbook.md §5.2` 相似度 ≥ 0.70 ⇒ 只留一个
   （除非 bucket 轴 family 经济上不同）。
7. **News source-proof**：模式激活时 L2 过更严门（Step 2.3），否则重生成为 L1；robust-cohort child 可作
   `ablation` 诊断例外。
8. **Research rationale** 四件套（return_attribution_prior / economic_mechanism / statistical_evidence_plan /
   signal_processing_rationale）非 ablation 必填。
9. **`trade_when`/threshold 纪律**：外层 `trade_when` ≤ 2/4；≥1 个 ungated source-parent/control；同一 gate
   条件不得出现在 3+ children；全 4 gated 仅限显式 `all_gated_ablation`（非 property-eligible）。
9b. **Submitted-field dedup（self-corr 防御——所有模式）**：
   - **Regional submitted cache 必须存在**：`n_submitted_codes == 0` 因缓存缺失/过期 ⇒ 停 S3，先
     `get_user_alphas` 刷新 `data/platform/my_submitted_<region>_regular.json`；不许标 unavailable 继续。
   - **Recent submitted fields 全角色禁用**（rolling 90 天）：main source、pair、denominator、auxiliary、
     cohort 轴、risk-control、ablation 全算。
   - **Fresh-field quota**：≥ 2/4 候选只用 `submitted_overlap == none` 的 primary fields（primary = 承载方向
     信号的非 base/group 字段）。
   - **`heavy` 不得独载**：primary-field set 全 `heavy` ⇒ 仅 `ablation`。
   - **`seen` 需 decorrelation 机制**：非 ablation 用 `seen` primary field ⇒ 必带
     `self_decorrelation_mechanism { vs_submitted_alpha_id, differs_by: [transform_family, group_axis, ...] }`
     （≥2 结构轴：transform family AND group/neutralize axis）+ `mandatory_self_corr_check: true`
     （S5 `self_corr ≥ 0.40` 即 REJECT，先于任何 S6/S6.5/S7 预算）。写不出 ⇒ 换 `none` 字段重生成。
   - **已提交 pair 不复用**：2-field 候选命中 `submitted_field_pairs` ⇒ 仅 `ablation`。
   - **禁语义家族翻包装**：wrapper/window/neutralization/sign 变化不算 diversity；S4 跑
     `scripts/submitted_family_guard.py`（`source_real_*`→`source_*`、`real_*`→base 归一）block
     `same_semantic_field_set` / `submitted_semantic_pair_reused`。
   - 每个 hypothesis 附 `submitted_overlap_summary { primary_fields, max_tier }`。
10. **Universal robust-cohort**：`required_next_two_batches=true` 时未来两批 ≥1 个 `cohort_axis_family != none`
    + `bucket_axis_hypothesis`，否则 emit `cohort_axis.skipped`。
11. **Template-skeleton diversity**：同 `batch_expression_guard.py --require-template-skeleton-diversity`
    语义（≥3 families / ≥3 stage paths / 无 family >2）。塌缩 ⇒ 回 Step 2 重选 template_ref，不许用改
    field/sign/window 蒙混。`focused_family_probe` 例外同 Step 2.1（一次 source-validation 批，失败即过期）。
12. **EUR/GLB cohort**：country/cohort wrapper 必带 `country_axis_reason` 或 bucket-axis hypothesis；前两批
    skip 要记原因。

### Step 4. Diversity check (batch-level, BEFORE returning)

`reference/diversity-contract.md` 4-axis 规则：≥2 task_types、≥2 paradigms、≥2 shapes、≥2 outer wrappers；
外层 `trade_when` cap 同 Step 3.9。失败 ⇒ 重生成，最多 3 次；仍失败 ⇒ 带 best-4 返回，由 batch-runner
Phase A 再拒。robust-cohort overlay 激活时按 rolling 两批窗口追踪 `cohort_axis_family`。
**不允许 2/3-child payload override**——diversity 按将交给 S4 的 exact 4 评估。

### Step 5. Emit events

Per batch（schema：`reference/trace-schema-v2.md §3.14`（template.*）、`§3.13.3`（hypothesis.proposed）、
`§4.1`（bandit.sampled 扩展）、`§3.6`（track.allocated））：

1. **1 × `bandit.sampled`** — `method: "thompson_template_cell"`（warm）或 `"uniform_cold_start"`（cold），
   warm 时必带 `cell_posteriors[]`（cell = `[region, dataset_category, skeleton_fingerprint]`）。
2. **4 × `template.selected`** — `{ skeleton_fingerprint, catalog_id, lifecycle, source, slot_fill }`，每槽一条，
   在对应 `hypothesis.proposed` 之前。
3. **1 × `track.allocated`（REQUIRED）** — 4 hypotheses 之后、返回外层循环之前：
   ```json
   {"kind":"track.allocated","payload":{"batch_id":"b-s-20260705-x-3","bfs_slots":2,"dfs_slots":2,"fallback_to_bfs":false}}
   ```
   冷启动：`{"bfs_slots":4,"dfs_slots":0,"fallback_to_bfs":true}` + `exploit_deficit`。batch-runner track lock
   缺此事件即 abort。
4. **4 × `hypothesis.proposed`** — 每条带完整 economic 4-tuple + `template_ref` + `structural_features`
   （`n_fields, depth, operatorCount_estimate, k_arity, op_class_hist, outer_wrapper_class, inner_wrapper_class,
   neut_chosen_reason`）+ `track ∈ {"BFS","DFS"}`（warm = 2 BFS + 2 DFS；`"unspecified"` 不被接受）。
5. **条件事件**：`kfield.enumerated`（K=2/3 枚举跑过时，per slot）；`external.consulted`（Step 6 触发时）；
   `template.transfer_proposed`（exploration 用相邻边先验时）；`parent.basic_strength.checked`（每个 L2 候选，
   Step 2.2）；`operator.coverage_check`（Step 2.7）；`hypothesis.regenerate_required` /
   `template_skeleton.fallback` / `operator_class.fallback` / `two_field_mode.fallback` / `bandit.cell_swap`
   （对应失败路径）。

### Step 6. Forum lookup for cold template-cells (optional, per batch)

选中的模板 cell `trials < 2` 且 playbook 无近似骨架时，可查论坛补先验：先
`python3 scripts/external/consult.py check --source forum --query "<skeleton_family> <category> alpha pattern" --stage S3`
（cache 优先）；miss 才 `search_forum_posts`（top 3）→ 蒸馏 1 段 hint → 写进 hypothesis 的
`external_evidence` → `consult.py record`。**每 batch ≤ 1 次 forum lookup，budget 0。**

### Step 7. Post-batch fusion route（指针）

S5 后若同 campaign 有 ≥2 个 PROMISING children 满足：不同 `two_field_construction_mode` + 双方
`parent_basic_strength` 过 + 估算 cross-corr < 0.5 + 预算 ≥ 4 units ⇒ emit `fusion.eligible_pair_found`，
交给 `skills/wqb-alpha-fusion.md`（S4.5，F1–F4 families）。designer 只负责**识别** pair，不做融合构造。

## 6. Events emitted

`bandit.sampled`（method=thompson_template_cell | uniform_cold_start）、`template.selected`（×4）、
`track.allocated`（×1, REQUIRED）、`hypothesis.proposed`（×4, 带 economic 4-tuple + template_ref + track）、
`kfield.enumerated`（条件）、`external.consulted`（条件）；side-effect：`template.transfer_proposed`、
`parent.basic_strength.checked`、`operator.coverage_check`、`hypothesis.regenerate_required`、
`template_skeleton.fallback`、`operator_class.fallback`、`two_field_mode.fallback`、`cohort_axis.skipped`、
`fusion.eligible_pair_found`。Schema 引用：`reference/trace-schema-v2.md §3.14`。

## 7. Constraints

- **Never call MCP**（Step 6 forum lookup 除外，且 cache 优先、每 batch ≤1 次、0 budget）。
- **Never invent fields** not in `shortlist`; **never invent operators** not in `operators-catalog.md` real list。
- **Never write** catalog / registry / blocked_skeletons / coverage json——S3 只读；注册与状态转移归
  S9 `wqb-memory-writer` 与 `scripts/templates/registry.py`。
- Must obey all iron laws from `AGENTS.md §3`。
- `dataset_category = Earnings` ⇒ batch 内 ≥ 1 `shock` 或 `persistence`。
- High-usage 模式下 prod-corr 风险天然更高：S3 负责差异化 source 构造，S5 仍是硬 gate
  （prod_corr > 0.7 或缺失 = 不合格）。
- **Self-corr 防御属于字段选择层**（S2 penalty/tier + Step 3.9b quota），不是 S5/S7 的事后补救。
- EUR/GLB 的 country/cohort 是假设维度：不自动加，也不无声跳过。
- `PROMISING ≠ 可提交`；tier 关系与提交门以 `reference/submission-gates.md` 为准。

## 8. Self-validation

- [ ] Exactly 4 dispatchable hypotheses after fingerprint/forbidden checks and any `reserved` swap
- [ ] **每个 hypothesis 有 `template_ref`（catalog_id / skeleton_fingerprint / lifecycle / source）**，且
      fingerprint 不在 `data/templates/blocked_skeletons.txt`
- [ ] **4 × `template.selected` 已 emit**（每槽一条，先于对应 `hypothesis.proposed`）
- [ ] **2 exploitation 槽来自 `registry.select` + `transfer()`（axis_changes ≥ 2）；2 exploration 槽认领
      coverage 空格或记录了次级 coverage_target**
- [ ] `source=generated_first_principles` 且 fingerprint 不在 catalog 的槽带 `pending_catalog_registration: true`
- [ ] `bandit.sampled` 已 emit：warm = `thompson_template_cell` + `cell_posteriors[]`；cold =
      `uniform_cold_start` + `cold_start_reason`
- [ ] Each hypothesis has all required YAML keys, including layer/provenance fields
- [ ] Diversity check passes（≥2 task_types / paradigms / shapes / outer wrappers）OR best-effort note attached
- [ ] Batch 骨架多样性：≥3 unique `template_skeleton_family`、≥3 unique `template_stage_path`、无 family >2
- [ ] Each `expression_sketch` is valid Fast Expression syntax；no ghost operators；≤3 fields / ≤8 ops
- [ ] Non-ablation hypotheses start from `zero_order_provenance`；两字段契约（≥3 modes + ≥3 roles）满足
- [ ] L2 hypotheses 有正向 parent L1 evidence + `parent.basic_strength.checked` 事件
- [ ] No candidate uses any field from `recent_submitted_fields`（rolling 90 天，全角色）
- [ ] ≥2/4 候选只用 `none` primary fields；无全-`heavy` 主候选；`seen` 带 `self_decorrelation_mechanism` +
      `mandatory_self_corr_check`；无 `submitted_field_pairs` 命中；无 semantic-family 翻包装
- [ ] Each hypothesis carries `submitted_overlap_summary { primary_fields, max_tier }`
- [ ] `research_rationale` 四件套齐全；`trade_when`/硬阈值有 source-edge + negative control 或已降 ablation
- [ ] **每个 `hypothesis.proposed` 带完整 economic 4-tuple**（claim / mechanism / falsifiable_prediction /
      negative_control）——继承模板机制三元组的槽仍须现补 falsifiable_prediction
- [ ] **每个 `hypothesis.proposed.track ∈ {"BFS","DFS"}`**；warm = 2+2，cold 允许 4 BFS 且
      `track.allocated.fallback_to_bfs=true`
- [ ] **Exactly 1 `track.allocated`** per batch（batch_id / bfs_slots / dfs_slots / fallback_to_bfs）
- [ ] EUR/GLB batches used or explicitly skipped the country/cohort slot with a reason
- [ ] Rolling 50/50 exploration/exploitation 保持或记录 debt（`exploration_debt` / `exploit_deficit`）
- [ ] `external_evidence_ids` non-empty OR `external_evidence_skip_reason` populated
