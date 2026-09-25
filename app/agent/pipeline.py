"""【1号模块】Agent 主流程：状态机 + 工具编排 + SSE 事件流。

阶段：collect_profile →(多域未定→await_domain)→ analyzing → await_material → report
原则：流程骨架写死（保证演示稳定），LLM 只做画像抽取与措辞（api 模式），
判断全部走规则引擎（3号），检索走领域包知识库（2号），材料走 VLM/sidecar（4号）。
领域包来自 app/domains/，新增办事领域不改代码。
"""
import json
from typing import AsyncGenerator
from app.agent.profile_extract import extract_profile
from app.agent import tool_gateway as gateway
from app.tools.registry import get_domain, route_domain, AskIf
from app import config

STATUS_LABEL = {"PASS": "✅ 符合", "FAIL": "⛔ 暂不满足", "UNKNOWN": "❓ 信息不足",
                "MANUAL_REVIEW": "🟡 待人工确认"}

FORCE_ANALYZE_WORDS = ["开始分析", "帮我查", "就这些", "没有了", "直接分析", "先分析"]


def _ask_if_satisfied(cond: AskIf | None, profile: dict) -> bool:
    return True if cond is None else cond.satisfied(profile)


def _pending_fields(session: dict):
    """该领域下还需要问的字段（必填、缺失、且 ask_if 条件成立）。
    非必填的增强字段不阻塞主流程，缺失时在资格结果中显示"信息不足"。"""
    pack = get_domain(session["domain"])
    if pack is None:
        return []
    profile = session["profile"]
    return [f for f in pack.profile_fields
            if f.required and profile.get(f.name) is None
            and _ask_if_satisfied(f.ask_if, profile)]


def _merge_profile(session: dict, extracted: dict) -> list[str]:
    updated = []
    profile = session["profile"]
    for k, v in extracted.items():
        if v is not None and profile.get(k) is None:
            profile[k] = v
            session["profile_sources"][k] = "user"
            updated.append(k)
    return updated


def _snapshot(session: dict) -> dict:
    pack = get_domain(session["domain"]) if session["domain"] else None
    return {
        "session_id": session["session_id"],
        "stage": session["stage"],
        "goal": session["goal"],
        "domain": {"id": pack.domain_id, "name": pack.name} if pack else None,
        "profile": session["profile"],
        "profile_sources": session["profile_sources"],
        "policies": [p.model_dump() for p in (pack.policies if pack else [])],
        "eligibility": [e.model_dump() for e in session["eligibility"]],
        "plan": [t.model_dump() for t in session["plan"]],
        "plan_source": session["plan_source"],
        "plan_summary": session["plan_summary"],
        "materials": [m.model_dump() for m in session["materials"]],
        "material_check": session["material_check"].model_dump() if session["material_check"] else None,
        "report": session["report"],
    }


def _profile_brief(session: dict) -> str:
    pack = get_domain(session["domain"])
    profile = session["profile"]
    if pack is None:
        return "信息收集中"
    parts = [str(profile[f.name]) for f in pack.profile_fields if profile.get(f.name) is not None]
    return "·".join(parts) or "信息收集中"


