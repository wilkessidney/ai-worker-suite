---
name: wqb-field-family-scout
description: "Discover transferable field-family ideas before ordinary dataset-local field ranking. This skill prevents the workflow from depending on forum posts to find ideas such as nip fields in News/PV datasets, where the real hypothesis is a joint pattern: Part of the WorldQuant BRAIN auto-mining workflow (S1.6 / S2 prelude of workflow/auto-mining.md)."
---

# Skill: wqb-field-family-scout

**Consumers**: Claude Code / GitHub Copilot / Codex / generic assistants
**Stage**: S1.6 / S2 prelude of `workflow/auto-mining.md`
**Budget cost**: 0

## 1. Purpose

Discover transferable field-family ideas before ordinary dataset-local field
ranking. This skill prevents the workflow from depending on forum posts to find
ideas such as `nip` fields in News/PV datasets, where the real hypothesis is a
joint pattern:

```text
field_family x operator_family x neutralization/settings x region/delay
```

The output is a hypothesis seed, not an alpha expression. It feeds S2, S2.5,
and S3 so the normal simulation, RA, correlation, robustness, and overfit gates
remain authoritative.

**Two run modes** (v0.2, 2026-06-01):

- **Responder mode** — `family_token` is supplied (user named a family, or a
  prior stage already chose one). Behaves as before.
