---
name: wqb-memory-writer
description: "Read today's records/<date>.jsonl events for the current session_id, aggregate per (field, zero-order field, paradigm, alpha, expression), and idempotently append updates to memory/{region}/.jsonl + memory/{region}/fingerprints.txt + memory/{region}/.last_ingested_ts.json. Part of the WorldQuant BRAIN auto-mining workflow (S9 of workflow/auto-mining.md (evidence-slice closeout; not a campaign stop by itself))."
---

# Skill: wqb-memory-writer

**Consumers**: Claude Code · GitHub Copilot · Codex · generic assistants
**Stage**: S9 of `workflow/auto-mining.md` (evidence-slice closeout; not a campaign stop by itself)
**Budget cost**: 0

## 1. Purpose

Read today's `records/<date>.jsonl` events for the current `session_id`, aggregate per (field, zero-order field, paradigm, alpha, expression), and **idempotently** append updates to `memory/{region}/*.jsonl` + `memory/{region}/fingerprints.txt` + `memory/{region}/.last_ingested_ts.json`.

Also writes one line to `metrics/sessions.jsonl` summarizing the evidence slice.
For manual-submit campaigns whose target is not reached, this row must use
checkpoint language such as `checkpoint_no_property_eligible_candidate` rather
than `completed_*`; S9 completion never authorizes a final answer until
`scripts/continuation_gate.py --fail-if-blocked` allows it.

Memory is hierarchical: exact operational state is region/dataset scoped, while reusable research templates may be promoted to `memory/global/*.jsonl` only as advisory priors after attribution-backed evidence.

**Template harvest (S9)**: for every PROMISING / SUBMITTABLE_PENDING / SUBMITTABLE_CONFIRMED / REJECT alpha in this slice, distill the parametrized skeleton (datafield IDs → `{fieldN}`, windows → `{dN}`, keep operators / wrappers / `bucket` axis; substitute any ghost op per `reference/operators-catalog.md §A/§B` first), normalize to a semantic `template_id`, compute `skeleton_fingerprint`, and idempotently upsert into `memory/{region}/template_effectiveness.jsonl` with rolling effectiveness counts + best metrics. Promote to `memory/global/strategy_templates.jsonl` only when `memory/README.md §0` promotion criteria hold. Full algorithm + schema: `reference/proven-template-registry.md §2–§3`.

## 2. Inputs

```yaml
session_id: str
region: str                         # one of USA/IND/...; binds memory_dir_path subdirectory
records_file_path: "records/<today>.jsonl"
memory_dir_path: "memory/{region}/" # all writes go to this region partition
global_memory_dir_path: "memory/global/" # advisory cross-region template layer; never hard fingerprints/forbidden
metrics_file_path: "metrics/sessions.jsonl"
analytics_dir_path: "analytics/"
```

## 3. Outputs

```yaml
new_fingerprints: int
new_seeds: int                    # SUBMITTABLE_CONFIRMED alphas
new_forbidden_candidates: int     # written to analytics/pending-forbidden.jsonl
field_updates: int
paradigm_updates: int
template_updates: int             # template_effectiveness.jsonl upserts (skeleton harvest)
templates_promoted_global: int    # registry lifecycle promotions this slice (via registry.py)
session_summary_written: bool
```

## 4. MCP tools used

**None.** Pure filesystem.

## 5. Steps (idempotent)

### Step 1. Load sidecar

```python
sidecar_path = memory_dir / ".last_ingested_ts.json"
sidecar = json.load(sidecar_path) if sidecar_path.exists() else {}
last_ts_for_session = sidecar.get(session_id, "1970-01-01T00:00:00Z")
```

### Step 2. Read records, filter by session + timestamp

```python
events = []
for line in records_file.read_text().splitlines():
    e = json.loads(line)
    if e.get("session_id") == session_id and e.get("ts") > last_ts_for_session:
        events.append(e)
events.sort(key=lambda e: e["ts"])
```

### Step 3. Aggregate by kind

- `sim.succeeded`: update `field_effectiveness.jsonl` per field used in expression (`field_id, dataset, trials+=1`)
- `zfield.generated` + downstream `gate.tier`: update `zero_order_effectiveness.jsonl` per `zfield_id`, `construction_family`, and raw field tuple
- `gate.tier`: update `paradigm_effectiveness.jsonl` per `(dataset_category, task_type, paradigm)` with `trials += 1` and increment `submittable` / `promising` / `rejects` per tier
- `attribution.generated`: update `attribution_patterns.jsonl` with `{root_cause_layer, risk.likely_exposure, market_regime_hypothesis, repair_plan targets}`
- `gate.tier` + `hypothesis.generated.expression_level == "L1"`: update `l1_parent_bank.jsonl` for parents with positive diagnostics that can support future L2 variants
- `gate.tier` with `tier == SUBMITTABLE_CONFIRMED` + `robustness.audited { upgrade: true }` → append to `submittable_seeds.jsonl` with full expression + metrics
- All unique `fingerprint` values across `batch.*` / `sim.*` → append to `fingerprints.txt` (if not already present)
- Template promotion candidates: aggregate normalized semantic templates from `hypothesis.generated.research_rationale`, `zero_order_provenance`, `structural_features`, and S6.5 attribution. Write region/category evidence locally; write `memory/global/strategy_templates.jsonl` or `template_effectiveness.jsonl` only when promotion criteria in `memory/README.md §0` are met.