async def _analyze(session: dict) -> tuple[str, list[tuple[str, dict]]]:
    """核心编排：检索 → 资格 → 规划。返回 (回复文本, SSE事件列表)。"""
    events: list[tuple[str, dict]] = []
    pack = get_domain(session["domain"])
    profile, sources = session["profile"], session["profile_sources"]
    city = profile.get("城市")

    events.append(("stage_change", {"stage": "analyzing", "label": f"正在分析你的情况（{pack.name}）"}))

    # ---- PolicySearch（2号）----
    events.append(("tool_call", {"tool": "PolicySearch",
                                 "args": {"domain": pack.domain_id, "goal": session["goal"], "city": city}}))
    found = await gateway.policy_search(pack, session["goal"], city=city)
    session["policy_ids"] = [p.id for p in found]
    events.append(("tool_result", {"tool": "PolicySearch",
                                   "summary": f"命中 {len(found)} 条：{'、'.join(p.name for p in found) or '无'}"}))

    if not found:
        session["stage"] = "report"
        reason = f"暂时没有{city}的可靠信息" if city else "知识库中暂无可检索的办事事项"
        return (f"抱歉，当前知识库（{pack.name}）仅覆盖已收录地区和事项，{reason}。"
                f"为保证不误导你，我不做猜测性推荐。\n"
                f"你可以输入\"重新开始\"换个目标再试。"), events + [("state", _snapshot(session))]

    # ---- Eligibility（3号）----
    events.append(("stage_change", {"stage": "analyzing", "label": "正在逐条判断资格"}))
    session["eligibility"] = []
    for p in found:
        events.append(("tool_call", {"tool": "Eligibility",
                                     "args": {"policy": p.name, "conditions": len(p.conditions)}}))
        r = await gateway.run_eligibility(p.id, profile, sources, pack)
        session["eligibility"].append(r)
        events.append(("tool_result", {"tool": "Eligibility",
                                       "summary": f"{p.name} → {STATUS_LABEL[r.overall]}"}))

    # ---- Plan（3号）：api 模式 AI 动态生成，mock 模式模板，校验失败自动降级 ----
    events.append(("stage_change", {"stage": "analyzing", "label": "正在生成办理方案"}))
    events.append(("tool_call", {"tool": "Plan", "args": {
        "policies": len(found),
        "mode": config.LLM_MODE,
        "skill": bool(pack.skill),
    }}))
    plan_out = await gateway.generate_plan(
        eligibility_results=session["eligibility"], profile=profile, pack=pack,
        materials_uploaded=[m.doc_type for m in session["materials"]])
    session["plan"] = plan_out["tasks"]
    session["plan_source"] = plan_out["source"]
    session["plan_summary"] = plan_out["summary"]
    src_label = "AI 动态生成（含政策依据）" if plan_out["source"] == "llm" else "模板生成（离线兜底）"
    events.append(("tool_result", {"tool": "Plan",
                                   "summary": f"{src_label}：{len(session['plan'])} 个步骤"}))

    session["stage"] = "await_material"

    # ---- 组织回复 ----
    lines = [f"根据你的情况（{_profile_brief(session)}），"
             f"从「{pack.name}」知识库中匹配到 {len(found)} 项相关事项：", ""]
    for i, e in enumerate(session["eligibility"], 1):
        lines.append(f"{i}. 【{e.policy_name}】{STATUS_LABEL[e.overall]}")
        if e.gap:
            lines.append(f"   差距：{e.gap}")
        if e.overall == "MANUAL_REVIEW":
            lines.append("   注意：存在需人工确认的条件（系统推断信息不作为结论依据），建议向主管部门核实。")
    lines += ["", "建议办理顺序已生成（见右侧\"办理方案\"）。", ""]
    needed = sorted({m for t in session["plan"] for m in t.materials})
    if needed:
        lines.append(f"需要准备的材料：{'、'.join(needed)}。")
        lines.append("请上传材料图片（演示样本见项目 app/data/sample_materials/），我会自动预检缺失项和信息冲突；"
                     "也可以直接输入\"生成报告\"查看当前预检结论。")
    return "\n".join(lines), events + [("state", _snapshot(session))]


async def build_report(session: dict) -> dict:
    """预检报告（PRD 9.2 结构）。"""
    required = sorted({m for t in session["plan"] for m in t.materials})
    check = await gateway.check_materials(session, required)
    session["material_check"] = check

    passed = [m.doc_type for m in check.materials
              if m.status == "OK" and m.doc_type not in [i.detail for i in check.conflicts]]
    to_fix = [c.detail for c in check.conflicts if c.type == "conflict"]
    manual = [c.detail for c in check.conflicts if c.type == "manual"]

    report = {
        "overall": check.readiness,
        "passed": passed,
        "to_fix": to_fix,
        "missing": check.missing,
        "manual_review": manual,
        "eligibility_summary": [
            {"policy": e.policy_name, "status": e.overall, "label": STATUS_LABEL[e.overall]}
            for e in session["eligibility"]],
    }
    session["report"] = report
    session["stage"] = "report"
    return report


