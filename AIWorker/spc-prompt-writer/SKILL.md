---
name: spc-prompt-writer
description: 按 BRAIN 中文论坛《SPC 竞赛 Prompt 生成完整指南》撰写、自检并提交 SPC (Strategic Prediction Competition) 的投资论点 Prompt。覆盖 7 项提交字段、纯 JSON 输出契约（ISIN|MIC → −1..1 信心分）、4 段式 Prompt 模板、7 个策略方向、5 个必避错误、覆盖度与权重策略、验证失败排查。Triggers on "SPC prompt", "SPC 竞赛", "写 SPC prompt", "prompt alpha 提交", "ISIN|MIC 输出".
---

# SPC 竞赛 Prompt 撰写

> 来源：BRAIN 中文论坛《SPC 竞赛 Prompt 生成完整指南》(post `42021244122775`, 2026-07-17) 及其跟帖。
> 本 skill 只承载该帖内容，不含任何本地既有 SPC 工具链。

## 一、SPC 是什么

SPC（Strategic Prediction Competition）是 WorldQuant BRAIN 的**月度**竞赛。参赛者提交**投资论点形式的 Prompt**，由 LLM 搜索网络、推理分析，输出全球股票的多空权重组合。系统每日运行，按**累计 PnL** 排名。

```
你写 Prompt → LLM 搜索+推理 → 输出 JSON 股票权重 → 系统自动交易 → 计算 PnL → 排名
```

## 二、提交清单（7 项必填）

| # | 字段 | 说明 | 示例 |
|:-:|------|------|------|
| 1 | **Prompt Name** | 标签名，方便识别 | `Value Trap Screener` |
| 2 | **Prompt Text** | 投资论点正文，最大 **10,000 字符** | 见 §五模板 |
| 3 | **Model** | 使用的 LLM | Claude / GPT / Gemini / DeepSeek 等 |
| 4 | **Model Version** | 可选版本号，最大 100 字符 | `opus4.8`, `gpt5.4` |
| 5 | **Update Frequency** | 运行频率 | ⛔ **小写**：`daily` / `weekly` / `monthly` / `quarterly` |
| 6 | **Weight** | 信念权重，0–1.0，两位小数 | `0.15` |
| 7 | **Sample Output** | 测试过的 JSON 输出样本 | 见 §四 |

支持的 LLM：Claude, GPT, Gemini, DeepSeek, Kimi, Qwen3, GLM, Llama, Minimax, Mistral。

## 三、输出格式（严格契约）

必须输出**纯 JSON**，无任何额外文本：

```json
{
  "ISIN|MIC": confidence_score,
  "ISIN|MIC": confidence_score
}
```

| 字段 | 含义 | 示例 |
|------|------|------|
| ISIN | 12 位股票安全标识符 | `US5949181045` |
| MIC | 交易所代码 | `XNAS`（纳斯达克）、`XETR`（Xetra）、`XLON`（伦敦） |
| Weight | 信心分，范围 **−1 到 1** | 正数=做多，负数=做空，0=不持仓 |

```json
{
  "US5949181045|XNAS": 0.060,
  "US0378691033|XNAS": -0.040,
  "IE00B4L5Y983|XETR": 0.035,
  "US4592001014|XNAS": 0.052,
  "JP3435000009|XTKS": -0.028
}
```

## 四、Prompt 4 段式模板

```
[ROLE] 你是谁...
[task] 你的任务是...
[universe] 你的股票池是...
[output] 输出格式要求...
[constraints] 约束条件...
```

- **ROLE**：`"You are a deep-value equity analyst specializing in European industrial stocks."`
- **TASK**：明确要求**搜索最新网络信息**（不依赖内部记忆）；指定分析框架（基本面/技术面/事件驱动）；说明时间框架。
- **UNIVERSE**：全球 / 特定板块 / 特定地区 / 特定因子。
- **OUTPUT**：只要 JSON，不要任何解释、markdown、bullet。

7 个方向的成品模板与 2 个完整范例见 [references/prompt-templates.md](references/prompt-templates.md)。

## 五、必须避免的 5 个错误

| # | 错误 | ❌ | ✅ | 原因 |
|:-:|------|----|----|------|
| 1 | 模糊词汇 | "strong fundamentals" / "robust growth" / "good value" | "ROIC > 15%, FCF yield > 8%" / "Revenue CAGR > 20% for 3 years" / "P/E < sector median, EV/EBITDA < 10x" | 模糊词导致每次运行结果不一致 |
| 2 | 堆砌弱信号 | 同时要求 8–10 个筛选条件 | 聚焦 2–3 个最强因子 | 信号互相矛盾，信噪比下降 |
| 3 | 要求非 JSON 输出 | "Explain your reasoning" / "Provide bullet points" | "Output only valid JSON, no commentary, no markdown" | 任何额外文本都导致验证失败 |
| 4 | 依赖模型内部记忆 | "Use your knowledge of..." | "Search the web for current..." | 训练数据有截止日期 |
| 5 | Ticker 或等权重 | `AAPL, MSFT` / 全部 0.05 | `US0378331005\|XNAS` / 按信念给分 | Ticker 不被识别；等权重体现不出信念差异 |

