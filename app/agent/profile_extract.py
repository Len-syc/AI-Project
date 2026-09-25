"""用户画像抽取。抽取规则来自领域包的 extract 配置（数据，不是代码）：
  any_of     关键词映射（最长关键词优先，避免"就业"误命中"灵活就业"）
  regex_int  正则抽整数（毕业年份/月数），支持 recent_any 近义命中直接取值
  bool       true_any / false_any 关键词 → True/False

api 模式改由 LLM 按 schema 字段做结构化抽取，字段清单同样来自领域包。
"""
from app import llm
from app.tools.registry import DomainPack, ProfileField


def _extract_field(field: ProfileField, text: str):
    spec = field.extract
    # any_of：最长关键词优先
    for kw in sorted(spec.any_of, key=len, reverse=True):
        if kw in text:
            return spec.any_of[kw]
    # regex_int
    if spec.regex_int:
        import re
        cfg = spec.regex_int
        for w in cfg.get("recent_any", []):
            if w in text:
                return cfg.get("recent_value")
        m = re.search(cfg["pattern"], text)
        if m:
            v = int(m.group(1))
            if v < cfg.get("min", -10**9) or v > cfg.get("max", 10**9):
                return None
            return v
    # bool
    if spec.bool:
        for w in spec.bool.get("true_any", []):
            if w in text:
                return True
        for w in spec.bool.get("false_any", []):
            if w in text:
                return False
    return None


def extract_profile(text: str, pack: DomainPack, mode: str) -> dict:
    """从一句话中抽取该领域画像字段。只返回能确认的字段。"""
    if mode == "api":
        fields_desc = "\n".join(
            f"- {f.name}（{f.type}{'，可选值: ' + '/'.join(map(str, f.options)) if f.options else ''}）"
            for f in pack.profile_fields)
        system = (f"从用户消息中抽取办事画像字段，缺失的字段不要编造，直接省略。\n"
                  f"领域：{pack.name}\n可用字段：\n{fields_desc}\n"
                  "输出 JSON：{字段名: 值}，只含能确认的字段。布尔值用 true/false，数字用数字。")
        try:
            return llm.extract_json(system, text)
        except Exception:
            return {}
    out = {}
    for f in pack.profile_fields:
        v = _extract_field(f, text)
        if v is not None:
            out[f.name] = v
    return out
