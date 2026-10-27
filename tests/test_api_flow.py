from pathlib import Path
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
import json
import pytest
from fastapi.testclient import TestClient
from studyagent.config import Settings


@pytest.fixture
def demo(tmp_path):
    from studyagent.main import create_app

    settings = Settings(
        _env_file=None, STUDYAGENT_PROVIDER="fake", user_id="test-" + str(uuid4()), runtime_dir=tmp_path
    )
    app = create_app(settings)
    with TestClient(app) as client:
        yield client, app, settings


def space(client, name="梯度课程", kind="course"):
    r = client.post(
        "/api/spaces",
        json={"name": name, "kind": kind, "topic": "machine learning gradient descent 梯度下降"},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def setup(client):
    sid = space(client)
    content = Path("data/demo_gradient.md").read_bytes()
    r = client.post(f"/api/spaces/{sid}/documents", files={"file": ("gradient.md", content, "text/markdown")})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "accepted", r.text
    view = client.get(f"/api/spaces/{sid}/overview").json()
    assert view["concepts"]
    return sid, view


def test_full_loop_persistent_resume_idempotent_stop(demo):
    client, app, settings = demo
    sid, view = setup(client)
    chat = client.post("/api/chat", json={"space_id": sid, "message": "请解释梯度"}).json()
    assert chat["citations"] and chat["decision"]["action"] == "answer", chat
    r = client.post(f"/api/spaces/{sid}/sessions", json={"concept_id": view["concepts"][0]["id"]})
    assert r.status_code == 200, r.text
    session = r.json()
    assert session["status"] == "waiting", session
    assert "correct_index" not in json.dumps(session) and "rubric" not in json.dumps(session)
    session_id = session["id"]
    quiz = session["quiz"]
    thread = session["thread_id"]
    body = {"quiz_id": quiz["id"], "submission_id": str(uuid4()), "answer": quiz["options"][1]}
    wrong = client.post(f"/api/spaces/{sid}/sessions/{session_id}/answer", json=body).json()
    assert wrong["feedback"]["correct"] is False and wrong["mode"] == "example", wrong
    assert wrong["quiz"]["id"] != quiz["id"]
    before = app.state.db.one("SELECT sum(attempts) AS n FROM mastery WHERE space_id=%s", (sid,))["n"]
    duplicate = client.post(f"/api/spaces/{sid}/sessions/{session_id}/answer", json=body)
    assert duplicate.status_code == 200
    assert app.state.db.one("SELECT sum(attempts) AS n FROM mastery WHERE space_id=%s", (sid,))["n"] == before
    expired = client.post(
        f"/api/spaces/{sid}/sessions/{session_id}/answer", json=dict(body, submission_id=str(uuid4()))
    )
    assert expired.status_code == 409
    # Reconstruct app and checkpointer (same persistent DB); no in-memory session reuse.
    from studyagent.main import create_app

    with TestClient(create_app(settings)) as restarted:
        restored = restarted.get(f"/api/spaces/{sid}/sessions/{session_id}").json()
        assert restored["quiz"]["id"] == wrong["quiz"]["id"] and restored["thread_id"] == thread
        good = restarted.post(
            f"/api/spaces/{sid}/sessions/{session_id}/answer",
            json={
                "quiz_id": restored["quiz"]["id"],
                "submission_id": str(uuid4()),
                "answer": restored["quiz"]["options"][0],
            },
        ).json()
        assert good["feedback"]["correct"] is True, good
        assert good["status"] == "waiting"
        stopped = restarted.post(f"/api/spaces/{sid}/sessions/{session_id}/stop", json={}).json()
        assert stopped["status"] == "stopped" and stopped["quiz"] is None
        calls = app.state.db.one("SELECT count(*) AS n FROM model_calls")["n"]
        assert restarted.post(f"/api/spaces/{sid}/sessions/{session_id}/resume", json={}).status_code == 409
        assert app.state.db.one("SELECT count(*) AS n FROM model_calls")["n"] == calls


def test_cross_space_objects_and_chat_scope(demo):
    client, app, _ = demo
    first, view = setup(client)
    second = space(client, "第二课程")
    cid = view["concepts"][0]["id"]
    doc = view["documents"][0]["id"]
    assert client.post(f"/api/spaces/{second}/sessions", json={"concept_id": cid}).status_code == 404
    assert client.get(f"/api/spaces/{second}/documents/{doc}/file").status_code == 404
    session = client.post(f"/api/spaces/{first}/sessions", json={"concept_id": cid}).json()
    assert client.get(f"/api/spaces/{second}/sessions/{session['id']}").status_code == 404
    chat = client.post("/api/chat", json={"space_id": first, "message": "什么是梯度"}).json()
    assert (
        client.post(
            "/api/chat", json={"space_id": second, "chat_id": chat["chat_id"], "message": "继续"}
        ).status_code
        == 404
    )
    assert client.post("/api/chat", json={"message": "解释一下"}).json()["decision"]["action"] == "clarify"
    assert client.get(f"/api/spaces/{second}/overview").json()["concepts"] == []


def test_concurrent_submission_cannot_double_update(demo):
    client, app, _ = demo
    sid, view = setup(client)
    session = client.post(
        f"/api/spaces/{sid}/sessions", json={"concept_id": view["concepts"][0]["id"]}
    ).json()
    q = session["quiz"]
    body = {"quiz_id": q["id"], "submission_id": str(uuid4()), "answer": q["options"][0]}
    url = f"/api/spaces/{sid}/sessions/{session['id']}/answer"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.post(url, json=body), range(2)))
    assert [r.status_code for r in results] == [200, 200]
    assert app.state.db.one("SELECT count(*) AS n FROM attempts WHERE quiz_id=%s", (q["id"],))["n"] == 1