def _report_text(report: dict) -> str:
    lines = ["【材料预检报告】", f"整体状态：{report['overall']}", ""]
    if report["passed"]:
        lines.append("✅ 已通过：" + "、".join(report["passed"]))
    if report["to_fix"]:
        lines.append("⚠️ 待修改：" + "；".join(report["to_fix"]))
    if report["missing"]:
        lines.append("❌ 缺失材料：" + "、".join(report["missing"]))
    if report["manual_review"]:
        lines.append("🟡 待人工确认：" + "；".join(report["manual_review"]))
    lines += ["", "说明：本报告为辅助预检，不构成正式审批意见，最终以主管部门审核为准。"]
    return "\n".join(lines)


def _domain_list_text() -> str:
    from app.tools.registry import load_domains
    packs = list(load_domains().values())
    lines = ["当前知识库收录了以下办事领域，你想了解哪一类？请直接描述，例如：", ""]
    for i, p in enumerate(packs, 1):
        lines.append(f"{i}. {p.name} —— {p.description}")
    return "\n".join(lines)


def _reset(session: dict):
    from app.store import new_session_fields
    session.update(new_session_fields())


async def handle_chat(session: dict, message: str) -> AsyncGenerator[str, None]:
    """处理一轮对话，yield SSE 格式事件。"""

    def sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    session["messages"].append({"role": "user", "content": message})
    session["turns"] += 1
    yield sse("stage_change", {"stage": session["stage"], "label": "正在理解你的输入"})

    if not session["goal"]:
        session["goal"] = message

    reply = ""

    # ---- 领域未定：意图路由 ----
    if not session["domain"]:
        best, candidates = route_domain(message)
        if best is None:
            session["stage"] = "await_domain"
            reply = _domain_list_text()
            yield sse("state", _snapshot(session))
        else:
            session["domain"] = best.domain_id
            session["stage"] = "collect_profile"
            extracted = extract_profile(message, best, config.LLM_MODE)
            _merge_profile(session, extracted)
            pending = _pending_fields(session)
            if not pending or any(w in message for w in FORCE_ANALYZE_WORDS):
                reply, events = await _analyze(session)
                for e, d in events:
                    yield sse(e, d)
            else:
                reply = (f"好的，你的事项属于「{best.name}」。为了准确判断你能办理哪些事项，"
                         "我需要确认几个信息：\n" +
                         "\n".join(f"{i+1}. {f.question}" for i, f in enumerate(pending[:2])))
                yield sse("state", _snapshot(session))

    # ---- 画像收集 ----
    elif session["stage"] == "collect_profile":
        pack = get_domain(session["domain"])
        extracted = extract_profile(message, pack, config.LLM_MODE)
        _merge_profile(session, extracted)
        pending = _pending_fields(session)
        if not pending or any(w in message for w in FORCE_ANALYZE_WORDS):
            reply, events = await _analyze(session)
            for e, d in events:
                yield sse(e, d)
        else:
            reply = ("好的，为了准确判断你能办理哪些事项，我需要确认几个信息：\n" +
                     "\n".join(f"{i+1}. {f.question}" for i, f in enumerate(pending[:2])))
            yield sse("state", _snapshot(session))

    # ---- 材料阶段 ----
    elif session["stage"] == "await_material":
        if "报告" in message:
            report = await build_report(session)
            reply = _report_text(report)
            yield sse("stage_change", {"stage": "report", "label": "已生成预检报告"})
            yield sse("state", _snapshot(session))
        else:
            required = sorted({m for t in session["plan"] for m in t.materials})
            missing = [m for m in required
                       if m not in [x.doc_type for x in session["materials"]]]
            reply = "请在下方\"材料中心\"上传材料图片，我会自动识别并预检。" \
                    f"（还缺：{'、'.join(missing) if missing else '无，可输入\"生成报告\"'}）"
            yield sse("state", _snapshot(session))

    # ---- 报告阶段 ----
    elif session["stage"] == "report":
        if "重新" in message or "再来" in message:
            _reset(session)
            reply = "已重置会话。请直接描述你要办理的事，例如：我想在苏州办居住证 / 我是2026届毕业生想在苏州创业。"
            yield sse("state", _snapshot(session))
        else:
            reply = "预检报告已生成（见右侧）。你可以继续上传补件材料后输入\"生成报告\"重新预检，或输入\"重新开始\"重置演示。"
            yield sse("state", _snapshot(session))

    session["messages"].append({"role": "assistant", "content": reply})
    yield sse("message", {"role": "assistant", "content": reply})
    yield sse("done", {})
