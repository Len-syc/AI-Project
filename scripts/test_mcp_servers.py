# -*- coding: utf-8 -*-
"""MCP 服务协议级测试：以 MCP 客户端身份连接 3 个服务，实测全部 7 个工具。
用法：python scripts/test_mcp_servers.py   （无需启动 uvicorn）
注意：所有断言必须在 stdio 上下文内存活期间执行（连接随上下文关闭）。"""
import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

FAILS = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")
    if not cond:
        FAILS.append(name)


def make_params(script: str) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable, args=[os.path.join(ROOT, "app", "mcp_servers", script)],
        cwd=ROOT, env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": ROOT})


async def call(session, name, args):
    result = await session.call_tool(name, args)
    if getattr(result, "isError", False):
        raise RuntimeError(f"{name} 执行失败: {[c.text for c in result.content]}")
    sc = getattr(result, "structuredContent", None)
    if isinstance(sc, dict) and "result" in sc:
        return sc["result"]
    for c in result.content:
        if getattr(c, "text", None):
            return json.loads(c.text)
    return None


async def main():
    print("== 1. policy-server（2号） ==")
    async with stdio_client(make_params("policy_server.py")) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = {t.name for t in (await s.list_tools()).tools}
            check("工具清单", {"policy_search", "policy_detail", "list_domains"} <= tools, str(tools))
            domains = await call(s, "list_domains", {})
            check("list_domains 返回 2 领域", len(domains) == 2)
            found = await call(s, "policy_search",
                               {"domain_id": "suzhou_residence", "goal": "办居住证", "city": "苏州"})
            check("policy_search 命中居住证", any(p["id"] == "sz-jzz-apply" for p in found))
            detail = await call(s, "policy_detail",
                                {"domain_id": "suzhou_residence", "policy_id": "sz-jzz-apply"})
            check("policy_detail 含名称与材料",
                  detail["name"] == "苏州居住证申领" and len(detail["materials"]) > 0)
            try:
                await call(s, "policy_search", {"domain_id": "nope", "goal": "x", "city": None})
                check("非法领域报错", False)
            except Exception:
                check("非法领域报错", True)

    print("\n== 2. eligibility-plan-server（3号） ==")
    async with stdio_client(make_params("eligibility_plan_server.py")) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            profile = {"城市": "苏州", "居住事由": "合法稳定就业", "居住登记月数": 8}
            r1 = await call(s, "check_eligibility", {"domain_id": "suzhou_residence",
                                                     "policy_id": "sz-jzz-apply", "profile": profile})
            check("资格判断 PASS", r1["overall"] == "PASS", r1["overall"])
            r2 = await call(s, "check_eligibility", {"domain_id": "suzhou_residence",
                                                     "policy_id": "sz-jzz-renew", "profile": profile})
            check("签注 UNKNOWN(无凭证)", r2["overall"] == "UNKNOWN")
            plan = await call(s, "generate_plan", {
                "domain_id": "suzhou_residence", "eligibility_results": [r1, r2],
                "profile": profile, "materials_uploaded": [], "mode": "mock"})
            check("方案生成（模板）", plan["source"] == "template" and len(plan["tasks"]) >= 3,
                  f"{len(plan['tasks'])} 步")

    print("\n== 3. material-server（4号） ==")
    async with stdio_client(make_params("material_server.py")) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            sample = os.path.join(ROOT, "app", "data", "sample_materials", "身份证_张三.png")
            rec = await call(s, "parse_document", {"file_path": sample,
                                                   "original_name": "身份证_张三.png", "mode": "mock"})
            check("识别身份证+字段", rec["doc_type"] == "身份证明" and rec["fields"].get("姓名") == "张三")
            form = await call(s, "parse_document", {
                "file_path": os.path.join(ROOT, "app", "data", "sample_materials", "创业补贴申请表_李四.png"),
                "original_name": "创业补贴申请表_李四.png", "mode": "mock"})
            chk = await call(s, "check_materials",
                             {"materials": [rec, form],
                              "required": ["身份证明", "学历证明", "创业补贴申请表"]})
            names = [c["detail"] for c in chk["conflicts"]]
            check("跨材料姓名冲突", any("不一致" in n for n in names), names)
            check("缺失清单", chk["missing"] == ["学历证明"], str(chk["missing"]))

    print("\n================")
    print("FAILED:", FAILS if FAILS else "无，全部通过 ✅")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
