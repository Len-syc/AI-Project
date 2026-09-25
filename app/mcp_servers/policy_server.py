"""【2号】policy-server：政策检索 MCP 服务。
工具：policy_search / policy_detail / list_domains
启动：python app/mcp_servers/policy_server.py   （stdio 传输）
任意 MCP 客户端（本 Agent、Claude Desktop、其他 Agent）均可连接复用。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from mcp.server.fastmcp import FastMCP

from app.tools import policy as policy_tool
from app.tools.registry import get_domain, load_domains

mcp = FastMCP("suzhou-policy-server",
              instructions="苏州市政务办事知识库检索服务（2号模块）：按领域检索政策/办事事项与官方来源。")


@mcp.tool()
def list_domains() -> list[dict]:
    """列出知识库收录的所有办事领域（id、名称、事项数量）。"""
    return [{"domain_id": p.domain_id, "name": p.name,
             "description": p.description, "policy_count": len(p.policies)}
            for p in load_domains().values()]


@mcp.tool()
def policy_search(domain_id: str, goal: str, city: str | None = None) -> list[dict]:
    """按办事目标在指定领域内检索政策/事项。命中关键词的排前，同城其余事项兜底返回
    （资格判断交给规则引擎）。政策限定城市与 city 不符时排除，不编造跨城结论。"""
    pack = get_domain(domain_id)
    if pack is None:
        raise ValueError(f"未知领域 {domain_id}，可用: {list(load_domains())}")
    return [p.model_dump() for p in policy_tool.policy_search(pack, goal, city=city)]


@mcp.tool()
def policy_detail(domain_id: str, policy_id: str) -> dict:
    """按 policy_id 返回完整事项信息：资格条件、所需材料、办理流程、前置关系、官方来源。"""
    pack = get_domain(domain_id)
    p = policy_tool.policy_detail(policy_id, pack) if pack else policy_tool.policy_detail(policy_id)
    if p is None:
        raise ValueError(f"政策 {policy_id} 不存在")
    return p.model_dump()


if __name__ == "__main__":
    mcp.run(transport="stdio")
