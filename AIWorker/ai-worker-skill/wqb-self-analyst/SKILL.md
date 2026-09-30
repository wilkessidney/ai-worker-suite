---
name: wqb-self-analyst
description: "Cross-session analytics. Reads metrics/sessions.jsonl + recent records/.jsonl + memory/{region}/.jsonl, computes submittable-rate per (dataset_category × task_type × paradigm × field × operator), identifies patterns worth forbidding or promoting, and emits a Chinese-first… Part of the WorldQuant BRAIN auto-mining workflow (post-S9 (auto-invoked at session end, or manually))."
---

# Skill: wqb-self-analyst

**Consumers**: Claude Code · GitHub Copilot · Codex · generic assistants
**Stage**: post-S9 (auto-invoked at session end, or manually)
**Budget cost**: 0

## 1. Purpose

Cross-session analytics. Reads `metrics/sessions.jsonl` + recent `records/*.jsonl` + `memory/{region}/*.jsonl`, computes submittable-rate per (dataset_category × task_type × paradigm × field × operator), identifies patterns worth forbidding or promoting, and emits a Chinese-first `analytics/self-report-<date>.md`.

**Template-registry regeneration (post-S9, 2026-07 SoT 版)**: re-render `reference/proven-template-registry.md`
from the SoT `memory/global/template_registry.jsonl`（lifecycle 排序 proven > promising > runnable）+
`memory/{region}/template_effectiveness.jsonl` 流水（effectiveness score 公式见 proven-template-registry 引言），
写 proven/promising 条目 + runnable 汇总 + 「反面骨架」（demoted/retired）小节。报告加三个小节：
(a) 「本切片新增/晋级的有效模板 Top-K」；(b) **coverage 热力**（`memory/{region}/template_coverage.json`
的已试/未试 `(category × skeleton_family)` 格子）；(c) **「候选 lesson」**（哪个 statistical_surgery ×
decorrelation_step 组合在哪个 category 反复有效——供人工择优并入
`reference/template-construction-principles.md §5` / `category-template-transfer-map.md §2`）。

**Lifecycle 提案（不直改 SoT）**：demote/retire 建议走 `diagnostic.proposal`，人工 apply =
`python scripts/templates/registry.py --transition <fp> --to demoted|retired --reason <why>`。
**new_archetype 提案**：新收割骨架的 `template_stage_path`/算子类签名与 `data/templates/archetypes.jsonl`
现有原型均不匹配且 effectiveness ≥ candidate 阈值 → emit
`diagnostic.proposal { type: new_archetype, skeleton, axes, two_field_mode }`；人工 apply 后 append
archetypes.jsonl + `scripts/templates/test_transfer.py` 回归必须过（原型库随学习增长）。

## 2. Inputs

```yaml
session_id: str                          # current session just ended
lookback_sessions: 10                    # default
lookback_days: 7                         # for records scan
metrics_file_path: "metrics/sessions.jsonl"
records_dir_path: "records/"
memory_dir_path: "memory/"
analytics_dir_path: "analytics/"
```

## 3. Outputs

```yaml
report_path: "analytics/self-report-<date>.md"
proven_template_registry_path: "reference/proven-template-registry.md"  # regenerated each run
proven_templates_count: int          # SoT rows with lifecycle in {proven, promising}
pending_forbidden_written: int
section_summaries:
  current_session:
    tier_distribution: dict
    budget_efficiency: float    # sims_succeeded / sims_dispatched
  cross_session_trend:
    recent_submittable_rate: float  # over lookback_sessions
    trend_direction: "improving" | "stable" | "degrading"
  validated_productive_combos: list
  validated_dead_combos: list
  recommended_priorities_next_session: list
  operator_coverage:
    operators_seen: list
    operators_unseen_or_rare: list
    parameter_depth_gaps: dict
  diversity_depth:
    hypothesis_diversity: dict
    field_diversity: dict
    signal_mining_depth: dict
```

## 4. MCP tools used

None.

## 5. Steps

### Step 1. Load data

```python
sessions = [json.loads(l) for l in metrics_file.read_text().splitlines()]
recent_sessions = sessions[-lookback_sessions:]
# Also load recent records files matching date range for deeper analysis
records = []
for p in recent_records_paths:
    records.extend(json.loads(l) for l in p.read_text().splitlines())
```

### Step 2. Compute aggregates

Use `memory/{region}/field_effectiveness.jsonl` + `memory/{region}/paradigm_effectiveness.jsonl` for per-dimension stats. Complement with live counts from `records`.

