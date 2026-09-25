"""转换器接口与校验。中间格式 = app/schemas.Policy 的 JSON 形态，
字段说明见本目录 README.md。"""
import json
from abc import ABC, abstractmethod

from app.schemas import Policy


class Converter(ABC):
    """一个转换器适配一种爬取数据格式。
    输入：爬取的单条原始记录（dict，结构由爬虫方定义）
    输出：中间格式 dict（见 README.md）；无法可靠转换的字段返回 None 或留空，
    由校验环节报告缺项，禁止编造。"""
    domain_hint: str = ""        # 建议归属的领域包 id

    @abstractmethod
    def convert(self, raw_item: dict) -> dict | None:
        ...


# 注册器：新转换器用 @register("名字") 挂进 CONVERTERS
_REGISTRY: dict[str, type[Converter]] = {}


def register(name: str):
    def deco(cls):
        _REGISTRY[name] = cls
        return cls
    return deco


def get_converter_class(name: str) -> type[Converter]:
    if name not in _REGISTRY:
        raise KeyError(f"未知转换器 {name}，已注册: {list(_REGISTRY)}")
    return _REGISTRY[name]


def validate_policy(data: dict) -> tuple[Policy | None, str]:
    """校验中间格式。返回 (policy, error)；不合法时 error 说明缺什么。"""
    try:
        p = Policy(**data)
    except Exception as e:
        return None, f"schema 校验失败: {e}"
    problems = []
    if not p.conditions:
        problems.append("conditions 为空（至少需要可判断的资格条件）")
    if not p.materials:
        problems.append("materials 为空（材料清单缺失）")
    if not p.process:
        problems.append("process 为空（办理流程缺失）")
    if "待核实" not in p.source and not p.source.startswith("http"):
        problems.append("source 需为官方原文链接或明确标注待核实")
    if problems:
        return None, "；".join(problems)
    return p, ""
