"""会话存储。MVP 用进程内字典（重启即清空，演示够用）；
后续如需持久化，只需把这里换成 SQLite，其余代码不动。"""
import uuid

SESSIONS: dict = {}


def new_session_fields() -> dict:
    return {
        "stage": "collect_profile",
        "domain": None,              # 领域包 id，意图路由后填充
        "profile": {},               # 领域 schema 驱动的动态字段
        "profile_sources": {},       # field -> user / inferred
        "messages": [],
        "turns": 0,
        "policy_ids": [],
        "eligibility": [],
        "plan": [],
        "plan_source": None,         # llm = AI 动态生成 | template = 模板兜底
        "plan_summary": None,        # AI 生成的一句话方案摘要
        "materials": [],
        "material_check": None,
        "report": None,
        "goal": "",
    }


def new_session() -> dict:
    sid = uuid.uuid4().hex[:12]
    SESSIONS[sid] = {"session_id": sid, **new_session_fields()}
    return SESSIONS[sid]


def get_session(sid: str) -> dict | None:
    return SESSIONS.get(sid)
