"""用户画像抽取。mock 模式用关键词规则（离线可跑）；api 模式用 LLM 结构化抽取。
两模式输出同一结构，pipeline 不感知差异。"""
import re
from app import llm

SUSONG_AREAS = ["姑苏区", "虎丘区", "工业园区", "高新区", "吴中区", "相城区", "吴江区",
                "常熟市", "张家港市", "昆山市", "太仓市"]
CITIES = ["苏州", "南京", "上海", "杭州", "北京", "深圳", "广州", "成都", "武汉", "西安",
          "郑州", "合肥", "无锡", "常州", "南通", "徐州", "福州", "厦门", "长沙", "重庆"]

EDU_MAP = [("博士", "博士"), ("硕士", "硕士"), ("研究生", "硕士"),
           ("本科", "本科"), ("学士", "本科"), ("大专", "大专"), ("专科", "大专")]

EXTRACT_SYSTEM = """从用户消息中抽取政务办事画像字段，缺失的字段不要编造，直接省略。
可用字段：
城市（如"苏州"）、学历（大专/本科/硕士/博士）、毕业年份（整数）、
状态（就业/创业/灵活就业/待业）、是否首次创业（true/false）、
企业注册地（苏州下辖区县名）、企业注册时间（"YYYY-MM"）、社保缴纳月数（整数）、
困难情形（存在低保/残疾/助学贷款等情况时为 true）。
输出 JSON：{"城市":..., "学历":..., ...}，只含能确认的字段。"""


def _rule_extract(text: str) -> dict:
    out = {}
    for kw, v in EDU_MAP:
        if kw in text:
            out["学历"] = v
            break
    years = [int(y) for y in re.findall(r"(20[0-3]\d)", text)
             if 2015 <= int(y) <= 2035]
    if "应届" in text or "今年毕业" in text:
        out["毕业年份"] = max(y for y in years if y >= 2025) if years else 2026
    elif years:
        out["毕业年份"] = min(years, key=lambda y: abs(y - 2026))
    for c in CITIES:
        if c in text:
            out["城市"] = c
            break
    for a in SUSONG_AREAS:
        if a in text:
            out["企业注册地"] = a
            break
    if "灵活就业" in text or "自由职业" in text:
        out["状态"] = "灵活就业"
    elif "创业" in text or "开公司" in text or "开店" in text:
        out["状态"] = "创业"
    elif "入职" in text or "上班" in text or "就业" in text:
        out["状态"] = "就业"
    if "第一次创业" in text or "首次创业" in text or re.search(r"第一次(自己)?(开|创)", text):
        out["是否首次创业"] = True
    elif "不是首次" in text or "之前创过" in text or "第二次创业" in text:
        out["是否首次创业"] = False
    m = re.search(r"社保[^0-9]{0,4}(\d{1,2})\s*个?月", text)
    if m:
        out["社保缴纳月数"] = int(m.group(1))
    if any(k in text for k in ["低保", "残疾", "助学贷款", "困难家庭"]):
        out["困难情形"] = True
    return out


def extract_profile(text: str, mode: str) -> dict:
    if mode == "api":
        try:
            return llm.extract_json(EXTRACT_SYSTEM, text)
        except Exception:
            return {}
    return _rule_extract(text)
