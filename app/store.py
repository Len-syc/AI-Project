"""会话存储。MVP 用进程内字典（重启即清空，演示够用）；
后续如需持久化，只需把这里换成 SQLite，其余代码不动。"""
import uuid
from app.schemas import UserProfile

SESSIONS: dict = {}


def new_session() -> dict:
    sid = uuid.uuid4().hex[:12]
    SESSIONS[sid] = {
        "session_id": sid,
        "stage": "collect_profile",
        "profile": UserProfile().model_dump(),
        "profile_sources": {},       # field -> user / inferred
        "messages": [],
        "turns": 0,
        "policy_ids": [],
        "eligibility": [],           # list[EligibilityResult]
        "plan": [],
        "materials": [],             # list[MaterialRecord]
        "material_check": None,
        "report": None,
        "goal": "",
    }
    return SESSIONS[sid]


def get_session(sid: str) -> dict | None:
    return SESSIONS.get(sid)
