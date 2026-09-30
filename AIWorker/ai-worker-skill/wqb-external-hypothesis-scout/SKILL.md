---
name: wqb-external-hypothesis-scout
description: "Convert external research sources into structured, BRAIN-mappable hypothesis cards so the mining loop has a steady supply of diverse ideas without blindly copying outside strategies. Part of the WorldQuant BRAIN auto-mining workflow (S2.2 of workflow/auto-mining.md (after field scan, before zero-order field factory))."
---

# Skill: wqb-external-hypothesis-scout

**Consumers**: Claude Code / GitHub Copilot / Codex / generic assistants
**Stage**: S2.2 of `workflow/auto-mining.md` (after field scan, before zero-order field factory)
**Budget cost**: 0 (no simulation; external consultation is recorded with `budget_charged=0`)

## 1. Purpose

Convert external research sources into structured, BRAIN-mappable hypothesis cards so the mining loop has a steady supply of diverse ideas without blindly copying outside strategies.

External sources are inspiration only. A card is accepted only when it can be mapped to available BRAIN observables and later turned into an L0/L1 candidate by `wqb-zero-order-field-factory` and `wqb-hypothesis-designer`.

## 2. Inputs

```yaml
dataset_id: "news18"
dataset_category: "News"
region: "USA"
delay: 1
shortlist:
  - field_id: str
    description: str
    type: MATRIX | VECTOR | GROUP
    semantic_role: str
low_coverage_cells:
  - [task_type, paradigm]
source_plan:
  source_types: [forum, paper, qlib, tradingview, quantconnect, market_data]
  max_fetches: 4
  max_cards_per_source: 3
memory_snapshot:
  fingerprints: set
  recent_external_cards: list
news_campaign_plan:  # required when dataset_category == "News"
  lifecycle_slots: list
  external_source_plan: object
  dataset_family: str
constraints:
  no_simulation: true
  no_direct_copy: true
```

## 3. Outputs

```yaml
external_hypothesis_cards:
  - card_id: "eh_news18_001"
    source_type: paper | forum | qlib | tradingview | quantconnect | market_data | web
    source_ref: "The Momentum of News"
    source_url: "https://..."
    source_title: str
    claim: "Positive firm-level news sentiment persists and may predict short-horizon returns."
    market_mechanism: "Investors underreact to persistent public information."
    horizon: intraday | short | medium | long | regime
    required_observables: ["sentiment", "relevance", "returns"]
    brain_field_candidates: ["rp_css_earnings", "nws18_relevance", "returns"]
    brain_mapping:
      mapped: true
      missing_observables: []
      mapping_notes: "sentiment and relevance exist in news18; returns comes from pv1."
    l0_construction_hint:
      family: interaction | spread | ratio | surprise | residual | gate | covariance | regime
      sketch: "sentiment * high_relevance_gate"
      expected_direction: positive | negative | unknown
    news_lifecycle_slot: news_momentum | delayed_negative | overreaction | silence_after_stress | novel_hard_event | sentiment_divergence | attention_spillover | reaction_speed | null
    task_type: level | change | shock | persistence
    paradigm: P1 | P2 | P3 | P4 | P5 | P6 | P7 | P8 | P9 | P10 | P11 | P12 | P13
    direction_type: reversal | continuation | undecided
    role_type: standalone | confirmation | interaction | gating | unknown
    risks: ["crowded news sentiment", "coverage proxies size/liquidity"]
    source_confidence: 0.0
    mapping_confidence: 0.0
    novelty_score: 0.0
    priority_score: 0.0
    fingerprint: "sha256-16"
```

Artifacts:

- `data/external_hypotheses/<region>/<dataset_id>.jsonl`
- optional `data/external_hypotheses/<region>/<dataset_id>-summary.json`
- reusable News seed input: `data/external_hypotheses/seeds/news_category_raw.jsonl`
- `external.consulted` records only when a forum/web/docs/glossary fetch actually happened through `scripts/external/consult.py`

## 4. MCP and web tools

This skill may consult external sources, but never directly simulates or submits.

- BRAIN forum: `search_forum_posts`, `read_forum_post`, then cache through `scripts/external/consult.py`
- Official/project docs: local files first; optional docs lookup through existing workflow rules
- Public web: search only for research/background; distill into cards, do not copy proprietary strategy code
- Local deterministic normalization: `python scripts/external/hypothesis_scout.py normalize ...`

## 5. Steps

### Step 0. Hard-gate trigger check (added 2026-05-08, Phase 3)

Run this skill in **MUST mode** if any of the following holds; otherwise it remains SHOULD (best-effort coverage). Trigger condition is recorded as `triggered_by_gap` on every emitted `external.consulted` event.

| Trigger | Detection | `triggered_by_gap` value |
|---|---|---|
| **Cold-start** | `wc -l memory/{region}/hypothesis_registry.jsonl < 5` | `cold_start` |
| **Claim exhaustion** | ≥ 2 consecutive batches in this session emit hypotheses with `claim` cosine similarity > 0.85 vs the registry's last 50 claim strings | `exhausted_claim_pattern` |
| **Paradigm gap** | S2.1 `research_gap.scanned.gaps.paradigm_under_explored` is non-empty (any P_id with `trials < 3` for the active dataset_category) | `cold_paradigm_<P_id>` |
| **User request** | `--external-scout` CLI flag or explicit user instruction | `manual` |

When MUST: run **at least one** `consult.py fetch` call per active gap dimension. arxiv + brain_forum first; tradingview / quantconnect / ssrn return stub responses (Phase 4+ implementation). When SHOULD: skip; emit `external.consulted.skipped { reason: "no_gap_detected" }` for auditability.