def test_preference_revision_scope_and_failure_recovery(demo, monkeypatch):
    client, app, _ = demo
    sid, view = setup(client)
    for content in ["我喜欢中文例子", "我偏好简短英文解释"]:
        r = client.post(f"/api/spaces/{sid}/preferences", json={"content": content})
        assert r.status_code == 200 and r.json()["save"]
    memories = app.state.db.all(
        "SELECT * FROM memories WHERE source_space_id=%s AND kind='preference' ORDER BY created_at", (sid,)
    )
    assert len(memories) == 2 and not memories[0]["valid"] and memories[1]["valid"]
    from studyagent.providers import ProviderError

    original = app.state.provider.complete

    def unavailable(task, *args, **kwargs):
        if task == "teach":
            raise ProviderError("故障注入：超时")
        return original(task, *args, **kwargs)

    monkeypatch.setattr(app.state.provider, "complete", unavailable)
    failed = client.post(f"/api/spaces/{sid}/sessions", json={"concept_id": view["concepts"][0]["id"]}).json()
    assert failed["status"] == "error" and failed["quiz"] is None, failed
    monkeypatch.setattr(app.state.provider, "complete", original)
    recovered = client.post(f"/api/spaces/{sid}/sessions/{failed['id']}/resume", json={}).json()
    assert recovered["status"] == "waiting" and recovered["quiz"], recovered


def test_prerequisite_then_repeated_success_advances(demo):
    from psycopg.types.json import Jsonb
    from studyagent.db import uid

    client, app, _ = demo
    sid, view = setup(client)
    prerequisite = view["concepts"][0]["id"]
    target = uid()
    app.state.db.execute(
        "INSERT INTO concepts(id,space_id,name,description,evidence_ids) VALUES (%s,%s,%s,%s,%s)",
        (target, sid, "目标：梯度下降", "根据梯度更新参数", Jsonb(view["concepts"][0]["evidence_ids"])),
    )
    graph = {
        "nodes": [{"id": prerequisite, "name": "导数"}, {"id": target, "name": "梯度下降"}],
        "edges": [
            {
                "source": prerequisite,
                "target": target,
                "status": "accepted",
                "evidence_ids": view["concepts"][0]["evidence_ids"],
            }
        ],
    }
    app.state.db.execute("UPDATE spaces SET graph=%s WHERE id=%s", (Jsonb(graph), sid))
    session = client.post(f"/api/spaces/{sid}/sessions", json={"concept_id": target}).json()
    assert session["current_concept_id"] == prerequisite
    for _ in range(2):
        q = session["quiz"]
        session = client.post(
            f"/api/spaces/{sid}/sessions/{session['id']}/answer",
            json={"quiz_id": q["id"], "submission_id": str(uuid4()), "answer": q["options"][0]},
        ).json()
    assert session["status"] == "waiting" and session["current_concept_id"] == target, session
    assert (
        app.state.db.one(
            "SELECT attempts FROM mastery WHERE space_id=%s AND concept_id=%s", (sid, prerequisite)
        )["attempts"]
        == 2
    )


