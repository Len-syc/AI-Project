"""【2号模块】政策/事项检索：PolicySearch / PolicyDetail。
在指定领域包内做 关键词+标签 打分检索；数据来自该包的 policies.json
（未来由 app/ingest/ 管线从官网爬取数据生成）。"""
from app.schemas import Policy
from app.tools.registry import DomainPack, load_domains


def policy_detail(policy_id: str, pack: DomainPack | None = None) -> Policy | None:
    packs = [pack] if pack else list(load_domains().values())
    for p in packs:
        for item in p.policies:
            if item.id == policy_id:
                return item
    return None


def policy_search(pack: DomainPack, goal: str, city: str | None = None) -> list[Policy]:
    """在领域包内检索。命中关键词的排前，其余兜底返回（资格判断交给规则引擎，
    避免"目标表述不精确就漏推荐"——PRD 要求跨事项综合判断）。
    政策限定城市而用户城市不符时直接排除（不编造跨城结论）。"""
    scored, rest = [], []
    for p in pack.policies:
        city_cond = next((c for c in p.conditions if c.field == "城市" and c.op == "eq"), None)
        if city and city_cond and city != city_cond.value:
            continue
        score = sum(2 for kw in p.keywords if kw in goal)
        (scored if score > 0 else rest).append((score, p))
    scored.sort(key=lambda x: -x[0])
    return [p for _, p in scored] + [p for _, p in rest]
