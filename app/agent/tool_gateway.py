"""工具网关：pipeline 与 HTTP 端点统一从这里调工具。
TOOL_MODE=direct（默认）→ 进程内直调，零额外开销，演示保底；
TOOL_MODE=mcp        → Agent 作为 MCP host，经 stdio 协议调用三个工具服务
                       （协议边界真实存在，任何 MCP 客户端都能复用同样的服务）。
网关把 MCP 的 dict 返回值转回 Pydantic 模型，调用方（pipeline）不感知模式差异。"""
from app import config
from app.schemas import (EligibilityResult, MaterialCheckResult, MaterialRecord,
                         PlanTask, Policy)
from app.tools.registry import DomainPack


async def policy_search(pack: DomainPack, goal: str, city: str | None) -> list[Policy]:
    if config.TOOL_MODE == "mcp":
        from app import mcp_client
        data = await mcp_client.call_tool("policy", "policy_search",
                                          {"domain_id": pack.domain_id, "goal": goal, "city": city})
        return [Policy(**d) for d in data]
    from app.tools import policy as policy_tool
    return policy_tool.policy_search(pack, goal, city=city)


async def run_eligibility(policy_id: str, profile: dict, sources: dict,
                          pack: DomainPack) -> EligibilityResult:
    if config.TOOL_MODE == "mcp":
        from app import mcp_client
        data = await mcp_client.call_tool("eligibility_plan", "check_eligibility", {
            "domain_id": pack.domain_id, "policy_id": policy_id,
            "profile": profile, "profile_sources": sources})
        return EligibilityResult(**data)
    from app.tools import eligibility as elig_tool
    return elig_tool.run_eligibility(policy_id, profile, sources, pack)


async def generate_plan(eligibility_results: list[EligibilityResult], profile: dict,
                        pack: DomainPack, materials_uploaded: list[str]) -> dict:
    if config.TOOL_MODE == "mcp":
        from app import mcp_client
        out = await mcp_client.call_tool("eligibility_plan", "generate_plan", {
            "domain_id": pack.domain_id,
            "eligibility_results": [r.model_dump() for r in eligibility_results],
            "profile": profile, "materials_uploaded": materials_uploaded,
            "mode": config.LLM_MODE})
        return {**out, "tasks": [PlanTask(**t) for t in out["tasks"]]}
    from app.tools import plan as plan_tool
    out = plan_tool.generate_plan(eligibility_results, profile, pack,
                                  materials_uploaded, mode=config.LLM_MODE)
    return out


async def parse_document(file_path: str, original_name: str) -> MaterialRecord:
    if config.TOOL_MODE == "mcp":
        from app import mcp_client
        data = await mcp_client.call_tool("material", "parse_document", {
            "file_path": file_path, "original_name": original_name,
            "mode": config.LLM_MODE})
        return MaterialRecord(**data)
    from app.tools import material as material_tool
    return material_tool.parse_document("", file_path, original_name)


async def check_materials(session: dict, required: list[str]) -> MaterialCheckResult:
    if config.TOOL_MODE == "mcp":
        from app import mcp_client
        data = await mcp_client.call_tool("material", "check_materials", {
            "materials": [m.model_dump() for m in session["materials"]],
            "required": required})
        return MaterialCheckResult(**data)
    from app.tools import material as material_tool
    return material_tool.check_materials(session, required)
