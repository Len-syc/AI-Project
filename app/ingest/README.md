# 知识库接入管线（ingest）

把官网爬取数据转换为 Agent 可用的结构化知识包。

## 领域包组成

一个领域 = `app/domains/<domain>/` 下的三份数据：

| 文件 | 内容 | 来源 |
|---|---|---|
| `domain.json` | 画像 schema（字段/追问/抽取规则/ask_if/必填） | 领域建模，人工编写 |
| `policies.json` | 结构化事项（条件/材料/流程/来源） | **本管线的产出** |
| `skill.md` | 办事攻略（顺序经验/材料雷区/时间窗口），注入动态规划上下文 | 领域专家经验，人工编写 |

## 数据流

```
爬虫输出（raw/*.json / *.jsonl）
        │  每条记录一个 dict（结构由爬虫方定义）
        ▼
Converter（app/ingest/ 下的适配器，一种爬取格式一个类）
        │  raw → 中间格式
        ▼
schema 校验（base.validate_policy，缺条件/材料/流程/来源 → 拒绝并报告）
        ▼
写入 app/domains/<domain>/policies.json（幂等合并，按 id 去重）
```

## 中间格式（= 领域包 policies.json 的条目结构）

| 字段 | 必填 | 说明 |
|---|---|---|
| id | ✅ | 全局唯一，建议 `<城市简称>-<事项>-<序号>` |
| name | ✅ | 事项名称（官方全称） |
| department | ✅ | 发布/实施部门 |
| applies_to | ✅ | 适用对象一句话 |
| amount | ✅ | 金额描述，非现金事项写"非现金：……" |
| valid_until | ✅ | 有效期 |
| source | ✅ | 官方原文链接；确无链接必须以"待核实："开头 |
| conditions | ✅ | 资格条件数组：`{id, desc, field, op, value, infer_only?}`，field 对应领域包 domain.json 的画像字段名，op ∈ eq/neq/gte/lte/in/true/false/within_years/months_gte |
| materials | ✅ | 材料清单（名称会用于缺失检查，需规范命名） |
| process | ✅ | 办理流程步骤（顺序即办理顺序） |
| requires | 可选 | 前置事项 id 列表（用于方案拓扑排序） |
| keywords | 可选 | 检索关键词 |
| infer_only_hints | 可选 | 仅系统推断可得的条件 id → 触发"待人工确认" |

## 接入爬虫数据时要做的事

1. **确认爬取格式**（字段名、一条记录的粒度：一个页面？一个事项？）
2. 在 `app/ingest/` 新增转换器（若现有 `LLMGuideConverter` 的假设不匹配）：

```python
from app.ingest.base import Converter, register

@register("xxx_site")
class XXXConverter(Converter):
    def convert(self, raw_item: dict) -> dict | None:
        return {...}   # raw → 中间格式；拿不准的字段留空，禁止编造
```

3. 运行：

```bash
LLM_MODE=api python -m app.ingest.run \
    --raw raw_data/suzhou.jsonl \
    --domain suzhou_startup \
    --converter llm_guide
```

4. 人工抽查转换结果（重点：conditions 是否忠实原文、来源链接是否有效），
   确认后随代码提交知识包。

## 设计原则

- **转换器只做格式映射 + LLM 理解，不做任何事实创作**；校验不过的条目宁可丢弃并报告，不进知识库。
- 每条知识必须带官方来源，无法溯源的标"待核实"，前端展示时明示。
- 知识包是数据（JSON），不是代码——新增办事领域不改 Agent 逻辑。
