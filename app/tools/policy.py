"""【2号模块】政策检索：PolicySearch / PolicyDetail。
MVP 用 关键词+标签 打分检索（7条政策无需向量库）；数据格式见 policies.json。"""
import json
from functools import lru_cache
from app import config
from app.schemas import Policy


@lru_cache
def load_policies() -> list[Policy]:
    with open(config.POLICIES_FILE, encoding="utf-8") as f:
        raw = json.load(f)
    return [Policy(**p) for p in raw["policies"]]


def policy_detail(policy_id: str) -> Policy | None:
    for p in load_policies():
        if p.id == policy_id:
            return p
    return None


def policy_search(goal: str, city: str | None = None) -> list[Policy]:
    """按目标文本与城市过滤打分。
    命中关键词的政策排前；同城市其余政策兜底返回（资格判断交给规则引擎，
    避免"目标表述不精确就漏推荐"——PRD 要求跨政策综合判断）。"""
    scored, rest = [], []
    for p in load_policies():
        # 政策限定城市而用户城市不匹配 → 直接排除（不编造跨城结论）
        city_cond = next((c for c in p.conditions if c.field == "城市" and c.op == "eq"), None)
        if city and city_cond and city != city_cond.value:
            continue
        score = sum(2 for kw in p.keywords if kw in goal)
        if "补贴" in goal and "补贴" in p.name:
            score += 1
        (scored if score > 0 else rest).append((score, p))
    scored.sort(key=lambda x: -x[0])
    return [p for _, p in scored] + [p for _, p in rest]
