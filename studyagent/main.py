"""Local-only FastAPI entry point; never sends private quiz fields to the client."""

from contextlib import asynccontextmanager
import time
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from psycopg.types.json import Jsonb
from .config import Settings, ROOT
from .db import Database, DomainError, uid
from .schemas import SpaceIn, ChatIn, SessionIn, Submission, Admit, PreferenceIn, Preference
from .providers import Provider, ProviderError
from .knowledge import Knowledge
from .learning import Learning


def create_app(settings=None, provider=None):
    settings = settings or Settings()
    db = Database(settings)
    provider = provider or Provider(settings, log_call=db.log_call)
    knowledge = Knowledge(db, provider, settings)
    learning = Learning(db, provider, knowledge, settings)

    @asynccontextmanager
    async def lifespan(app):
        db.migrate()
        settings.runtime_dir.mkdir(parents=True, exist_ok=True)
        yield

    app = FastAPI(title="StudyAgent", version="0.1.0", lifespan=lifespan)
    app.state.db, app.state.learning, app.state.provider = db, learning, provider

    @app.exception_handler(DomainError)
    async def domain_error(request, exc):
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    @app.exception_handler(ProviderError)
    async def provider_error(request, exc):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return JSONResponse(status_code=403, content={"detail": "仅允许本机页面的同源请求。"})
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Server-Timing"] = f"app;dur={(time.perf_counter() - started) * 1000:.1f}"
        return response

    @app.get("/api/health")
    def health():
        result = provider.health()
        result.update(
            database=bool(db.one("SELECT 1 AS ok")),
            provider=settings.provider,
            mode_label="离线模拟，仅验证流程" if settings.provider == "fake" else "DeepSeek 真实服务",
        )
        return result

    @app.get("/api/spaces")
    def spaces():
        return db.all(
            "SELECT id,name,kind,topic,created_at FROM spaces WHERE owner_id=%s ORDER BY created_at DESC",
            (settings.user_id,),
        )

    @app.post("/api/spaces")
    def create_space(body: SpaceIn):
        if not body.name.strip() or not body.topic.strip():
            raise DomainError("空间名称和学习主题不能为空。")
        return db.create_space(body.name.strip(), body.kind, body.topic.strip())

    @app.get("/api/spaces/{space_id}/overview")
    def overview(space_id: str):
        space = db.space(space_id)
        documents = db.all(
            "SELECT d.id,d.filename,sd.status,sd.reason,d.source_url FROM documents d JOIN space_documents sd ON sd.document_id=d.id WHERE sd.space_id=%s ORDER BY d.created_at DESC",
            (space_id,),
        )
        sessions = db.all(
            "SELECT id,status,goal_concept_id,current_concept_id,thread_id FROM sessions WHERE space_id=%s ORDER BY created_at DESC LIMIT 30",
            (space_id,),
        )
        memories = db.all(
            "SELECT id,kind,content,valid,created_at FROM memories WHERE source_space_id=%s AND owner_id=%s AND valid=true ORDER BY created_at DESC LIMIT 20",
            (space_id, settings.user_id),
        )
        return {
            "space": space,
            "documents": documents,
            "concepts": knowledge.concepts(space_id),
            "graph": space["graph"],
            "sessions": sessions,
            "memories": memories,
        }

    @app.post("/api/spaces/{space_id}/documents")
    def upload(space_id: str, file: UploadFile = File(...), source_url: str = Form("")):
        db.space(space_id)
        content = file.file.read(settings.upload_max_bytes + 1)
        if len(content) > settings.upload_max_bytes:
            raise DomainError("文件超过 20 MB 上限。", 413)
        if len(source_url) > 2000:
            raise DomainError("来源 URL 过长。")
        return knowledge.ingest(space_id, file.filename or "upload.pdf", content, source_url)

    @app.get("/api/spaces/{space_id}/documents/{document_id}/file")
    def document_file(space_id: str, document_id: str):
        db.space(space_id)
        row = db.one(
            "SELECT d.* FROM documents d JOIN space_documents sd ON sd.document_id=d.id WHERE d.id=%s AND sd.space_id=%s",
            (document_id, space_id),
        )
        if not row:
            raise DomainError("文档不属于当前空间。", 404)
        path = Path(row["file_path"]).resolve()
        if not path.is_relative_to(settings.runtime_dir.resolve()) or not path.is_file():
            raise DomainError("源文件不存在。", 404)
        return FileResponse(
            path,
            filename=row["filename"],
            media_type="application/pdf" if path.suffix == ".pdf" else "text/plain",
            content_disposition_type="inline",
        )

    @app.post("/api/spaces/{space_id}/admit")
    def admit(space_id: str, body: Admit):
        return knowledge.admit(space_id, body.source_space_id, body.document_id)

    @app.post("/api/chat")
    def chat(body: ChatIn):
        if not body.space_id:
            return {
                "chat_id": None,
                "answer": "请先选择 Course 或 Focus 空间，再提出问题。",
                "citations": [],
                "decision": {
                    "action": "clarify",
                    "space_id": "",
                    "concept_id": None,
                    "evidence_ids": [],
                    "reason": "空间范围未指定。",
                },
                "gap": "",
                "provider": settings.provider,
            }
        space = db.space(body.space_id)
        chat_id = body.chat_id or uid()
        with db.lock("chat:" + chat_id):
            if body.chat_id:
                row = db.one(
                    "SELECT * FROM chats WHERE id=%s AND space_id=%s AND owner_id=%s",
                    (chat_id, space["id"], settings.user_id),
                )
                if not row:
                    raise DomainError("对话不属于当前空间。", 404)
            else:
                row = db.one(
                    "INSERT INTO chats(id,space_id,owner_id) VALUES (%s,%s,%s) RETURNING *",
                    (chat_id, space["id"], settings.user_id),
                )
            corrections = list(row["corrections"])
            if any(
                word in body.message.lower()
                for word in ["纠正", "更正", "不是", "correction", "actually", "i meant"]
            ):
                corrections.append(body.message[:1500])
                corrections = corrections[-5:]
            state = {
                "space_id": space["id"],
                "space_name": space["name"],
                "current_concept": None,
                "unresolved": [body.message],
                "corrections": corrections,
            }
            if not body.baseline:
                state["mastery"] = knowledge.concepts(space["id"])
                state["preferences"] = db.all(
                    "SELECT content FROM memories WHERE source_space_id=%s AND owner_id=%s AND kind='preference' AND valid=true",
                    (space["id"], settings.user_id),
                )
            result = knowledge.answer(
                space["id"], body.message, history=row["history"], state=state, baseline=body.baseline
            )
            history = row["history"] + [
                {"role": "user", "content": body.message},
                {"role": "assistant", "content": result["answer"], "citations": result.get("citations", [])},
            ]
            db.execute(
                "UPDATE chats SET history=%s,corrections=%s WHERE id=%s",
                (Jsonb(history), Jsonb(corrections), chat_id),
            )
            return dict(result, chat_id=chat_id)

    @app.get("/api/spaces/{space_id}/chats/{chat_id}")
    def chat_history(space_id: str, chat_id: str):
        db.space(space_id)
        row = db.one(
            "SELECT id,history FROM chats WHERE id=%s AND space_id=%s AND owner_id=%s",
            (chat_id, space_id, settings.user_id),
        )
        if not row:
            raise DomainError("对话不属于当前空间。", 404)
        return row

    @app.post("/api/spaces/{space_id}/sessions")
    def start(space_id: str, body: SessionIn):
        return learning.start(space_id, body.concept_id)

    @app.get("/api/spaces/{space_id}/sessions/{session_id}")
    def session(space_id: str, session_id: str):
        return learning.view(space_id, session_id)

    @app.post("/api/spaces/{space_id}/sessions/{session_id}/answer")
    def answer(space_id: str, session_id: str, body: Submission):
        return learning.submit(space_id, session_id, body.model_dump())

    @app.post("/api/spaces/{space_id}/sessions/{session_id}/resume")
    def resume(space_id: str, session_id: str):
        return learning.resume(space_id, session_id)

    @app.post("/api/spaces/{space_id}/sessions/{session_id}/stop")
    def stop(space_id: str, session_id: str):
        return learning.stop(space_id, session_id)

    @app.post("/api/spaces/{space_id}/preferences")
    def preference(space_id: str, body: PreferenceIn):
        db.space(space_id)
        with db.lock("preference:" + space_id):
            existing = db.all(
                "SELECT content FROM memories WHERE source_space_id=%s AND owner_id=%s AND kind='preference' AND valid=true",
                (space_id, settings.user_id),
            )
            result = provider.complete(
                "preference", {"content": body.content, "existing": existing, "scope": space_id}, Preference
            )
            db.event(space_id, "memory_validation", result)
            if not result["save"]:
                return result
            if any(m["content"] == result["content"] for m in existing):
                return dict(result, reason="相同偏好已存在，无需重复保存。")
            mid = uid()
            with db.connect() as conn, conn.transaction():
                conn.execute(
                    "UPDATE memories SET valid=false,superseded_by=%s WHERE source_space_id=%s AND owner_id=%s AND kind='preference' AND valid=true",
                    (mid, space_id, settings.user_id),
                )
                conn.execute(
                    "INSERT INTO memories(id,owner_id,source_space_id,kind,content,source_id) VALUES (%s,%s,%s,%s,%s,%s)",
                    (mid, settings.user_id, space_id, "preference", result["content"], "explicit-user"),
                )
            return dict(result, id=mid)

    @app.get("/api/spaces/{space_id}/traces")
    def traces(space_id: str, session_id: str | None = None):
        db.space(space_id)
        if session_id:
            db.session(space_id, session_id)
            return db.all(
                "SELECT * FROM events WHERE space_id=%s AND session_id=%s ORDER BY id DESC LIMIT 80",
                (space_id, session_id),
            )
        return db.all("SELECT * FROM events WHERE space_id=%s ORDER BY id DESC LIMIT 80", (space_id,))

    @app.get("/")
    def index():
        return FileResponse(ROOT / "studyagent/static/index.html")

    app.mount("/static", StaticFiles(directory=ROOT / "studyagent/static"), name="static")
    return app


app = create_app()