### Step 4. Idempotent append

Use atomic append: read → check existence → write. For JSONL files, check via line-by-line scan; for `fingerprints.txt`, use `set` semantics.

### Step 5. Forbidden-candidate proposal (write to ANALYTICS, not memory)

For each `(field, paradigm)` with `trials >= 5 AND submittable == 0 AND promising == 0`:
- Append to `analytics/pending-forbidden.jsonl` with regex proposal + confidence. Does NOT write to `memory/{region}/forbidden_patterns.jsonl` directly — requires human review.

### Step 6. Session summary → `metrics/sessions.jsonl`

Append one line:

```json
{
  "session_id": "s-20260423-a",
  "dataset": "earnings2",
  "region_universe_delay": "USA/TOP3000/1",
  "started_at": "...", "ended_at": "...",
  "budget_granted": 60, "budget_used": 47,
  "sims_dispatched": 47, "sims_succeeded": 42, "sims_failed": 5,
  "tiers": {"SUBMITTABLE_CONFIRMED": 0, "SUBMITTABLE_PENDING": 3, "PROMISING": 8, "REJECT": 31},
  "submitted": 0, "submit_failed": 0,
  "top_failure_categories": ["high_turnover", "low_sharpe", "sub_universe_fail"],
  "memory_delta": {"new_fingerprints": 47, "new_forbidden_proposals": 2, "new_seeds": 0},
  "circuit_breaker": null,
  "continuation_state": "target_reached|target_partially_filled|needs_continuation|null",
  "target_reached": false
}
```

Do not write `completed_no_property_eligible_candidate` for a manual-submit
campaign with an unreached target. Use `checkpoint_no_property_eligible_candidate`
or a more specific source-diagnosis checkpoint and let the continuation gate
decide whether the same thread must continue.

If the same `session_id` contains multiple `scope.started` contexts, the writer
must not silently summarize only the final dataset. Either write one metrics row
per `(session_id, region, universe, delay, dataset_id)` context, or write one
whole-session aggregate with a `contexts[]` field and per-context child counts.
The sum of `children_dispatched` / `sims_dispatched` must match the normalized
event count from `sim.succeeded`, `sim.failed`, `sim.timeout`, or `gate.tier`.

### Step 6.5. Advance playbook rotation pointer (Cluster 1 / RC3)

Read `memory/{region}/playbook_rotation.json`. If the session emitted `scope.playbook_activated`:

1. Locate the activated playbook's `playbook_id` in `pool`.
2. Set `last_session_per_playbook[playbook_id] = session_id`.
3. If the session also emitted `scope.playbook_skipped` for that playbook → increment `skip_streak[playbook_id]`. Otherwise reset `skip_streak[playbook_id] = 0`.
4. **Advance** `next_index = (next_index + 1) % len(pool)` regardless of skip status (so a chronically-skipping playbook does not block the round-robin).
5. **Retirement check**: if `skip_streak[playbook_id] >= skip_retire_threshold` (default 3), emit a retirement proposal at `analytics/proposals/pending/playbook_retire_<playbook_id>_<session_id>.json` with shape `{ "playbook_id": "...", "skip_streak": <int>, "evidence_session_ids": [...], "proposed_action": "retire", "human_review_required": true }`. Do not auto-remove from `pool` — humans review.
6. Atomically rewrite `playbook_rotation.json` (write to `.tmp`, then `rename()`).

This step is idempotent on `(session_id, playbook_id)`: re-running on the same session does not double-advance `next_index` because the rotation file's `last_session_per_playbook[playbook_id] == session_id` short-circuits the advance.

If the session emitted neither `scope.playbook_activated` nor `scope.playbook_skipped`, do nothing (legacy session compatibility).

### Step 7. Update sidecar

```python
sidecar[session_id] = max(e["ts"] for e in events)
sidecar_path.write_text(json.dumps(sidecar, indent=2))
```

### Step 7.5. Template harvest → SoT（2026-07 根重构；取代已废弃的 hypothesis_registry 落盘）

Hypothesis 生命周期完全活在 `records/*.jsonl`（`hypothesis.*` 事件即状态机）。本步做**模板收割**：

