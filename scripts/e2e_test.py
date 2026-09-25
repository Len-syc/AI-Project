# -*- coding: utf-8 -*-
"""端到端联调脚本：mock 模式全链路（对话 → 追问 → 分析 → 上传材料 → 冲突 → 报告）。
用法：python scripts/e2e_test.py [base_url]  默认 http://127.0.0.1:8765
"""
import io
import json
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
SESSION = {"session_id": None}
FAILS = []


def check(name, cond, detail=""):
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name} {detail}")
    if not cond:
        FAILS.append(name)


def post_json(path: str, payload: dict):
    req = urllib.request.Request(BASE + path,
                                 data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    return urllib.request.urlopen(req)


def read_sse(resp) -> list[dict]:
    events = []
    for raw in resp.read().decode("utf-8").split("\n\n"):
        ev = None
        data = None
        for line in raw.splitlines():
            if line.startswith("event: "):
                ev = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if ev:
            events.append({"event": ev, "data": data})
    return events


def chat(message: str) -> list[dict]:
    resp = post_json("/api/agent/chat", {"session_id": SESSION["session_id"], "message": message})
    events = read_sse(resp)
    _track_session(events)
    return events


def upload(path: str) -> dict:
    boundary = "----mvpe2e"
    with open(path, "rb") as f:
        content = f.read()
    fname = path.replace("\\", "/").split("/")[-1]
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"session_id\"\r\n\r\n"
            f"{SESSION['session_id']}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"{fname}\"\r\nContent-Type: image/png\r\n\r\n").encode() + content + \
        f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(BASE + "/api/materials/upload", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                                 method="POST")
    return json.loads(urllib.request.urlopen(req).read())


def last_message(events):
    msgs = [e["data"]["content"] for e in events if e["event"] == "message"]
    return msgs[-1] if msgs else ""


def states(events):
    return [e["data"] for e in events if e["event"] == "state"]


def _track_session(events):
    """从 state 事件里回填 session_id，保证后续轮次延续同一会话。"""
    for e in events:
        if e["event"] == "state" and e["data"].get("session_id"):
            SESSION["session_id"] = e["data"]["session_id"]


print("== 1. 健康检查 ==")
health = json.loads(urllib.request.urlopen(BASE + "/api/health").read())
check("health", health.get("status") == "ok", str(health))

print("\n== 2. 首轮：表达目标（部分画像字段应被抽取，剩余追问） ==")
ev = chat("我是2026届本科毕业生，准备在苏州创业，有什么政策可以申请？")
st = states(ev)[-1]
p = st["profile"]
check("抽取 城市=苏州", p.get("城市") == "苏州")
check("抽取 学历=本科", p.get("学历") == "本科")
check("抽取 毕业年份=2026", p.get("毕业年份") == 2026)
check("抽取 状态=创业", p.get("状态") == "创业")
check("保持 stage=collect_profile", st["stage"] == "collect_profile")
check("追问缺失字段", "第一次创业" in last_message(ev) and "哪个区" in last_message(ev), last_message(ev)[:60])
SESSION["session_id"] = st["session_id"]

print("\n== 3. 补全信息 → 触发分析链路 ==")
ev = chat("是第一次创业，公司注册在工业园区")
tools = [e["data"]["tool"] for e in ev if e["event"] == "tool_call"]
check("依次调用 PolicySearch/Eligibility/Plan",
      tools[:1] == ["PolicySearch"] and "Eligibility" in tools and "Plan" in tools, str(tools))
st = states(ev)[-1]
check("stage=await_material", st["stage"] == "await_material")
elig = {e["policy_id"]: e["overall"] for e in st["eligibility"]}
check("一次性创业补贴 PASS", elig.get("su-startup-subsidy") == "PASS")
check("场地租金补贴 PASS", elig.get("su-rent-subsidy") == "PASS")
check("租房补贴 UNKNOWN(缺社保月数)", elig.get("su-housing") == "UNKNOWN")
check("求职补贴 UNKNOWN(缺困难情形)", elig.get("su-hardship-subsidy") == "UNKNOWN")
check("落户 PASS", elig.get("su-hukou") == "PASS")
check("生成办理步骤", len(st["plan"]) > 0, f"{len(st['plan'])} 步")
check("mock 模式 plan_source=template", st.get("plan_source") == "template")