- **Autonomous mode** — `family_token` is *not* supplied. The skill discovers
  *which* family to scout by itself, using
  `reference/category-template-transfer-map.md`. This is the fix for the
  root cause behind the forum-dependence: the scout used to require the answer
  (`family_token: "nip"`) as input, so the discovery move ("attack the news
  pyramid via the `nip` family because the sentiment template transfers") had
  to come from a human. Autonomous mode performs that discovery move itself.

## 2. Inputs

```yaml
region: "USA" | "EUR" | ...
universe: "TOP3000" | "TOP2500"
delay: 1
family_token: "nip"        # OPTIONAL. If absent -> autonomous mode (see §5 Step 0).
description_token: "news impact projection"  # OPTIONAL; derived in autonomous mode
mode: responder | autonomous   # inferred: autonomous iff family_token is empty
dataset_scope: []          # optional list; empty means scan cached platform field files
target_category: null      # autonomous mode: the under-lit dataset_category to attack (G)
source_category: null      # autonomous mode: the adjacent lit category whose template transfers (S)
transfer_id: null          # autonomous mode: chosen unit from category-template-transfer-map §2
field_metadata_sources:
  - data/platform/*_datafields.json
  - optional MCP get_datafields(search=<family_token>, filter_sharpe=false) results
transfer_map: reference/category-template-transfer-map.md   # autonomous-mode driver
memory_snapshot:
  - memory/{region}/template_effectiveness.jsonl
  - memory/{region}/structural_features.jsonl
  - memory/{region}/lesson_candidates.jsonl
constraints:
  no_simulation: true
  no_submission: true
```

## 3. Outputs

```yaml
field_family_seed:
  family_token: "nip"
  semantic_definition: "news impact projection"
  region: "USA"
  delay: 1
  datasets:
    news18:
      count: 21
      top_fields: [rp_nip_earnings, rp_nip_ratings, ...]
  hypothesis_seed:
    claim: "Projected post-news market impact may predict delayed absorption or reversal."
    brain_field_candidates: []
    candidate_operator_families: [pairwise_time_series, residual_purification, cohort_relative]
    candidate_templates:
      - "ts_corr(<family_field>, returns, <window>)"
      - "ts_covariance(<family_field>, returns, <window>)"
      - "ts_regression(returns, <family_field>, <window>, lag=0, rettype=2)"
    settings_prior:
      neutralization_candidates: [FAST, INDUSTRY, SECTOR]
      decay_candidates: [4, 6, 8, 12]
      windows: [20, 60, 120]
    validation_batch_type: focused_family_probe
```

Artifacts:

- `data/field_family_scout/<region>_D<delay>_<family_token>.json`
- optional `field_family.scouted` event in `records/<date>.jsonl`

## 4. Tools Used

Local deterministic script:

```bash
python scripts/field_family_scout.py \
  --region <REGION> --universe <UNIVERSE> --delay <DELAY> \
  --family-token <TOKEN> \
  --description-token "<TEXT>"
```

If a target dataset is missing from `data/platform/`, use MCP
`get_datafields(region, universe, delay, dataset_id=<id>, search=<token>,
filter_sharpe=false)` and pass the saved JSON through `--extra-fields`.

## 5. Steps

### Step 0. Autonomous family discovery (only when `family_token` is empty)

This is the move that used to require a human (or a forum post) to supply the
answer. Run `reference/category-template-transfer-map.md §3` deterministically:

1. Identify the under-lit **target category G** for this region/delay: a
   `dataset_category` with no `proven`/`promoted` skeleton in
   `memory/{region}/template_effectiveness.jsonl` (or `alphaCount < 3` when
   pyramid coverage is available). USA/EUR do not expose pyramid coverage by
   default (CLAUDE.md forbids `get_pyramid_*`), so use the memory-coverage
   degradation in transfer-map §3.
2. Find G's cluster-adjacent **lit source category S** in transfer-map §1 — a
   category in the same cluster that *does* have a `proven`/`promoted` skeleton
   in this region.
3. Pick the transferable template unit `transfer_id` for edge `(S→G)` from
   transfer-map §2 (or synthesize a `generated_first_principles` unit from the
   cluster's shared L1 operator family + neutralization prior when §2 has none).
   A cross-cluster edge is allowed only with a non-empty `transfer_rationale`.
4. **Enumerate candidate `family_token`s inside G's datasets** by clustering the
   field ids / descriptions of G's cached datafields into semantic tokens (e.g.
   News → `nip`, `css`, `ess`, `relevance`, `volume`). The top tokens that can
   carry the chosen `transfer_id` operator family become the families to scout.
   This replaces the missing human input.
5. Emit `template.transfer_proposed { region, target_category, source_category,
   edge, transfer_id, candidate_family_tokens, transfer_rationale }` to
   `records/<date>.jsonl`, then run Steps 1-6 below once **per** chosen
   `family_token` (cap 2 families/session per transfer-map §3).

If Step 0 finds no under-lit category with a lit adjacent source, emit
`template.transfer_proposed { skipped: true, reason }` and fall back to ordinary
dataset-local S2 ranking — autonomous mode never blocks the pipeline.

### Step 1+. Scout a single family (both modes)

1. Scan cached platform datafield files and optional MCP field snapshots.
2. Match field ids and descriptions by token and semantic phrase.
3. Group matches by dataset, category, region, delay, field type, alphaCount,
   and userCount.
4. Infer compatible operator families from the family definition:
   - impact/projection/sentiment fields -> `pairwise_time_series`,
     `residual_purification`, `cohort_relative`
   - count/coverage fields -> `coverage_intensity`, `cohort_relative`
   - positive/negative paired fields -> `spread`, `sentiment_divergence`
5. Emit a focused-family seed for downstream construction.
6. In S3, allow one `focused_family_probe` exact-4 batch to reuse the same
   field family and settings family, provided children vary by at least three
   of: field subtype, operator (`ts_corr`/`ts_covariance`/`ts_regression`),
   window, sign/control, cohort axis.

## 6. Constraints

1. Never call simulation, submit, or property tools.
2. Do not treat the seed as platform truth; only simulations and RA checks
   validate it.
3. Do not bypass self-correlation or production-correlation gates.
4. A focused-family probe is allowed to relax batch-local skeleton diversity
   only for one source-validation batch. It must not be used for blind wrapper
   sweeps after the family source fails.
5. If cached fields are incomplete, explicitly mark `metadata_incomplete=true`
   and refresh target datasets with `get_datafields` before budget spending.

## 7. Self-Validation

- [ ] Output file exists and has `match_count > 0`, or a clear no-match reason.
- [ ] Every candidate field id came from platform metadata.
- [ ] The seed includes operator families, templates, settings prior, and risks.
- [ ] S3 candidates generated from the seed remain exact-4 and pass normal
      forbidden, ghost-op, fingerprint, RA, self-corr, and prod-corr gates.
