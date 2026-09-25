"""通用转换器：办事指南页面正文 → 中间格式。
依赖 LLM 结构化抽取（api 模式）；模型只做"理解"，抽取结果必须过 schema 校验，
来源链接原样保留 —— 对应 PRD"模型负责理解，来源负责证明"。"""
from app import config, llm
from app.ingest.base import Converter, register

SYSTEM = """你是政务办事知识库整理员。根据给出的办事指南正文，抽取结构化信息。
严格依据原文，原文没有的信息留空，禁止编造。
输出 JSON：
{
  "name": "事项名称",
  "department": "发布/实施部门",
  "applies_to": "适用对象一句话",
  "amount": "金额或'非现金：事项说明'（原文无则空串）",
  "valid_until": "有效期或'长期有效'",
  "source": "原文链接（原样保留输入的 url）",
  "conditions": [{"id": "c1", "desc": "条件描述（原文措辞）",
                  "field": "对应画像字段名（拼音或中文，与领域 schema 一致）",
                  "op": "eq/gte/lte/in/true/within_years", "value": ...}],
  "materials": ["材料名", ...],
  "process": ["步骤1", ...],
  "keywords": ["检索关键词", ...]
}"""


@register("llm_guide")
class LLMGuideConverter(Converter):
    domain_hint = ""

    def convert(self, raw_item: dict) -> dict | None:
        """raw_item 约定：{title, url, department?, text}（爬虫方格式定稿后按需调整）。"""
        if config.LLM_MODE != "api":
            raise RuntimeError("llm_guide 转换器需要 LLM_MODE=api（LLM 抽取正文）")
        user = f"标题: {raw_item.get('title', '')}\n" \
               f"链接: {raw_item.get('url', '')}\n" \
               f"部门: {raw_item.get('department', '')}\n" \
               f"正文:\n{raw_item.get('text', '')}"
        data = llm.extract_json(SYSTEM, user)
        data.setdefault("source", raw_item.get("url", "待核实：无链接"))
        data.setdefault("requires", [])
        data.setdefault("keywords", [])
        data.setdefault("infer_only_hints", [])
        data["id"] = raw_item.get("id") or ""
        return data
