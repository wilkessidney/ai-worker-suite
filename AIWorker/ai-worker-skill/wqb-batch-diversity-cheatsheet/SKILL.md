---
name: wqb-batch-diversity-cheatsheet
description: "WorldQuant BRAIN factor mining skill wqb-batch-diversity-cheatsheet."
---

# Skill: wqb-batch-diversity-cheatsheet

> **来源**:Microsoft SkillOpt(github.com/microsoft/SkillOpt)在本仓库自定义 `wqbbatch` env 上训练产出的 `best_skill.md`(第 3 轮,run `outputs/full_run3`,2026-07-17)。
> **训练方式**:optimizer/target 均为 `claude_chat` backend(`claude -p` 子进程,**无 API key**),reward = `scripts/batch_expression_guard.py`(全 workflow flags)+ 复杂度/ghost/字段幻觉本地检查;`rewrite_from_suggestions` 模式;3 轮累计验证门 0.535→1.00(6/6 val 数据集)。
> **实测效果(valid_unseen,4 个未见数据集 × 2 次重复,target=sonnet)**:guard 首过率 无 skill 0/8 → 手工种子 1/8 → 第 2 轮 4/8 → **本版(第 3 轮)7/8**;soft 0.655 → 0.756 → 0.936 → **0.985**。
> **用法**:S3(wqb-hypothesis-designer)起草 exact-4 批次前、S4(wqb-batch-runner)预检失败重生成时,将本文档作为附加约束清单注入。评估报告:`analytics/skillopt-eval-2026-07-17.md`。
> **真实验证(2026-07-17,s-20260717-a)**:2 个全新数据集冷启动批,双 guard 首试 2/2 全过(本周 cheatsheet 前基线:4 个冷批中 2 个首试失败);真实平台模拟 8/8 编译运行成功;news85 分歧 CV 腿 0.96/2Y 2.01。**边界教训**:guard 通过 ≠ 平台字段有效——datafields 缓存是分 region 面的(rsk62 是 USA model),分发前必须确认字段在目标 region 面存在;且 submitted 缓存须当日新鲜(USA 缓存曾过期 41 天)。
> **注意**:第 6 条映射表是训练发现的保守白名单子集;完整权威映射在 `scripts/batch_expression_guard.py` 的 `OPERATOR_CLASS_MAP`(9 类,含 winsorize→group_cross_sectional、ts_zscore→time_series_level、hump/ts_decay_linear→time_series_change 等)。起草时优先查完整表;本文档的"白名单外即回避"原则仍然成立。

---

# WQB exact-4 batch generation — baseline rules

You generate batches of 4 FASTEXPR alpha expressions with metadata. The batch is rejected unless ALL of the following hold:

1. Exactly 4 hypotheses, each with a valid FASTEXPR `expression_sketch`.
2. Skeleton diversity: at least 3 distinct `template_skeleton_family` values and at least 3 distinct `template_stage_path` values; no family used by more than 2 children.
3. Anti-crowding (macro-skeleton, not just label diversity): at most 1 child may belong to any given deep structural shape ("macro-skeleton"), regardless of what `template_skeleton_family`/`template_stage_path` name was assigned to it. Two children with different family names can still be crowded if their expressions reduce to the same underlying shape. Classify every child into a macro-skeleton bucket BEFORE finalizing family names. At minimum, cap these buckets at 1 member each per batch:
   - **normalize-wraps-single-field-ts-op**: ANY child whose top-level or near-top-level structure is a cross-sectional normalize (rank/zscore/group_rank/group_zscore/quantile/bucket) applied to a single-field time-series transform (ts_delta, ts_mean, ts_std_dev, divide(field, ts_mean(field)), etc.) — regardless of which specific normalize or which specific ts-op is used.
   - **pairwise-correlation-based**: ANY child built around comparing two fields via ts_corr/ts_covariance — whether wrapped in divide, rank, bucket, or used directly — regardless of the outer wrapper.
   If more expressive structural patterns emerge while drafting, extend this bucket list rather than relying on family-name diversity alone.

   **Warning: label diversity is not structural diversity.** Distinct `template_skeleton_family` and `template_stage_path` strings are necessary but NOT sufficient — the grader compares the underlying structural shape (what operator wraps what, over how many fields) independent of the labels you assign. Do not treat a unique-sounding family name as evidence that a child is structurally distinct; verify its macro-skeleton bucket explicitly.
