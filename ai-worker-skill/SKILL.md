---
name: ai-worker-skill
description: Portable skill documents for BRAIN alpha research workflow
---

# Skills Index

Portable skill documents. Read by Claude Code, GitHub Copilot, OpenAI Codex, and any other LLM coding assistant. Each file is pure markdown — no frontmatter, no language-specific wrappers.

## Invocation convention

All skills follow the same schema:

```
# Skill: wqb-<name>

**Consumers**: Claude Code · GitHub Copilot · Codex · generic assistants
**Stage**: S{n} of workflow/auto-mining.md
**Budget cost**: {0 | N child sims via create_multi_simulation}

## Purpose
## Inputs (YAML)
## Outputs (YAML)
## MCP tools used (bare names)
## Steps (numbered)
## Events emitted (records/<date>.jsonl kinds)
## Constraints (hard rules)
## Self-validation checklist
```

## Stage → skill mapping

| Stage | Skill file | Budget |
|---|---|---|
| S0 bootstrap | `workflow/bootstrap.md` (not a skill — run once) | 0 |
| S1 scope | inline in workflow | 0 |
| S1.5 news campaign planner | `wqb-news-campaign-planner.md` (only when category=`News`) | 0 |
| S1.6/S2 prelude field-family scout | `wqb-field-family-scout.md` (when a semantic field family, category transfer, or active idea discovery is requested) | 0 |
| S2 field scan | `wqb-field-explorer.md` | 0 |
| S2.1 Labs data analyst | `.claude/skills/alpha-template-labs-data-analysis/SKILL.md` (optional, when browser/Labs analysis is requested) | 0 |
| S2.2 external hypothesis scout | `wqb-external-hypothesis-scout.md` | 0 |
| S2.5 zero-order field factory | `wqb-zero-order-field-factory.md` | 0 |
| S3 hypothesis | `wqb-hypothesis-designer.md` | 0 |
| S4 simulate | `wqb-batch-runner.md` | 1 per child sim (exactly 4 children in 1 multi call) |
| S5 gate | `wqb-quality-gate.md` | 0 |
| S5.5 MEA stability guard | `wqb-mea-stability-guard.md` (only when region=`MEA`) | 0 (+optional exact-4 confirmation sims) |
| S6 robustness | `wqb-robustness-audit.md` | 0 (+optional exact-4 sub-universe sims) |
| S6.5 attribution | `wqb-attribution-analyst.md` | 0 (+optional exact-4 ablation sims) |
| S7 repair | `wqb-alpha-repair.md` | exactly 4 variants per invocation |
| S7.5 anti-overfit gate | `wqb-anti-overfit-gate.md` | 0 (+optional 4/8/12 perturbation sims) |
| S8 auto-submit | inline in workflow (4-lock check) | 0 |
| S9 memory | `wqb-memory-writer.md` | 0 |
| post-S9 analytics | `wqb-self-analyst.md` | 0 |
| post-S9 diagnostic | `wqb-self-diagnostic.md` | 0 |

## MCP tool bare names

In skill docs, MCP tools appear as bare names:
- `authenticate`, `get_datasets`, `get_datafields`, `get_operators`
- `create_multi_simulation`, `lookINTO_SimError_message`
- `get_alpha_details`, `get_alpha_yearly_stats`, `get_alpha_pnl`
- `check_self_correlation`, `check_correlation`, `set_alpha_properties`, `submit_alpha`
- `get_platform_setting_options`, `get_documentations`, `get_documentation_page`
- `search_forum_posts`, `read_forum_post`
- `run_selection`, `expand_nested_data`

Your AI client maps these to its own prefix. In Claude Code this is typically `mcp__wqb-mcp__authenticate`; in this Codex workspace it is the `mcp__wqb_mcp__.authenticate` tool namespace.

For `create_multi_simulation`, pass exactly 4 `alpha_expressions[]` plus one shared simulation settings block. The portable skills must not assume per-child settings inside one multi-sim call and must not use single-sim fallback for any short batch. If fewer than 4 valid children exist, fill with non-duplicate controls, ablations, or nearby variants that preserve research value, otherwise defer.

## Contract with workflow

Each skill is called EXACTLY ONCE per session stage (except `wqb-batch-runner`, `wqb-attribution-analyst`, `wqb-alpha-repair`, and `wqb-anti-overfit-gate`, which may be called multiple times in the outer loop).

Skills do NOT call each other directly. The workflow (`workflow/auto-mining.md`) orchestrates.

Skills DO read from `reference/*`, `data/*`, `memory/{region}/*`.
Skills DO write to `records/<date>.jsonl`.
Skills do NOT mutate `memory/` except via `wqb-memory-writer`.
Skills do NOT call `submit_alpha` except via the S8 inline check in `workflow/auto-mining.md`.
Skills do NOT call `set_alpha_properties` unless S8 has already observed `overfit.checked.property_eligible=true` and `overfit.checked.platform_lock.failed_ra_count=0` for the alpha. Failed RA follows the WebDataScope rule, defined in `reference/submission-gates.md` §9 (canonical `RA_CHECK_NAMES` list ported verbatim from `WebDataScope-0.10.20/src/scripts/background.js`). `WARNING` on a name **inside** `RA_CHECK_NAMES` (e.g. `LOW_GLB_AMER_SHARPE`, `LOW_SUB_UNIVERSE_SHARPE`, `LOW_2Y_SHARPE`) **counts as a fail**; `WARNING` on out-of-list names (e.g. `MATCHES_THEMES`) is the only kind that is diagnostic-only.
