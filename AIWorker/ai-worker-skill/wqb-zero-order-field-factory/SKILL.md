---
name: wqb-zero-order-field-factory
description: "> Role (2026-07 template-first restructure): field-slot filling subroutine, not a candidate-generation core. > Template selection comes first (reference/template-standard.md §2: field slot = S2 carrier shortlist). > Given ONE template's field slot plus the S2 carrier shortlist, this skill emits ≤ 4… Part of the WorldQuant BRAIN auto-mining workflow (subroutine of S2.5 / S3 (workflow/auto-mining.md) — invoked by template instantiation & transfer, never standalone)."
---

# Skill: wqb-zero-order-field-factory

**Consumers**: Claude Code · GitHub Copilot · Codex · generic assistants
**Stage**: subroutine of S2.5 / S3 (`workflow/auto-mining.md`) — invoked by template instantiation & transfer, never standalone
**Budget cost**: 0

## 1. Purpose

> **Role (2026-07 template-first restructure): field-slot filling subroutine, not a candidate-generation core.**
> Template selection comes first (`reference/template-standard.md` §2: field slot = S2 carrier shortlist).
> Given ONE template's field slot plus the S2 carrier shortlist, this skill emits **≤ 4 economically
> meaningful L0 composite carriers** (two-field constructions: net_direction / surprise / intensity /
> interaction / dispersion) for the S2.5 instantiation step and `scripts/template_transfer.py` to substitute
> into that slot. It does not choose templates, datasets, paradigms, or drive S3 slots on its own.

Call it when a template slot wants a *composite* carrier (opposed pair, surprise, scaled intensity) instead
of a raw field, or when every raw carrier in the shortlist is crowded / sign-ambiguous. If a raw carrier
satisfies the slot, skip this skill and emit `zfield.skipped { reason: "raw_carrier_sufficient" }`.

**Gate note**: the S2.5 hard gate is **`template.selected` OR `zfield.generated` — either one satisfies it**.
The old rule "S3 must start from an L0 pack" is retired; this skill is a fallback/subroutine path.

## 2. Inputs

```yaml
template_ref:                 # the template whose field slot is being filled
  catalog_id: str             # T-/H-/G- id (template-standard §1)
  skeleton_fingerprint: str
  slot_name: str              # e.g. field1
dataset_id: str
dataset_category: str
region: str
delay: 1
shortlist:                    # S2 carrier shortlist (≤40, submitted-overlap-locked)
  - {field_id, description, type: MATRIX|VECTOR|GROUP, coverage, alphaCount, submitted_overlap}
news_campaign_plan: {}        # optional; News datasets only (source-proof policy)
constraints: {max_raw_fields: 3, preferred_raw_fields: 2, max_outputs: 4}
```

No MCP calls. If field descriptions are missing, return `needs_field_descriptions: true` — never guess.

## 3. Outputs (≤ 4 candidates)

```yaml
zero_order_fields:
  - zfield_id: z1
    expression: "divide(vec_min(insd12_positionchangetransactionamount), abs(vec_sum(insd12_sharesheld)) + 1)"
    raw_fields: ["insd12_positionchangetransactionamount", "insd12_sharesheld"]
    construction_family: spread | ratio | surprise | intensity | interaction | dispersion | bucket_axis | vector_pair
    two_field_construction_mode: <8-value enum, reference/two-field-construction-contract.md>
    l0_economic_role: spread | disagreement | confirmation | horizon_mismatch | scale | surprise | confidence_weight | cohort_residual | negative_control
    anomaly_class: <canonical enum, reference/submission-gates.md §11>   # batch-runner reject gate; "unclassified" only with ablation_baseline: true
    cohort_axis_field: null | str          # bucket/group axis field — not counted as a source field
    economic_hypothesis: "Insider sell pressure is meaningful only relative to remaining holdings."
    expected_direction: positive | negative | unknown   # unknown → paired sign test required downstream
    false_positive_risks: ["tax/liquidity motivated sales", "sparse coverage → liquidity proxy"]
    l0_pack_slot: net_direction | surprise | intensity | interaction | dispersion
    bucket_axis_candidates:                # optional L2 ingredients, never standalone alphas
      - {axis_family: "ownership_intensity", expression: "bucket(rank(vec_sum(insd12_sharesheld)), range=\"0.1,1,0.1\")", cohort_logic: "..."}
    source_proof_required: false           # true for News post-event context L0s (§4 Step 3)
    template_ref: {catalog_id, skeleton_fingerprint, slot_name}
```

## 4. Method

### Step 1 — Classify field roles (descriptions, not just IDs)

| Role | Description clues | Slot use |
|---|---|---|
| direction | buy/sell, call/put, sentiment polarity | numerator / signed spread |
| scale | shares, cap, assets, volume, holdings | denominator / bucket axis |
| expectation / outcome | estimate, forecast / actual, reported | surprise formula |
| confidence | count, relevance, coverage | gate / weight / bucket |
| categorical | rating, transaction code | bucket/gate only after distribution check |