1. 对本 slice 每个 PROMISING / SUBMITTABLE_* / REJECT alpha 跑 8 步骨架蒸馏
   （`reference/proven-template-registry.md` 引言）→ `skeleton_fingerprint`。
2. append 一行到 `memory/{region}/template_effectiveness.jsonl`：
   `{ts, session_id, skeleton_fingerprint, catalog_id, dataset_id, tier_counts:{trials,confirmed,pending,promising,reject}, fields_seen, settings_seen, best_metrics, notes}`。
3. **SoT 回写（唯一通道 `scripts/templates/registry.py`，勿直写 jsonl）**：
   `registry.record_effectiveness(fp, tier_counts, best_metrics, alpha_ids, region, session_id)` —
   lifecycle 晋级（runnable→promising→proven / trials≥8 无正例→demoted）自动发生并 emit
   `template.lifecycle_changed`。
4. **新骨架注册**：fingerprint 不在 catalog（`data/templates/forum_templates.jsonl`）→ 新建 catalog 行
   `H-<region>-<nnn>`（source=harvest；S3 现造的 `generated_first_principles` 实例用 `G-<region>-<nnn>`；
   机制三元组从 hypothesis YAML 继承）+ `registry.upsert(lifecycle="promising")`。
5. emit `template.harvested { skeleton_fingerprint, catalog_id, tier_counts, new_entry }` per distilled skeleton。
6. 再生 coverage ledger：`python scripts/templates/coverage.py --region <R>`。

幂等：靠 `(session_id, skeleton_fingerprint)` 判重 + `.last_ingested_ts.json` sidecar，同 session 重跑不重复累计。

### Step 8. Emit closeout events

- `memory.updated { field_updates, paradigm_updates, new_fingerprints, new_seeds }`
- `session.summary { tiers, budget_used, sims_dispatched, circuit_breaker }`

After these events, the workflow must run self-diagnostic, online learning, and
the continuation gate. A `session.summary` row is not a stop permission for
manual-submit campaigns whose target is still unmet.

## 6. Events emitted

`memory.updated`, `session.summary`

### Trace events emitted (Trace 2.0 schema — see reference/trace-schema-v2.md)

**(a) Aggregate `structural_features` from `hypothesis.proposed`** (or legacy `hypothesis.generated`) events of this session and append to `memory/{region}/structural_features.jsonl`. Keyed by `(dataset, task_type, paradigm)`, accumulating histograms over `n_fields`, `depth` / `operatorCount_estimate`, `k_arity`, and `op_class_hist`. `depth` is retained for schema compatibility but should be interpreted as the project operatorCount estimate unless a true AST depth is explicitly supplied. This is the raw input for `wqb-self-diagnostic`'s structural-entropy attribution analysis.

Schema (one line per session×cell update):
```json
{
  "ts": "<session_end_ts>",
  "session_id": "<sid>",
  "dataset": "earnings2",
  "task_type": "shock",
  "paradigm": "P3",
  "samples": 4,
  "n_fields_hist": {"1": 1, "2": 3},
  "depth_hist": {"3": 1, "4": 2, "8": 1},
  "op_class_totals": {"ts": 5, "cs": 3, "logic": 4}
}
```

Idempotency: keyed by `(session_id, dataset, task_type, paradigm)`; re-running the writer for a session that's already ingested (per `.last_ingested_ts.json`) is a no-op.

**(b) (Phase 4+ only) Persist `dfs_seeds` to `memory/{region}/dfs_seeds.jsonl`.** Whenever a `gate.tier { tier: "PROMISING" | "SUBMITTABLE_PENDING" | "SUBMITTABLE_CONFIRMED" }` is observed, append a seed entry:

```json
{
  "ts": "...",
  "seed_id": "ds-<sid>-<n>",
  "session_id": "<sid>",
  "parent_alpha_id": "<alpha_id>",
  "cell": ["shock", "P6"],
  "fields_used": ["..."],
  "depth_explored": 4,
  "metrics": {"sharpe": 1.42, "fitness": 1.05}
}
```

FIFO cap of 8 active seeds (older entries are kept on disk but not loaded by `wqb-hypothesis-designer` Phase 4 controller).

**(c) Persist zero-order effectiveness.** For every `zfield.generated` that later appears in a `hypothesis.generated.zero_order_provenance`, aggregate outcomes into `memory/{region}/zero_order_effectiveness.jsonl`:

```json
{
  "ts": "<session_end_ts>",
  "session_id": "<sid>",
  "dataset": "insiders12",
  "zfield_id": "z1",
  "raw_fields": ["insd12_positionchangetransactionamount", "insd12_sharesheld"],
  "construction_family": "ratio",
  "trials": 4,
  "best_sharpe": 1.09,
  "best_fitness": 0.60,
  "best_2y_sharpe": 1.66,
  "tiers": {"REJECT": 4, "PROMISING": 0, "SUBMITTABLE_PENDING": 0}
}
```