def test_checkpoint_replay_after_grade_commit_is_idempotent(demo, monkeypatch):
    client, app, _ = demo
    sid, view = setup(client)
    session = client.post(
        f"/api/spaces/{sid}/sessions", json={"concept_id": view["concepts"][0]["id"]}
    ).json()
    q = session["quiz"]
    body = {"quiz_id": q["id"], "submission_id": str(uuid4()), "answer": q["options"][0]}
    original = app.state.db.event
    crash_once = [True]

    def crash(space_id, kind, payload, session_id=None):
        if kind == "assess_and_update" and crash_once[0]:
            crash_once[0] = False
            raise RuntimeError("injected crash after attempt transaction before graph checkpoint")
        return original(space_id, kind, payload, session_id)

    monkeypatch.setattr(app.state.db, "event", crash)
    failed = client.post(f"/api/spaces/{sid}/sessions/{session['id']}/answer", json=body).json()
    assert failed["status"] == "error"
    monkeypatch.setattr(app.state.db, "event", original)
    resumed = client.post(f"/api/spaces/{sid}/sessions/{session['id']}/resume", json={}).json()
    assert resumed["status"] == "waiting", resumed
    assert app.state.db.one("SELECT count(*) AS n FROM attempts WHERE quiz_id=%s", (q["id"],))["n"] == 1
    assert (
        app.state.db.one(
            "SELECT attempts FROM mastery WHERE space_id=%s AND concept_id=%s", (sid, q["concept_id"])
        )["attempts"]
        == 1
    )


def test_concurrent_sessions_preserve_both_mastery_updates(demo, monkeypatch):
    from threading import Barrier, Lock

    client, app, _ = demo
    sid, view = setup(client)
    concept_id = view["concepts"][0]["id"]
    sessions = [
        client.post(f"/api/spaces/{sid}/sessions", json={"concept_id": concept_id}).json() for _ in range(2)
    ]
    # Force the two legacy, unlocked reads to observe the same initial row.
    original = app.state.db.one
    barrier, counter_lock = Barrier(2), Lock()
    read_count = 0

    def simultaneous_reads(query, params=()):
        nonlocal read_count
        result = original(query, params)
        if query.startswith("SELECT * FROM mastery"):
            with counter_lock:
                read_count += 1
                wait = read_count <= 2
            if wait:
                barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(app.state.db, "one", simultaneous_reads)

    def submit(session):
        quiz = session["quiz"]
        return client.post(
            f"/api/spaces/{sid}/sessions/{session['id']}/answer",
            json={"quiz_id": quiz["id"], "submission_id": str(uuid4()), "answer": quiz["options"][0]},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(submit, sessions))
    assert all(response.status_code == 200 for response in responses)
    assert all(response.json()["status"] != "error" for response in responses)
    assert original("SELECT count(*) AS n FROM attempts WHERE space_id=%s", (sid,))["n"] == 2
    mastery = original(
        "SELECT attempts,score,streak FROM mastery WHERE space_id=%s AND concept_id=%s", (sid, concept_id)
    )
    assert mastery == {"attempts": 2, "score": 0.85, "streak": 2}