Ambiguous direction → `expected_direction: unknown` + force reverse/sign control in the instantiated batch
(铁律 2). Attach `anomaly_class` from the canonical enum in `reference/submission-gates.md §11`.

### Step 2 — Build ≤ 4 targeted composites

Emit only formulas with a real economic sentence, chosen to fit the template slot (not a broad pack):

1. **Spread / net direction**: `subtract(A, B)` — mandatory when obvious opposed pairs exist (call/put, buy/sell, upgrade/downgrade, positive/negative).
2. **Ratio / intensity**: `divide(A, abs(B) + 1)`.
3. **Surprise**: `divide(subtract(actual, expected), abs(expected) + 1)`.
4. **Interaction**: `direction × confidence`, e.g. `multiply(rank(A), rank(conf))`.
5. **Dispersion**: `abs(A - B)` or `vec_stddev(A)`.

Classify each under the 8-value `two_field_construction_mode` enum of
`reference/two-field-construction-contract.md` (`math_relation` / `pairwise_operator` / `custom_group_axis` /
`main_aux_complement` / `horizon_complement` / `conditional_regime_gate` / `composite_cohort_axis` /
`vector_field_pairing`) and tag `l0_economic_role`. Cohort/bucket axes go in `cohort_axis_field` +
`bucket_axis_candidates` and do **not** count as source fields.

Minimal positive example: `call_field - put_field` → family=spread, role=spread, hypothesis "net call-minus-put
demand proxies directional option pressure", risks ["hedging demand may invert sign", "low option liquidity ∝ size"].
Minimal negative example (reject): `multiply(sharesout, volume)` — two scale variables, hypothesis survives
replacing every field name with "something"; no identifiable expected-return sign.

### Step 3 — News source-proof overlay (kept)

Trigger: `dataset_category == "News"` and selected fields are mostly post-event price/volume/session context,
OR `news_campaign_plan.source_layer_policy == "source_proof_required"`.

- Post-event reaction / session / volume fields are **context_gate / bucket_axis ingredients, not independent
  sources**: tag `source_proof_required: true`, use them only as gates, weights, or cohort axes.
- Pure two-News reaction L0s are controlled ablations (`ablation_baseline: true`) until a source-proof parent
  exists; pair one News context field with a companion (`returns` etc.) instead.
- Only explicit ex-ante sentiment / forecast / source-confidence fields qualify as possible sources.

### Step 4 — VECTOR handling (kept)

Collapse every VECTOR input before scalar arithmetic: `vec_avg / vec_sum / vec_min / vec_max / vec_count /
vec_stddev`. Never emit scalar `multiply(A, B)` on raw VECTOR inputs; never use `filter(x, h, t)` as a boolean
vector selector — collapse first, then gate the scalar with `if_else` / `greater` / `less` / `nan_mask` / `clamp`.

### Step 5 — Score and cut to ≤ 4

Keep a candidate only if it has: a clear economic direction (or is a declared sign test), scale normalization
where the raw level is a size proxy, a falsifiable failure mode, and a hypothesis that mentions the actual
economic roles (reject "something-vs-something" hypotheses). If all shortlist fields are scale/cadence
variables with no signed source, return `needs_companion_fields: true` and emit `zfield.skipped
{ reason: "no_signed_source" }` instead of fabricating a weak composite.

### Step 6 — Emit events

One `zfield.generated` per emitted candidate:

```json
{"kind": "zfield.generated", "payload": {"dataset_id": "...", "zfield_id": "z1", "expression": "...",
 "raw_fields": ["A","B"], "construction_family": "ratio", "l0_pack_slot": "intensity",
 "l0_economic_role": "scale", "economic_hypothesis": "...", "expected_direction": "negative",
 "template_ref": {"catalog_id": "...", "skeleton_fingerprint": "...", "slot_name": "field1"}}}
```

When the skill is bypassed or aborts: `zfield.skipped { template_ref, slot_name, reason:
raw_carrier_sufficient | no_signed_source | needs_field_descriptions }`.

## 5. Constraints

- **≤ 4 outputs per invocation**, each bound to the given `template_ref` slot.
- Prefer exactly 2 raw fields; 1 only as `ablation_baseline: true`; 3 only when the third is a clear
  denominator / confidence gate / regime bucket. Hard cap 3 raw fields (铁律 5).
- No simulation; no candidate without `economic_hypothesis` + `false_positive_risks`.
- Bucket-axis candidates are L2 ingredients with `cohort_logic`, never standalone alphas.
- High-alphaCount public fields: pair components / denominators / cohort axes only, not standalone sources.

## 6. Self-validation

- [ ] ≤ 4 candidates, every one carries `template_ref` with the slot being filled
- [ ] Every VECTOR raw field collapsed with `vec_*` before scalar arithmetic
- [ ] Every candidate has `two_field_construction_mode`, `l0_economic_role`, `expected_direction`, `false_positive_risks`
- [ ] News post-event fields only appear as context_gate / bucket_axis unless a source-proof parent exists
- [ ] `zfield.generated` or `zfield.skipped` emitted (S2.5 gate: `template.selected` OR `zfield.generated`)