**(d) Persist attribution patterns.** For each `attribution.generated`, append one idempotent line to `memory/{region}/attribution_patterns.jsonl` keyed by `(session_id, alpha_id)`:

```json
{
  "ts": "<session_end_ts>",
  "session_id": "<sid>",
  "alpha_id": "N1gmpJj7",
  "root_cause_layer": "l1_temporal",
  "likely_exposure": "liquidity",
  "recent_4y_slope": 0.32,
  "pnl_concentration_top_years": 0.73,
  "repair_targets": ["l0_construction"]
}
```

**(e) Persist L1 parent bank.** For each `gate.tier` whose upstream hypothesis has `expression_level: "L1"`, append to `memory/{region}/l1_parent_bank.jsonl` when any positive diagnostic holds: Sharpe > 0.8, 2Y Sharpe > 1.2, sub-universe PASS, Fitness > 0.7 with no failed RA, or S6.5 attribution supports the L0/L1 layer.

```json
{
  "ts": "<session_end_ts>",
  "session_id": "<sid>",
  "dataset": "insiders12",
  "parent_alpha_id": "abc123",
  "zfield_id": "z1",
  "raw_fields": ["field_a", "field_b"],
  "construction_family": "net_direction",
  "l1_operator": "ts_rank",
  "lookback": 189,
  "sign": "positive",
  "neutralization": "STATISTICAL",
  "metrics": {"sharpe": 1.02, "fitness": 0.78, "two_year_sharpe": 1.34},
  "corr": {"prod_corr": 0.42, "self_corr": 0.31},
  "eligible_for_l2": true,
  "failed_l2_axes": []
}
```

S3 loads only recent entries for the current region/dataset and uses this as the L2 improvement queue. Entries with known `prod_corr >= 0.5` or `self_corr >= 0.5` remain useful only if the next variant changes L0 construction or bucket axis family.

**(f) Persist layered strategy-template evidence.** For every hypothesis with `research_rationale` and a downstream `gate.tier`, derive a normalized template key:

```json
{
  "template_id": "<semantic_roles>_<construction_family>_<l1_operator_family>",
  "scope": "dataset|region_category|global",
  "region": "USA",
  "dataset_id": "institutions5",
  "dataset_category": "institutions",
  "semantic_roles": ["source_intensity", "source_confidence"],
  "construction_family": "interaction",
  "l1_operator_family": "ts_zscore",
  "outer_wrapper_policy": "ungated_source_first",
  "research_rationale": {"return_attribution_prior": "...", "economic_mechanism": "...", "statistical_evidence": "...", "signal_processing": "..."},
  "evidence_delta": {"trials": 4, "promising": 0, "submittable": 0, "rejects": 4},
  "attribution_supports_source": false
}
```

Rules:

- Write dataset-local and region/category evidence under `memory/{region}/template_effectiveness.jsonl`（append-only 流水）。
- 跨 region 推广走 SoT：`registry.record_effectiveness` 在 ≥2 region 出正例时自动 promising→proven（`memory/global/strategy_templates.jsonl` 已于 2026-07 删除，职责并入 registry）。
- Do not promote exact field IDs, exact expressions, fingerprints, or forbidden regexes into global memory.
- Do not promote a `trade_when` / threshold template unless ungated source evidence and negative controls are present.

## 7. Constraints

- **Idempotency is sacred**. Running this skill 2× on the same session MUST produce identical `memory/` and `metrics/` state.
- **Never mutate `records/<date>.jsonl`**. Read-only.
- **Never call MCP**.
- **Sidecar write is atomic**: write to `.tmp` file, then `rename()`.
- **Layering precedence**: dataset-local rows dominate region/category rows, which dominate global priors. Global memory is advisory and must never create hard bans or dedup hits.

## 8. Self-validation

- [ ] `.last_ingested_ts.json[session_id]` is monotonically non-decreasing
- [ ] `fingerprints.txt` no duplicate lines
- [ ] `metrics/sessions.jsonl` has exactly one new line per session
- [ ] Multi-dataset sessions have one row per context or an explicit aggregate,
  and `scripts/diagnostic/audit_session_completeness.py` reports no count drift
- [ ] `zero_order_effectiveness.jsonl` is updated when `zfield.generated` events exist
- [ ] `attribution_patterns.jsonl` is updated when `attribution.generated` events exist
- [ ] `l1_parent_bank.jsonl` receives eligible L1 parents for future L2 variants
- [ ] transferable templates, if any, are normalized by semantic roles and promotion criteria; exact expressions remain region-scoped
- [ ] `memory.updated` + `session.summary` events present in records
