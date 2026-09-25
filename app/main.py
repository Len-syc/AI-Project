"""FastAPI 入口。
  POST /api/agent/chat            主对话（SSE 流式返回工具调用过程与最终回复）
  POST /api/materials/upload      材料上传 → 识别 → 预检
  GET  /api/policies              政策库列表（调试用）
  GET  /api/agent/session/{sid}   会话快照（前端刷新用）
  GET  /                          单文件演示前端
"""
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from app import config
from app.store import new_session, get_session
from app.agent.pipeline import handle_chat, build_report
from app.agent import tool_gateway as gateway
from app.schemas import ChatRequest


@asynccontextmanager
async def lifespan(_: FastAPI):
    os.makedirs(config.UPLOAD_DIR, exist_ok=True)
    yield

app = FastAPI(title="政务办事智能辅助 Agent · MVP", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # 演示环境；上线前收敛
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok", "llm_mode": config.LLM_MODE}


@app.post("/api/agent/chat")
async def agent_chat(req: ChatRequest):
    session = get_session(req.session_id) if req.session_id else None
    if session is None:
        session = new_session()

    async def gen():
        async for chunk in handle_chat(session, req.message):
            yield chunk

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.get("/api/agent/session/{sid}")
def agent_session(sid: str):
    session = get_session(sid)
    if not session:
        raise HTTPException(404, "session not found")
    from app.agent.pipeline import _snapshot
    return _snapshot(session)


@app.post("/api/materials/upload")
async def upload_material(session_id: str = Form(...), file: UploadFile = File(...)):
    session = get_session(session_id)
    if not session:
        raise HTTPException(404, "session not found")

    ext = os.path.splitext(file.filename or "")[1] or ".png"
    save_path = os.path.join(config.UPLOAD_DIR, f"{session_id}_{uuid.uuid4().hex[:6]}{ext}")
    with open(save_path, "wb") as f:
        f.write(await file.read())

    rec = await gateway.parse_document(save_path, file.filename or "upload" + ext)
    session["materials"].append(rec)

    required = sorted({m for t in session["plan"] for m in t.materials})
    check = await gateway.check_materials(session, required)
    session["material_check"] = check

    from app.agent.pipeline import _snapshot
    return {"record": rec.model_dump(), "check": check.model_dump(),
            "state": _snapshot(session)}


@app.get("/api/domains")
def list_domains():
    from app.tools.registry import load_domains
    return [{"domain_id": p.domain_id, "name": p.name, "description": p.description,
             "policy_count": len(p.policies)} for p in load_domains().values()]


@app.get("/api/policies")
def list_policies(domain: str | None = None):
    from app.tools.registry import load_domains
    packs = [load_domains()[domain]] if domain else list(load_domains().values())
    out = []
    for p in packs:
        for item in p.policies:
            d = item.model_dump()
            d["domain_id"] = p.domain_id
            out.append(d)
    return out


# ---------- 前端静态托管 ----------
WEB_DIR = os.path.join(config.BASE_DIR, "web")
# 注意：samples 必须先于 /static 注册，否则会被 /static 前缀捕获
app.mount("/static/samples", StaticFiles(directory=config.SAMPLE_DIR), name="samples")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="web")


@app.get("/")
def index():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))
