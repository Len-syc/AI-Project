"""【3号】eligibility-plan-server：资格判断与办理规划 MCP 服务。
工具：check_eligibility / generate_plan
启动：python app/mcp_servers/eligibility_plan_server.py   （stdio 传输）
原则：资格判断只走规则引擎（结论可追溯）；方案可由 LLM 动态生成（mode=api 时，
校验失败自动降级模板）。会话状态由调用方（Agent）持有，本服务无状态。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from mcp.server.fastmcp import FastMCP

from app.schemas import EligibilityResult
from app.tools import eligibility as elig_tool
from app.tools import plan as plan_tool
from app.tools.registry import get_domain, load_domains

mcp = FastMCP("suzhou-eligibility-plan-server",
              instructions="政务办事资格判断与办理规划服务（3号模块）：规则引擎四态判断 + 动态方案生成。")


@mcp.tool()
def check_eligibility(domain_id: str, policy_id: str, profile: dict,
                      profile_sources: dict | None = None) -> dict:
    """将用户画像与指定政策的资格条件逐条匹配。
    返回 overall（PASS/FAIL/UNKNOWN/MANUAL_REVIEW）+ 每条条件的 status 与原因。
    profile: 画像字段字典；profile_sources: 字段来源（user/inferred），推断字段触发待人工确认。"""
    pack = get_domain(domain_id)
    if pack is None:
        raise ValueError(f"未知领域 {domain_id}，可用: {list(load_domains())}")
    result = elig_tool.run_eligibility(policy_id, profile, profile_sources or {}, pack)
    return result.model_dump()


@mcp.tool()
def generate_plan(domain_id: str, eligibility_results: list[dict], profile: dict,
                  materials_uploaded: list[str] | None = None,
                  mode: str = "mock") -> dict:
    """生成个性化办理方案。
    eligibility_results: check_eligibility 的返回列表；mode=api 时由 LLM 读取政策要点与
    skill 攻略动态生成（结构化校验，失败重试一次后降级模板），mode=mock 走模板拓扑排序。
    返回 {"tasks": [...], "source": "llm"|"template", "summary": "..."}。"""
    pack = get_domain(domain_id)
    if pack is None:
        raise ValueError(f"未知领域 {domain_id}，可用: {list(load_domains())}")
    results = [EligibilityResult(**r) for r in eligibility_results]
    out = plan_tool.generate_plan(results, profile, pack, materials_uploaded or [], mode=mode)
    return {**out, "tasks": [t.model_dump() for t in out["tasks"]]}


if __name__ == "__main__":
    mcp.run(transport="stdio")