4. Operator classes: the 4 children must declare 4 unique `primary_operator_class_pair` combinations, cover at least 5 distinct operator classes overall, and no class may appear in all 4 children (except vector_collapse for VECTOR data).
5. Exclusions: each child names at least one intentionally absent operator class in `excluded_operator_classes`; at least 3 distinct excluded classes across the batch; an excluded class must NOT appear in that child's expression (check against the fully-scanned signature from rule 6, not against what you originally intended to use).
6. Metadata truthfulness: `operator_class_signature` must equal the set of classes triggered by EVERY operator token literally present in `expression_sketch` — including wrapper/helper calls, never just the "headline" operator or the expression's theme/intent. `primary_operator_class_pair` must be a subset of this signature.

   **Classification is whitelist-only — never infer a class by analogy.** Derive the signature immediately after drafting each child by scanning the expression left-to-right, token by token, and classifying every function call name and bare symbol found strictly against the table below. Do not defer this to a later pass, and do not guess a class for an operator based on how similar it sounds to a known one (e.g. do not assume `s_log` behaves like a known nonlinear operator just because the name looks related).

   Confirmed operator → class mapping:
   - `vec_avg`, `vec_sum`, and other `vec_*` collapse ops → `vector_collapse` (VECTOR data only)
   - Named ratio/division functions (functions literally named `divide`, `ratio`, or percentage-style helpers) → `arithmetic_ratio`
   - `ts_corr`, `ts_covariance` → `pairwise_time_series`
   - `rank`, `group_rank`, `group_zscore` → `group_cross_sectional`
   - `ts_delta` → `time_series_change`
   - `ts_mean`, `ts_std_dev` used as a level or scaling factor → `time_series_level`
   - `bucket` → `cohort_bucket`
   - `trade_when` → `state_gate`

   **Pre-drafting whitelist restriction — apply this BEFORE writing any expression, not just when scanning it afterward.** Compose each child ONLY from operators that already have a confirmed class in the mapping table above (`rank`, `group_rank`, `group_zscore`, `ts_delta`, `ts_corr`, `ts_covariance`, `ts_mean`, `ts_std_dev`, `divide`, `bucket`, `trade_when`). Treat `sign`, `s_log`, `signed_power`, `tanh`, and any other operator not explicitly listed above as **forbidden for this batch** unless you verify its class against an authoritative, up-to-date operator reference in the same turn — never include an unlisted operator "just this once" because the expression reads naturally with it. Worked examples of what NOT to do:
   - Wrong: using `s_log(close)` and declaring `nonlinear_shape` in the signature — `s_log` is not in the mapping table, so its class is unconfirmed; either drop it or verify it first.
   - Wrong: using `sign(ts_delta(volume, 5))` and assuming it contributes a class by analogy to a known operator — `sign` is not in the mapping table and must not be used unless verified.

   **Bare arithmetic symbols do NOT trigger arithmetic_ratio.** A bare `/`, `*`, `+`, or `-` between two subexpressions (e.g. `A / B`, `close - open`) does NOT by itself count toward `arithmetic_ratio` or any other operator class — only explicitly named functions (divide/ratio/percentage-style) do. Example: `close / ts_mean(volume, 20)` triggers `time_series_level` (from `ts_mean`) but NOT `arithmetic_ratio` — the bare `/` contributes nothing to the signature. **If a child's design requires `arithmetic_ratio` to appear in its signature, always write the division as the named `divide(a, b)` function call — never as bare `a / b`.** Bare arithmetic symbols must never be relied on to satisfy an operator-class requirement.

   For any operator token — including `sign`, `s_log`, `signed_power`, `bucket`, `trade_when`, `ts_std_dev` used as a denominator, or any operator not explicitly listed above — that is NOT covered by this table, do not assume its class by analogy. Either confirm its class against a complete, up-to-date operator reference before using it, or avoid that operator in this batch until its class is confirmed.
7. Complexity: each expression uses at most 3 data fields and at most 8 operator calls; use only fields from the provided list.
8. Never use these banned operators: ts_entropy, ts_percentage, ts_skewness, ts_median, ts_min_max_diff, ts_min_max_cps, ts_partial_corr, ts_co_kurtosis, ts_delta_limit, group_normalize, group_median, group_percentage, group_vector_proj, tanh, sigmoid, s_log_1p, ts_decay_exp_window.

## Final consistency self-check (required before output)

After all 4 children are drafted, do a second full pass, separate from the drafting pass. Work through these steps in order and fix-then-recheck if any fails:

1. **Skeleton/crowding tally (rules 2-3):**
   a. List all 4 `template_skeleton_family` values. Confirm at least 3 are distinct and no family appears more than twice.
   b. List all 4 `template_stage_path` values. Confirm at least 3 are distinct.
   c. **Macro-skeleton tally.** For each of the 4 children, assign a macro-skeleton bucket per the rule-3 definitions (normalize-wraps-single-field-ts-op, pairwise-correlation-based, or any other structural bucket you identified while drafting). Tally bucket membership counts across all 4 children and confirm no bucket has more than 1 member. If a bucket has 2+ members, you must revise one child's underlying structure — not just its family name or stage_path label. Swap it for a genuinely different structural pattern (e.g. a state_gate-based child using `trade_when`, a cohort_bucket-first child using `bucket`, or a vector-collapse-based child) rather than renaming the same shape.
2. **Operator-class re-scan (rule 6):** Re-scan every expression token-by-token again, using only the confirmed/whitelisted mapping above — treat any operator whose classification felt uncertain during drafting as a flag to re-verify here.
3. Recompute `operator_class_signature` from this re-scan and confirm it matches what was recorded.
4. Confirm `primary_operator_class_pair` is a subset of the re-scanned signature.
5. Confirm every class in `excluded_operator_classes` is absent from the re-scanned signature.
6. Only after all 4 children pass every step above, finalize and emit the batch. If any mismatch is found at any step, fix the metadata (or the expression) and re-run the full self-check before output.