## 六、温度设置（必须写进 Prompt）

```
Use the lowest temperature setting (or equivalent reproducibility setting)
to ensure consistent output across runs.
```
或更具体：`Set temperature to 0 for deterministic, reproducible output.`

高温度 ⇒ 每次输出不同 ⇒ 无法保证一致性。

## 七、覆盖范围策略

**单个 Prompt**：约 **50 只**股票（token 效率最优）。太少（<20）覆盖不足；太多（>100）分析深度不够。

**所有 Prompt 合计**：总覆盖应达 **500+ 只不同股票**；各 prompt 覆盖**不同**股票，交集越小分散化越好、PnL 越稳。

多 Prompt 组合示例：

| Prompt | 方向 | 覆盖 |
|--------|------|------|
| A | 美国科技基本面 | 50 只美股科技 |
| B | 欧洲价值股 | 50 只欧洲股 |
| C | 亚洲动量股 | 50 只亚太股 |
| D | 全球宏观对冲 | 50 只全球多空 |
| E | 新闻事件驱动 | 50 只事件受益股 |
| **合计** | 多策略分散 | **~250 只（去重后）** |

## 八、调优流程

```
1. 写初版 Prompt
2. 本地用 LLM 试跑输出
3. 检查是否合法 JSON
4. 检查 ISIN|MIC 格式
5. 检查 weight ∈ [−1, 1]
6. 调整内容，确保分析深度
7. 在【新对话】中做最终测试（避免上下文污染）
8. 提交到 SPC 平台
9. 观察 PnL，迭代优化
```

- 用早期探索性运行识别有潜力的股票。
- **最终生产运行必须在新对话中进行。**
- 测试多个版本再提交。

## 九、验证失败（Failed Validation）排查

| 可能原因 | 解决方法 |
|---------|---------|
| 超过 **32K token** | 精简 Prompt 文本，减少冗余描述 |
| 输出不是合法 JSON | Prompt 中强调 "output only JSON" |
| 信心分超出 −1..1 | Prompt 中明确范围 |
| 包含额外文本 | 删除 "explain" / "analyze" 等指令 |
| **Update Frequency 首字母大写** ⚠️非原帖表内，据跟帖补充 | 见 §二，改成小写 |

验证规则：输出必须是合法 JSON；信心分 ∈ [−1, 1]；提交前必须预测试输出。

## 十、更新频率选择

下表「频率」一列的值**已按 §二 跟帖修正改成小写**；原帖此处写的是大写。

| 频率（提交值） | 适用场景 | 优缺点 |
|------|---------|--------|
| `daily` | 高频交易、事件驱动 | 响应快，token 消耗大 |
| `weekly` | 基本面、中期趋势 | 平衡型，**推荐大多数策略** |
| `monthly` | 长期价值、宏观 | 省 token，反应慢 |
| `quarterly` | 超长期投资 | 最省，几乎不调整 |

## 十一、权重（Weight）设置

| 信念强度 | 权重范围 |
|---------|---------|
| 强信念 | 0.15 – 0.25 |
| 中等信念 | 0.08 – 0.15 |
| 弱信念/测试 | 0.03 – 0.08 |
| 不运行 | 0 |

- 所有活跃（权重 > 0）prompt 总数不能超过 **50 个**。
- 每天最多提交 **50 个** prompt。
- 权重修改在**下一个频率周期**才生效。

## 十二、FAQ

- **能编辑已提交的 Prompt 吗？** 权重可编辑（即时生效，影响未来运行）；**Prompt 文本不能编辑**，文本修改要到下一个频率周期才生效。
- **如何撤回？** 权重设为 0；Prompt 保留在历史中但不再运行。
- **非交易日能提交吗？** 能，系统在下一个匹配频率的交易日运行。
- **排行榜何时更新？** 每个交易日（周末/节假日除外），按月累计 PnL 排序。
- **平局怎么办？** 比较所有 prompt 覆盖的**不同股票总数**，覆盖多的靠前。

## 十三、提交前检查清单

见 [references/submit-checklist.md](references/submit-checklist.md) —— 14 项逐条打勾，含 Update Frequency 小写一项。
