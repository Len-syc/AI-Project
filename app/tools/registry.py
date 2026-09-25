"""领域包注册表：加载 domains/ 下的所有领域，按用户目标做意图路由。
领域包 = domain.json（画像 schema）+ policies.json（结构化办事知识）。
新增一个办事领域 = 新增一个目录 + 两份数据，不改任何代码。"""
import json
import os
from functools import lru_cache
from pydantic import BaseModel, ConfigDict, Field

from app import config
from app.schemas import Policy


class AskIf(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    field: str | None = None
    in_: list | None = Field(default=None, alias="in")
    all: list["AskIf"] = []

    def satisfied(self, profile: dict) -> bool:
        """条件成立才需要问这个字段。null 出现在 in 列表里表示"该字段还没答案时也算成立"。"""
        if self.all:
            return all(c.satisfied(profile) for c in self.all)
        v = profile.get(self.field)
        if self.in_ is None:
            return True
        return (v is None and None in self.in_) or (v is not None and v in self.in_)


class ExtractSpec(BaseModel):
    any_of: dict[str, object] = {}
    regex_int: dict | None = None
    bool: dict = {}


class ProfileField(BaseModel):
    name: str
    type: str = "string"          # string / enum / int / bool
    options: list = []
    question: str
    required: bool = False        # True=缺失会阻塞分析（主动追问）；False=仅作为增强字段，缺失显示"信息不足"
    ask_if: AskIf | None = None
    extract: ExtractSpec = ExtractSpec()


class DomainPack(BaseModel):
    domain_id: str
    name: str
    description: str = ""
    intent_keywords: list[str] = []
    profile_fields: list[ProfileField]
    policies: list[Policy] = []
    skill: str = ""                    # skill.md 办事攻略（领域方法论，注入规划上下文）

    def field(self, name: str) -> ProfileField | None:
        return next((f for f in self.profile_fields if f.name == name), None)


def _load_pack(domain_dir: str) -> DomainPack:
    with open(os.path.join(domain_dir, "domain.json"), encoding="utf-8") as f:
        meta = json.load(f)
    policies = []
    policies_path = os.path.join(domain_dir, "policies.json")
    if os.path.exists(policies_path):
        with open(policies_path, encoding="utf-8") as f:
            policies = [Policy(**p) for p in json.load(f)["policies"]]
    skill = ""
    skill_path = os.path.join(domain_dir, "skill.md")
    if os.path.exists(skill_path):
        with open(skill_path, encoding="utf-8") as f:
            skill = f.read()
    return DomainPack(policies=policies, skill=skill, **meta)


@lru_cache
def load_domains() -> dict[str, DomainPack]:
    packs = {}
    for d in sorted(os.listdir(config.DOMAINS_DIR)):
        path = os.path.join(config.DOMAINS_DIR, d)
        if os.path.isdir(path) and os.path.exists(os.path.join(path, "domain.json")):
            pack = _load_pack(path)
            packs[pack.domain_id] = pack
    return packs


def get_domain(domain_id: str) -> DomainPack | None:
    return load_domains().get(domain_id)


def route_domain(goal: str) -> tuple[DomainPack | None, list[DomainPack]]:
    """按意图关键词打分路由。返回 (最佳领域, 全部候选)。
    最佳为 None 时（无命中或并列最高分），调用方应让用户从候选里选。"""
    scored = []
    for pack in load_domains().values():
        score = sum(2 for kw in pack.intent_keywords if kw in goal)
        scored.append((score, pack))
    scored.sort(key=lambda x: -x[0])
    if not scored or scored[0][0] == 0:
        return None, [p for _, p in scored]
    top = [p for s, p in scored if s == scored[0][0]]
    if len(top) > 1:
        return None, [p for _, p in scored]
    return top[0], [p for _, p in scored]