print("\n== 4. 上传身份证（识别+字段抽取） ==")
r = upload("app/data/sample_materials/身份证_张三.png")
check("识别为 身份证明", r["record"]["doc_type"] == "身份证明")
check("抽取姓名=张三", r["record"]["fields"].get("姓名") == "张三")

print("\n== 5. 上传营业执照 ==")
r = upload("app/data/sample_materials/营业执照_星辉科技.png")
check("识别为 营业执照", r["record"]["doc_type"] == "营业执照")
check("法定代表人=张三", r["record"]["fields"].get("法定代表人") == "张三")

print("\n== 6. 上传申请表（姓名李四 → 应检出跨材料冲突） ==")
r = upload("app/data/sample_materials/创业补贴申请表_李四.png")
conf = r["check"]["conflicts"]
check("检出姓名冲突", any("不一致" in c["detail"] for c in conf),
      conf[0]["detail"] if conf else "无冲突")
check("缺失清单包含 学历证明", "学历证明" in r["check"]["missing"], str(r["check"]["missing"]))
check("readiness=建议补件后提交", r["check"]["readiness"] == "建议补件后提交")

print("\n== 7. 生成预检报告 ==")
ev = chat("生成报告")
st = states(ev)[-1]
rep = st["report"]
check("report 生成", rep is not None)
check("stage=report", st["stage"] == "report")
check("报告含缺失材料", "学历证明" in rep["missing"])
check("报告含待修改冲突", any("不一致" in x for x in rep["to_fix"]))
check("报告边界声明", "不构成正式审批意见" in last_message(ev))

print("\n== 8. 非苏州城市边界（新会话） ==")
SESSION["session_id"] = None
ev = chat("我是2026届本科毕业生，准备在郑州创业，有什么政策可以申请？")
ev2 = chat("郑州，本科，2026届，创业，第一次创业，注册在金水区")
check("不编造：明确提示仅覆盖苏州", "仅覆盖" in last_message(ev2), last_message(ev2)[:80])

print("\n== 9. 跨领域路由：居住证全流程（新会话） ==")
SESSION["session_id"] = None
ev = chat("我不是苏州户口，在苏州工作租房子住了8个月了，想办一张居住证")
st = states(ev)[-1]
check("路由到居住证领域", st["domain"] and st["domain"]["id"] == "suzhou_residence", str(st.get("domain")))
p = st["profile"]
check("抽取 城市=苏州", p.get("城市") == "苏州")
check("抽取 居住事由=合法稳定就业", p.get("居住事由") == "合法稳定就业")
check("抽取 居住登记月数=8", p.get("居住登记月数") == 8)
elig = {e["policy_id"]: e["overall"] for e in st["eligibility"]}
check("居住证申领 PASS", elig.get("sz-jzz-apply") == "PASS")
check("签注 UNKNOWN(无凭证)", elig.get("sz-jzz-renew") == "UNKNOWN")

print("\n== 10. 居住证画像不足时追问（新会话） ==")
SESSION["session_id"] = None
ev = chat("我想办居住证")
st = states(ev)[-1]
check("路由到居住证领域", st["domain"] and st["domain"]["id"] == "suzhou_residence")
check("追问 居住事由/登记月数", "居住事由" in last_message(ev) or "工作就业" in last_message(ev),
      last_message(ev)[:80])
ev2 = chat("我在苏州上班，租房住了3个月")
st2 = states(ev2)[-1]
elig2 = {e["policy_id"]: e["overall"] for e in st2["eligibility"]}
check("登记不满半年 → 申领 FAIL", elig2.get("sz-jzz-apply") == "FAIL")

print("\n== 11. 模糊目标 → 列出可选领域（新会话） ==")
SESSION["session_id"] = None
ev = chat("我想办点事")
check("列出领域清单引导", "居住证" in last_message(ev) and "创业" in last_message(ev),
      last_message(ev)[:80])
ev2 = chat("办居住证")
check("二次输入可路由", states(ev2)[-1]["domain"]["id"] == "suzhou_residence")

print("\n== 12. 领域 API ==")
domains = json.loads(urllib.request.urlopen(BASE + "/api/domains").read())
check("/api/domains 返回 2 个领域", len(domains) == 2, str([d["domain_id"] for d in domains]))

print("\n================")
print("FAILED:", FAILS if FAILS else "无，全部通过 ✅")
sys.exit(1 if FAILS else 0)
