---
name: wqb-news-campaign-planner
description: "Create a News-specific campaign plan before the generic field explorer, external scout, zero-order factory, and hypothesis designer run. The plan prevents the agent from treating post-news reaction fields as standalone alpha sources and forces each batch to cover distinct news lifecycle mechanisms. Part of the WorldQuant BRAIN auto-mining workflow (S1.5 / S2 prelude of workflow/news-mining.md; optional overlay in workflow/auto-mining.md when dataset_category == 'News')."
---

# Skill: wqb-news-campaign-planner

**Consumers**: Claude Code / GitHub Copilot / Codex / generic assistants
**Stage**: S1.5 / S2 prelude of `workflow/news-mining.md`; optional overlay in `workflow/auto-mining.md` when `dataset_category == "News"`
**Budget cost**: 0

## 1. Purpose

Create a News-specific campaign plan before the generic field explorer, external
scout, zero-order factory, and hypothesis designer run. The plan prevents the
agent from treating post-news reaction fields as standalone alpha sources and
forces each batch to cover distinct news lifecycle mechanisms.

This skill does not create BRAIN expressions and never calls simulation tools.

## 2. Inputs

```yaml
dataset_id: "news54"
dataset_category: "News"
region: "USA"
universe: "TOP3000"
delay: 1
dataset_snapshot:
  name: "Key Developments Data"
  description: str
  subcategory: "News Sentiment"
  field_count: 41
  alpha_count: 325
field_snapshot:
  - id: "key_development_sentiment_score"
    description: str
    type: MATRIX | VECTOR | GROUP
external_cards_existing:
  - card_id: str
    source_type: str
    l0_construction_hint: object
memory_snapshot:
  recent_news_slots:
    news_momentum: {trials: 0, promising: 0, submittable: 0}
constraints:
  max_fields_per_candidate: 3
  max_operatorCount_estimate: 8
  no_simulation: true
```

## 3. Outputs

```yaml
news_campaign_plan:
  dataset_id: "news54"
  dataset_family: sentiment_relevance | key_development | post_event_reaction | deal_event | transcript_story | identifier_mapping | model_transfer | unknown
  source_layer_policy: source_first | source_proof_required | mapping_only_skip | hard_event_streams
  lifecycle_slots:
    - slot: news_momentum
      priority: 0.80
      required_roles: [sentiment_or_event_direction, relevance_or_significance]
      allowed_l0_families: [intensity, interaction]
      horizon_grid: [5, 21, 63]
  field_role_overrides:
    field_id:
      role_type: standalone | context_gate | bucket_axis | post_event_reaction | source_proof_helper | mapping_only
      likely_false_proxy: none | liquidity | coverage | size | post_event_reaction | reporting_frequency | unknown
      source_layer_note: str
  companion_policy:
    allowed: [returns, volume, adv20, cap, subindustry]
    require_effective_pyramids: true
  source_proof_gate:
    enabled: true
    min_sharpe: 1.25
    min_fitness: 0.70
    require_sub_universe_pass: true
    require_no_failed_ra_checks: true
  external_source_plan:
    source_types: [forum, paper, qlib, tradingview, quantconnect, market_data]
    required_lifecycle_slots: [news_momentum, reaction_speed, novel_hard_event]
    max_cards: 24
  first_batch_blueprint:
    required_slots: [news_momentum, delayed_negative, novel_hard_event, reaction_speed]
    forbidden_until_source_proof: [wrapper_sweep, pure_reaction_pair, bucket_neutralization_repair]
  stop_rules:
    max_children_without_source_proof: 20
    max_same_slot_empty_batches: 3
```

## 4. Tools used

No MCP tools are required when `dataset_snapshot` and `field_snapshot` are
available. If missing, the workflow may fetch them before invoking this skill
with `get_datasets` and `get_datafields`.

Prefer the deterministic local planner whenever cached metadata exists:

```bash
python scripts/news/campaign_planner.py plan \
  --dataset-id <dataset_id> \
  --region <region> \
  --universe <universe> \
  --delay <delay> \
  --output data/news_campaign_plans/<region>/<dataset_id>.json
```

The script writes `data/news_campaign_plans/<region>/<dataset_id>.json`, then
the agent reviews the family, slot mix, and field-role overrides against the
playbook before passing the plan to downstream stages.

If the script exits with code `2` or writes
`planning_status: blocked_missing_field_metadata`, the plan is not executable.
Refresh `data/platform/<dataset_id>_datafields.json` through `get_datafields` or
Phase 0 bootstrap before S2/S2.5/S3. Do not use `--allow-missing-fields` except
to write an audit artifact; that flag must not unblock simulation.

This skill reads:

- `reference/news-category-playbook.md`
- `reference/<dataset_id>-playbook.md` if present
- `data/platform/datasets_<region>_D<delay>_<universe>.json` if present
- `data/platform/<dataset_id>_datafields.json` if present
- `data/external_hypotheses/seeds/news_category_raw.jsonl` for seed-card source
  coverage
- recent `memory/{region}/*.jsonl`

## 5. Steps

### Step 1. Load News playbook

Read `reference/news-category-playbook.md`. If a stricter dataset-specific
playbook exists, such as `reference/news12-playbook.md`, apply it after the
category playbook.

### Step 2. Classify dataset family

Use dataset name, description, subcategory, and field descriptions:

- sentiment/relevance words -> `sentiment_relevance`
- key development/significant/corporate event words -> `key_development`
- price/volume/VWAP/minute/session/post-event dominated -> `post_event_reaction`
- M&A/deal/proceeds/premium/status -> `deal_event`
- conference call/transcript/story section -> `transcript_story`
- mapping/identifier/RIC/BBID only -> `identifier_mapping`
- DNN/transfer/model sentiment -> `model_transfer`

When multiple labels apply, choose the stricter policy:
`identifier_mapping` > `post_event_reaction` > `key_development` >
`sentiment_relevance` > `model_transfer`.

If `scripts/news/campaign_planner.py` was used, treat its classification as the
machine baseline. Dataset-family rows from `reference/news-category-playbook.md`
are hard overrides when field metadata is missing or ambiguous. Unknown family
is conservative: run source-proof only and block wrapper sweeps.

### Step 3. Override field roles

Assign `field_role_overrides` for fields likely to mislead generic ranking:

- reaction fields become `context_gate`, `bucket_axis`, or `post_event_reaction`
- relevance/significance fields become gates or interaction weights
- sentiment/tone fields may be standalone only when not obviously reaction-only
- identifier fields become `mapping_only`

### Step 4. Choose lifecycle slot mix

Select at least four starting slots from the category playbook. Default mix:

1. `news_momentum`
2. `delayed_negative`
3. `novel_hard_event`
4. `reaction_speed`

For post-event datasets, replace one slot with `overreaction` and enable the
source-proof gate. For identifier-only datasets, emit `mapping_only_skip`.

### Step 5. Define external scout plan

Pass `external_source_plan` to `wqb-external-hypothesis-scout`. For News, require
at least one paper-backed card and one forum-backed card when sources exist.
Prioritize cards that map to one of the selected lifecycle slots.

Cold-start campaigns should first normalize the seed file:

```bash
python scripts/external/hypothesis_scout.py normalize \
  --input data/external_hypotheses/seeds/news_category_raw.jsonl \
  --dataset-id <dataset_id> \
  --region <region> \
  --output data/external_hypotheses/<region>/<dataset_id>.jsonl \
  --max-cards 24
```

### Step 6. Define stop rules

Use the playbook stop rules. If the dataset-specific playbook is stricter, use
the stricter rule.

## 6. Events emitted

The workflow should emit:

```json
{
  "kind": "news.campaign_planned",
  "payload": {
    "dataset_id": "news54",
    "dataset_family": "key_development",
    "source_layer_policy": "hard_event_streams",
    "lifecycle_slots": ["news_momentum", "delayed_negative", "novel_hard_event", "reaction_speed"],
    "source_proof_required": false,
    "external_source_types": ["forum", "paper", "qlib", "tradingview", "quantconnect", "market_data"],
    "stop_rules": {"max_children_without_source_proof": 20}
  }
}
```

If the trace schema has not yet been upgraded for `news.campaign_planned`, emit
the same payload inside `scope.started.news_campaign_plan` or
`external.consulted.notes` until the schema is updated.

## 7. Constraints

1. Never call `create_simulation` or `create_multi_simulation`.
2. Never generate alpha expressions directly.
3. Never let post-event reaction fields enter L2 repair before source-proof.
4. Do not use external TradingView/Qlib/QuantConnect code directly; only use
   mechanism summaries and BRAIN-mappable observables.
5. Keep companion fields explicit and record `effective_pyramids`.
6. Prefer lifecycle diversity over operator diversity for the first News batches.
7. A plan with `field_count: 0` or `planning_status != "ready"` blocks S2/S3
   simulation. Fetch field metadata first; do not rely on dataset names alone.
8. Novelty/count/days/source/relevance fields are helpers, gates, or axes until
   paired with a signed source. Do not label them standalone return sources just
   because the field name also contains `score`.

## 8. Self-validation

- [ ] `dataset_family` is assigned and justified by descriptions
- [ ] every shortlisted field has a role or inherits a clear default
- [ ] lifecycle slots cover at least two mechanisms
- [ ] post-event datasets have `source_proof_gate.enabled=true`
- [ ] external source plan includes both forum and paper when available
- [ ] stop rules are present