For each `(dataset_category, task_type, paradigm)`:
- `trials = sum(trials)`
- `submittable_rate = submittable / (trials + 0.5)` (add-k smoothing)
- `wilson_lower_95 = ...` (Wilson 95% CI lower bound)

### Step 3. Sections

**Section A — Current session**:
- Copy current session's `metrics/sessions.jsonl` row, render as table + summary

**Section B — Cross-session trend**:
- Time-series of `tiers.SUBMITTABLE_CONFIRMED` + `tiers.SUBMITTABLE_PENDING` per session
- Compute slope over lookback. Flag "degrading" if slope < -5% per session

**Section C — Validated productive combos**:
- (task_type, paradigm) pairs with `wilson_lower_95 > 0.10` AND `trials >= 3` AND `span >= 2 sessions`
- These are "keep doing more of this"

**Section D — Validated dead combos** (candidates for `forbidden_patterns.jsonl`):
- (task_type, paradigm) pairs with `trials >= 5` AND `submittable == 0` AND `promising <= 1` AND `span >= 2 sessions`
- For each, generate a regex proposal (match task_type + paradigm in expression) and confidence score
- Write to `analytics/pending-forbidden.jsonl` with `{"regex": ..., "reason": ..., "confidence": "high"|"medium", "source": "self-analyst-<date>", "suggested_block_until": "<now+30d>"}`
- **Does NOT** auto-write to `memory/{region}/forbidden_patterns.jsonl` — requires human review

**Section E — Recommended priorities next session**:
- For `wqb-hypothesis-designer` bandit: suggest which (task_type, paradigm) combos to prioritize (top 3 from Section C)
- For `wqb-field-explorer`: suggest which fields to rerank higher (fields with submittable_rate > 0.15)
- Format as actionable bullets

**Section F - Search-space coverage**:
- operator usage and unseen/rare REGULAR operators;
- parameter-rich operator coverage, including which params/values were actually
  tested vs still untested;
- hypothesis diversity across task/paradigm/L0/L1/L2/track/provenance;
- field diversity across unique fields, roles, pairs, and source families;
- signal-mining depth across raw -> L0 -> L1 -> L2 -> robustness/overfit.

### Step 4. Write markdown report

File path: `analytics/self-report-YYYY-MM-DD-<session_id_suffix>.md`. Template:

```markdown
# 自我分析报告 - <date>

## A. 当前会话
...

## B. 跨会话趋势
...

## C. 已验证的有效组合
- ...

## D. 已验证的低效组合（仅建议禁用）
- ...

## E. 下轮优先级
...

## F. 搜索空间覆盖
...

**由 `wqb-self-analyst` 基于 <D> 天内 <N> 个会话生成。**
```

### Step 5. Emit events

- `self_analyst.started { lookback_sessions, lookback_days }`
- `self_analyst.generated { report_path, pending_forbidden_written, sections: {...} }`

## 6. Events emitted

`self_analyst.started`, `self_analyst.generated`

### Trace events emitted (Trace 2.0 schema — see reference/trace-schema-v2.md)

The `self_analyst.generated` payload MUST add a `diversity_coverage` block consumable by `wqb-self-diagnostic`:

```json
{
  "report_path": "analytics/self-report-<date>-<sid>.md",
  "pending_forbidden_written": 0,
  "sections": {...},
  "diversity_coverage": {
    "lookback_sessions": 10,
    "task_paradigm_cells_visited": 17,
    "task_paradigm_cells_total": 28,
    "coverage_pct": 0.607,
    "op_class_entropy": 0.71,
    "paradigm_entropy": 0.62,
    "structural_diversity_score": 0.32
  }
}
```

`structural_diversity_score = op_class_entropy × paradigm_entropy × coverage_pct` — the primary metric used by the eval harness regression check (see `reference/trace-schema-v2.md §7` and the plan file `~/.claude/plans/skills-trace-trace-robust-lerdorf.md` §E).

This block is also persisted as a one-line snapshot to `analytics/diversity_history.jsonl` (idempotent per session).

## 7. Constraints

- **Does NOT write to `memory/`**. Only reads.
- **Does NOT auto-promote forbidden patterns**. All writes go to `analytics/pending-forbidden.jsonl` for human review.
- **Does NOT call MCP**.
- Report must be ≤ 2000 lines to stay skimmable.
- Markdown report should be Chinese-first; keep raw IDs/operators/check names unchanged.

## 8. Self-validation

- [ ] `analytics/self-report-*.md` file exists and is non-empty
- [ ] If pending_forbidden_written > 0, `analytics/pending-forbidden.jsonl` has new entries
- [ ] `self_analyst.generated` event present in records
- [ ] Report includes operator/parameter/hypothesis/field/signal-depth coverage
