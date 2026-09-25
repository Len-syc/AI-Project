"""【4号】material-server：材料解析与检查 MCP 服务。
工具：parse_document / check_materials
启动：python app/mcp_servers/material_server.py   （stdio 传输）
注意：parse_document 读取本机文件路径（stdio 本地部署场景）；api 模式走 VLM，
mock 模式读取样本旁的 .meta.json sidecar。会话状态由调用方（Agent）持有。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from mcp.server.fastmcp import FastMCP

from app.schemas import MaterialRecord
from app.tools import material as material_tool

mcp = FastMCP("suzhou-material-server",
              instructions="政务办事材料预检服务（4号模块）：证件识别、字段抽取、缺失与跨材料一致性检查。")


@mcp.tool()
def parse_document(file_path: str, original_name: str, mode: str = "mock") -> dict:
    """识别单份材料：L1 分类（证件类型）+ L2 关键字段抽取。
    mode=api 走 VLM；mode=mock 读取 <文件名>.meta.json sidecar（演示样本预置）。
    返回 {doc_type, filename, status, fields}。"""
    if not os.path.exists(file_path):
        raise FileNotFoundError(file_path)
    rec = material_tool.parse_document("", file_path, original_name)
    return rec.model_dump()


@mcp.tool()
def check_materials(materials: list[dict], required: list[str]) -> dict:
    """材料预检：L3 缺失检查（政策要求但未上传）+ L4 跨材料一致性（如姓名冲突）。
    materials: parse_document 返回的记录列表；required: 候选政策材料清单并集。
    返回 {materials, missing, conflicts, readiness}。"""
    records = [MaterialRecord(**m) for m in materials]
    check = material_tool.check_materials({"materials": records}, required)
    return check.model_dump()


if __name__ == "__main__":
    mcp.run(transport="stdio")