```bash
# Example: paradigm gap on P10
python3 scripts/external/consult.py fetch \
  --source arxiv --query "post-news underreaction reversal volume" \
  --stage S2 --session-id "$SID" --triggered-by-gap "cold_paradigm_P10"
```

### Step 1. Choose source mix

Pick sources to fill diversity gaps, not to chase popularity.

Default quotas per scout pass:

| source_type | role |
|---|---|
| `forum` | platform idioms, operator pitfalls, dataset-specific tricks |
| `paper` | economic mechanism and horizon |
| `qlib` | feature families, ML factor shapes, market-dynamics tests |
| `tradingview` | technical pattern archetypes, entry/exit/gating logic |
| `quantconnect` | implementable academic strategy templates |
| `market_data` | current regime, volatility, liquidity, macro stress context |

Use `reference/external-hypothesis-sources.md` when source selection or reuse rules are unclear.

For `dataset_category == "News"`, also read `reference/news-category-playbook.md` and the optional `news_campaign_plan`. The accepted card must map to at least one active News lifecycle slot such as `news_momentum`, `delayed_negative`, `novel_hard_event`, `sentiment_divergence`, `attention_spillover`, or `reaction_speed`.

For a cold-start News dataset, begin with
`data/external_hypotheses/seeds/news_category_raw.jsonl`, then add fresh
forum/web cards only for lifecycle slots that are still under-covered.

For `region == "GLB"`, use `reference/GLB-mining-playbook.md` before source
selection. The scout is mandatory for the first GLB production batch unless a
fresh `data/external_hypotheses/GLB/<dataset_id>.jsonl` file already exists.
The GLB source mix must include:

1. BRAIN forum GLB transfer / field-similarity / country-cohort evidence;
2. at least two of paper, qlib, tradingview, or quantconnect;
3. any available same-field or similar-field evidence from USA / ASI / EUR
   memory, submitted-alpha caches, or platform field descriptions.

Each accepted GLB card should tag one provenance path in `notes`:
`cross_region_transfer`, `same_field_migration`, `similar_field_replacement`,
or `public_strategy_archetype`.

### Step 2. Distill source into hypothesis cards

For each source, extract only:

1. market claim
2. mechanism
3. horizon
4. required observables
5. possible BRAIN field mapping
6. L0 construction hint
7. failure mode

Do not paste full Pine scripts, Qlib code, or paper text into cards. Use short summaries and URLs.

### Step 3. Map to BRAIN observables

Reject or mark `mapped=false` if the idea needs data unavailable in BRAIN.

Mapping rules:

- A TradingView moving-average/breakout idea maps to BRAIN price-volume observables (`returns`, `close`, `volume`, `adv20`) only if the dataset campaign allows those as companion fields.
- A paper about news underreaction maps to news sentiment/relevance plus returns/volume; if no sentiment/relevance fields exist, keep it as unmapped background.
- A GLB transfer idea maps only when the current GLB field id exists or the
  field description is semantically equivalent to the faster-region source
  field. Similarity by name alone is not enough.
- A GLB country/cohort idea maps to `group_cartesian_product(country, axis)` or
  a country-crossed bucket only when the axis field is available and has a
  written cohort hypothesis.
- For News cards, assign `news_lifecycle_slot` and reject the card for downstream use if it cannot map to an active campaign slot.
- Qlib `Alpha158`/`Alpha360` features map to generic price-volume L0/L1 shapes, not to Qlib labels or trained models.
- Real-time market/regime data maps to gates or source-priority changes; it is not a direct BRAIN expression input unless a platform field exists.

### Step 4. Normalize, score, and deduplicate

Write raw cards to a temp JSONL file, then run:

```bash
python scripts/external/hypothesis_scout.py normalize \
  --input <raw_cards.jsonl> \
  --dataset-id <dataset_id> \
  --region <region> \
  --output data/external_hypotheses/<region>/<dataset_id>.jsonl \
  --max-cards 24
```

The script:

- validates required fields and enums
- computes a stable fingerprint
- drops duplicate fingerprints already present in the output file
- scores mapped, diverse, high-confidence cards higher
- writes normalized JSONL plus a summary JSON

### Step 5. Feed downstream stages

Pass accepted cards to S2.5 as `external_hypotheses`.

`wqb-zero-order-field-factory` should use the cards to bias L0 construction families, not to bypass its own field-role checks. `wqb-hypothesis-designer` may attach the card as `external_evidence` when generating a hypothesis.

## 6. Constraints

1. No simulation, no `create_multi_simulation`, no `create_simulation`.
2. No `submit_alpha` or `set_alpha_properties`.
3. No direct copy of external strategy code into a BRAIN expression.
4. Every accepted card must have `claim`, `market_mechanism`, `required_observables`, `brain_field_candidates`, `l0_construction_hint`, `risks`, and a BRAIN mapping decision.
5. At least three `source_type` values should be represented when `max_cards >= 8` and sources are available.
6. At least two `task_type` and two `paradigm` values should be represented when `max_cards >= 8`.
7. Treat external data as hypothesis evidence, not platform truth. Platform truth still comes from BRAIN simulations, checks, correlations, and submitted-alpha outcomes.
8. For GLB, direct cold-start simulation without a scout result must be recorded
   as `glb.transfer_scout.skipped` with a reason and should be limited to
   source-validation batches.

## 7. Self-validation

- [ ] `data/external_hypotheses/<region>/<dataset_id>.jsonl` exists or the skill reports `no_accepted_cards`
- [ ] every card has a fingerprint and `priority_score`
- [ ] no duplicate fingerprint was appended
- [ ] no card uses external-only data as if it were a BRAIN field
- [ ] source mix and task/paradigm mix are summarized
- [ ] any external fetch was recorded through `external.consulted` with `budget_charged=0`