def test_final_successful_submission_can_be_retried_without_tools(demo, monkeypatch):
    client, app, _ = demo
    sid, view = setup(client)
    session = client.post(
        f"/api/spaces/{sid}/sessions", json={"concept_id": view["concepts"][0]["id"]}
    ).json()
    url = f"/api/spaces/{sid}/sessions/{session['id']}/answer"
    for _ in range(2):
        quiz = session["quiz"]
        body = {"quiz_id": quiz["id"], "submission_id": str(uuid4()), "answer": quiz["options"][0]}
        session = client.post(url, json=body).json()
    assert session["status"] == "completed"

    def unexpected_run(*args, **kwargs):
        raise AssertionError("Retrying a completed attempt must not run the learning graph")

    monkeypatch.setattr(app.state.learning, "_run", unexpected_run)
    retry = client.post(url, json=body)
    assert retry.status_code == 200
    assert retry.json() == session
    assert client.post(url, json=dict(body, answer="different answer")).status_code == 409
    assert (
        app.state.db.one("SELECT count(*) AS n FROM attempts WHERE session_id=%s", (session["id"],))["n"] == 2
    )


def test_answer_survives_quiz_commit_before_checkpoint(demo, monkeypatch):
    client, app, _ = demo
    sid, view = setup(client)
    original = app.state.db.event

    def crash(space_id, kind, payload, session_id=None):
        if kind == "teach_and_quiz":
            raise RuntimeError("Injected crash after quiz transaction and before checkpoint")
        return original(space_id, kind, payload, session_id)

    monkeypatch.setattr(app.state.db, "event", crash)
    session = client.post(
        f"/api/spaces/{sid}/sessions", json={"concept_id": view["concepts"][0]["id"]}
    ).json()
    assert session["status"] == "error" and session["quiz"]
    monkeypatch.setattr(app.state.db, "event", original)
    quiz = session["quiz"]
    body = {"quiz_id": quiz["id"], "submission_id": str(uuid4()), "answer": quiz["options"][0]}
    response = client.post(f"/api/spaces/{sid}/sessions/{session['id']}/answer", json=body)
    assert response.status_code == 200
    assert response.json()["feedback"]["correct"] is True
    assert response.json()["quiz"]["id"] != quiz["id"]
    assert app.state.db.one("SELECT count(*) AS n FROM attempts WHERE quiz_id=%s", (quiz["id"],))["n"] == 1
    assert app.state.db.session(sid, session["id"])["state"].get("pending_submission") is None


def test_lesson_cites_only_excerpts_actually_sent_after_trimming(demo, monkeypatch):
    client, app, settings = demo
    sid = space(client)
    content = (
        "梯度下降通过沿梯度反方向更新参数来降低可微损失函数。学习率控制每次更新的步长。\n" * 200
    ).encode()
    upload = client.post(
        f"/api/spaces/{sid}/documents", files={"file": ("long.md", content, "text/markdown")}
    )
    assert upload.status_code == 200 and upload.json()["status"] == "accepted"
    concepts = client.get(f"/api/spaces/{sid}/overview").json()["concepts"]
    settings.context_token_budget = 4000
    visible = []
    original_complete = app.state.provider.complete

    def capture_visible(task, *args, **kwargs):
        result = original_complete(task, *args, **kwargs)
        if task == "teach":
            visible.extend(app.state.provider.last_evidence)
        return result

    monkeypatch.setattr(app.state.provider, "complete", capture_visible)
    response = client.post(f"/api/spaces/{sid}/sessions", json={"concept_id": concepts[0]["id"]})
    assert response.status_code == 200
    session = response.json()
    assert session["status"] == "waiting", session
    assert 0 < len(visible) < 6  # This fixture must exercise actual context trimming.
    visible_text = {entry["id"]: entry["text"] for entry in visible}
    assert {citation["evidence_id"]: citation["text"] for citation in session["citations"]} == visible_text
    assert session["decision"]["evidence_ids"] == list(visible_text)
    assert session["quiz"]["evidence_ids"] == list(visible_text)
