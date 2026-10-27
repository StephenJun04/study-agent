"""One persistent LangGraph loop. Business effects are transactional and idempotent."""

from typing import TypedDict
from psycopg.types.json import Jsonb
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.postgres import PostgresSaver
from .db import uid, DomainError
from .schemas import Teaching, Grade, AgentDecision, EvidenceCheck


def update_mastery(previous, correct, error):
    old = previous or {"score": None, "attempts": 0, "streak": 0, "errors": []}
    score = (
        (0.6 if correct else 0.2)
        if old["score"] is None
        else max(0.0, min(1.0, old["score"] + (0.25 if correct else -0.3)))
    )
    return {
        "score": round(score, 3),
        "attempts": old["attempts"] + 1,
        "streak": old["streak"] + 1 if correct else 0,
        "errors": old["errors"] + ([] if correct else [error[:500]]),
    }


def choose_mode(mastery, last_correct):
    if last_correct is False:
        return "example"
    if not mastery or not mastery["attempts"]:
        return "explanation"
    return "quiz"


class FlowState(TypedDict, total=False):
    space_id: str
    session_id: str
    quiz_id: str
    submission: dict
    done: bool


class Learning:
    def __init__(self, db, provider, knowledge, settings):
        self.db, self.provider, self.knowledge, self.settings = db, provider, knowledge, settings

    def graph(self, saver):
        graph = StateGraph(FlowState)
        graph.add_node("prepare", self.prepare)
        graph.add_node("wait_for_student", self.wait_for_student)
        graph.add_node("assess", self.assess)
        graph.add_edge(START, "prepare")
        graph.add_conditional_edges(
            "prepare", lambda s: "end" if s.get("done") else "wait", {"end": END, "wait": "wait_for_student"}
        )
        graph.add_edge("wait_for_student", "assess")
        graph.add_edge("assess", "prepare")
        return graph.compile(checkpointer=saver)

    def mastery(self, space_id, concept_id):
        return self.db.one(
            "SELECT * FROM mastery WHERE space_id=%s AND concept_id=%s", (space_id, concept_id)
        )

    def mastered(self, space_id, concept_id):
        m = self.mastery(space_id, concept_id)
        return bool(m and m["score"] >= 0.8 and m["streak"] >= 2)

    def prerequisite(self, space_id, concept_id, seen=None):
        seen = set() if seen is None else seen
        if concept_id in seen:
            return None
        seen.add(concept_id)
        edges = self.db.space(space_id)["graph"].get("edges", [])
        for edge in edges:
            if edge.get("status") == "accepted" and edge["target"] == concept_id:
                pre = edge["source"]
                self.db.concept(space_id, pre)
                if not self.mastered(space_id, pre):
                    return self.prerequisite(space_id, pre, seen) or pre
        return None

    def save_state(self, session, **changes):
        state = dict(session["state"])
        state.update(changes)
        self.db.execute("UPDATE sessions SET state=%s WHERE id=%s", (Jsonb(state), session["id"]))
        return state

    def finish(self, session, status, message):
        self.save_state(
            session,
            error=None,
            explanation=message,
            quiz_id=None,
            decision=AgentDecision(
                action="complete" if status == "completed" else "stop",
                space_id=session["space_id"],
                concept_id=session["current_concept_id"],
                reason=message,
            ).model_dump(),
        )
        self.db.execute("UPDATE sessions SET status=%s WHERE id=%s", (status, session["id"]))
        self.db.event(session["space_id"], status, {"message": message}, session["id"])
        return {"done": True}

    def prepare(self, flow):
        s = self.db.session(flow["space_id"], flow["session_id"])
        if s["status"] in ("stopped", "completed", "needs_clarification"):
            return {"done": True}
        # A crash after committing a quiz but before checkpointing must reuse it.
        active = self.db.one(
            "SELECT id FROM quizzes WHERE session_id=%s AND status='active' ORDER BY sequence DESC LIMIT 1",
            (s["id"],),
        )
        if active:
            self.db.execute("UPDATE sessions SET status='waiting' WHERE id=%s", (s["id"],))
            return {"quiz_id": active["id"], "done": False}
        if s["step"] >= self.settings.max_session_steps:
            return self.finish(s, "needs_clarification", "达到本次学习步骤上限，请休息或重新选择目标。")
        current = s["current_concept_id"]
        recent = self.db.all(
            "SELECT a.correct,a.answer,a.feedback FROM attempts a JOIN quizzes q ON q.id=a.quiz_id "
            "WHERE a.session_id=%s AND q.concept_id=%s ORDER BY a.created_at DESC LIMIT 3",
            (s["id"], current),
        )
        if len(recent) == 3 and all(not a["correct"] for a in recent):
            return self.finish(
                s,
                "needs_clarification",
                "这个概念连续三次未通过。已保存错误记录，请调整目标或补充问题后重新开始。",
            )
        reason = "根据当前掌握状态选择教学方式。"
        if self.mastered(s["space_id"], current):
            if current != s["goal_concept_id"]:
                current = self.prerequisite(s["space_id"], s["goal_concept_id"]) or s["goal_concept_id"]
                reason = "前置概念已连续答对，返回学习目标。"
            else:
                edges = self.db.space(s["space_id"])["graph"].get("edges", [])
                next_ids = [
                    e["target"]
                    for e in edges
                    if e.get("status") == "accepted"
                    and e["source"] == current
                    and not self.mastered(s["space_id"], e["target"])
                    and not self.prerequisite(s["space_id"], e["target"])
                ]
                if not next_ids:
                    return self.finish(s, "completed", "目标已连续两次答对，前置条件满足；本次学习完成。")
                current = next_ids[0]
                self.db.execute("UPDATE sessions SET goal_concept_id=%s WHERE id=%s", (current, s["id"]))
                reason = "连续成功且前置条件满足，前进到关联概念。"
            self.db.event(s["space_id"], "advance", {"concept_id": current, "reason": reason}, s["id"])
        pre = self.prerequisite(s["space_id"], current)
        if pre:
            current, reason = pre, "目标的前置概念尚未掌握，先补前置知识。"
        concept = self.db.concept(s["space_id"], current)
        m = self.mastery(s["space_id"], current)
        last = self.db.one(
            "SELECT a.correct FROM attempts a JOIN quizzes q ON q.id=a.quiz_id "
            "WHERE a.session_id=%s AND q.concept_id=%s ORDER BY a.created_at DESC LIMIT 1",
            (s["id"], current),
        )
        mode = choose_mode(m, last["correct"] if last else None)
        evidence = self.knowledge.retrieve(s["space_id"], concept["name"] + " " + concept["description"])
        self.db.event(
            s["space_id"],
            "retrieve",
            {"call_id": uid(), "concept_id": current, "evidence_ids": [e["id"] for e in evidence]},
            s["id"],
        )
        check = self.provider.complete(
            "evidence_check",
            {
                "scope": self.db.space(s["space_id"])["topic"],
                "question": f"解释 {concept['name']}",
                "evidence": evidence,
            },
            EvidenceCheck,
        )
        self.db.event(s["space_id"], "retrieval_validation", check, s["id"])
        if not check["sufficient"] or check["conflicts"]:
            supplement = self.knowledge.answer(s["space_id"], f"解释 {concept['name']}")
            if supplement.get("gap") or not supplement.get("citations"):
                return self.finish(
                    s, "needs_clarification", "证据不足或存在冲突，未生成测验。请补充材料或澄清目标。"
                )
            evidence = [dict(c, id=c["evidence_id"]) for c in supplement["citations"]]
        if not evidence:
            return self.finish(s, "needs_clarification", "没有可验证的证据，无法开始此概念测验。")
        memories = self.db.all(
            "SELECT content FROM memories WHERE source_space_id=%s AND owner_id=%s AND valid=true AND kind='preference'",
            (s["space_id"], self.settings.user_id),
        )
        previous = self.db.all(
            "SELECT question FROM quizzes WHERE session_id=%s ORDER BY sequence DESC LIMIT 4", (s["id"],)
        )
        lesson = self.provider.complete(
            "teach",
            {
                "concept": concept,
                "mode": mode,
                "evidence": evidence,
                "recent_errors": m["errors"][-3:] if m else [],
                "previous_questions": previous,
                "preferences": memories,
                "question_variant": s["step"] + 1,
            },
            Teaching,
        )
        # Bind the public lesson/quiz provenance to the excerpts actually sent
        # after context budgeting, rather than every retrieval candidate.
        visible = getattr(self.provider, "last_evidence", None)
        if visible is not None:
            original = {e["id"]: e for e in evidence}
            evidence = [
                dict(original[eid], **item)
                for item in visible
                if (eid := item.get("id", item.get("evidence_id"))) in original
            ]
        if not evidence:
            return self.finish(
                s, "needs_clarification", "输入预算未保留可验证证据，未生成测验。请缩短偏好或增大上下文预算。"
            )
        decision = AgentDecision(
            action=mode,
            space_id=s["space_id"],
            concept_id=current,
            evidence_ids=[e["id"] for e in evidence],
            reason="正式讲解后作答错误，改用具体例子并重新测验。" if mode == "example" else reason,
        )
        if lesson["correct_index"] >= len(lesson["options"]):
            raise DomainError("模型生成的测验不合法，请重试。", 502)
        qid = uid()
        citations = [dict(e, evidence_id=e["id"]) for e in evidence]
        state = dict(
            s["state"],
            explanation=lesson["explanation"],
            mode=mode,
            quiz_id=qid,
            citations=citations,
            decision=decision.model_dump(),
            error=None,
            pending_submission=None,
        )
        with self.db.connect() as conn, conn.transaction():
            conn.execute(
                "INSERT INTO quizzes(id,session_id,space_id,concept_id,sequence,question,options,correct_index,rubric,answer_explanation,evidence_ids,mode) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    qid,
                    s["id"],
                    s["space_id"],
                    current,
                    s["step"] + 1,
                    lesson["question"],
                    Jsonb(lesson["options"]),
                    lesson["correct_index"],
                    lesson["rubric"],
                    lesson["answer_explanation"],
                    Jsonb(decision.evidence_ids),
                    mode,
                ),
            )
            conn.execute(
                "UPDATE sessions SET status='waiting',step=step+1,current_concept_id=%s,state=%s WHERE id=%s",
                (current, Jsonb(state), s["id"]),
            )
        self.db.event(
            s["space_id"],
            "teach_and_quiz",
            {
                "decision": decision.model_dump(),
                "quiz_id": qid,
                "call_id": uid(),
                "result": "quiz_created_waiting",
            },
            s["id"],
        )
        return {"quiz_id": qid, "done": False}

    def wait_for_student(self, flow):
        # Keep the interrupt node pure: re-entry cannot duplicate a quiz or external call.
        answer = interrupt({"quiz_id": flow["quiz_id"], "message": "等待学生提交；标准答案保留在服务端。"})
        return {"submission": answer}

    def assess(self, flow):
        s = self.db.session(flow["space_id"], flow["session_id"])
        if s["status"] == "stopped":
            return {"done": True}
        sub = flow["submission"]
        q = self.db.one(
            "SELECT * FROM quizzes WHERE id=%s AND session_id=%s AND space_id=%s",
            (sub["quiz_id"], s["id"], s["space_id"]),
        )
        if not q:
            raise DomainError("测验与会话不匹配。", 409)
        existing = self.db.one("SELECT * FROM attempts WHERE quiz_id=%s", (q["id"],))
        if existing:
            if existing["submission_id"] != sub["submission_id"] or existing["answer"] != sub["answer"]:
                raise DomainError("此测验已经提交，拒绝覆盖。", 409)
            return {"done": False}
        if q["status"] != "active" or q["id"] != s["state"].get("quiz_id"):
            raise DomainError("测验已过期。", 409)
        # Option selection is deterministic; free text uses semantic grading.
        answer = sub["answer"].strip()
        if answer in q["options"]:
            correct = q["options"].index(answer) == q["correct_index"]
            grade = {
                "correct": correct,
                "score": 1.0 if correct else 0.0,
                "feedback": ("回答正确。" if correct else "这次回答不正确。") + q["answer_explanation"],
            }
        else:
            grade = self.provider.complete(
                "grade",
                {
                    "question": q["question"],
                    "options": q["options"],
                    "correct_index": q["correct_index"],
                    "rubric": q["rubric"],
                    "student_answer": answer,
                },
                Grade,
            )
            if grade["correct"] != (grade["score"] >= 0.8):
                raise DomainError("评分结果不一致，请恢复后重试。", 502)
        with self.db.connect() as conn, conn.transaction():
            # Mastery is shared by sessions. Serialize its read/update, including
            # the first insert where there is no row for SELECT FOR UPDATE yet.
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                ("mastery:" + s["space_id"] + ":" + q["concept_id"],),
            )
            old = conn.execute(
                "SELECT * FROM mastery WHERE space_id=%s AND concept_id=%s", (s["space_id"], q["concept_id"])
            ).fetchone()
            updated = update_mastery(old, grade["correct"], answer + " → " + grade["feedback"])
            conn.execute(
                "INSERT INTO attempts(id,submission_id,quiz_id,session_id,space_id,answer,correct,score,feedback) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    uid(),
                    sub["submission_id"],
                    q["id"],
                    s["id"],
                    s["space_id"],
                    answer,
                    grade["correct"],
                    grade["score"],
                    grade["feedback"],
                ),
            )
            conn.execute(
                "INSERT INTO mastery(space_id,concept_id,score,attempts,streak,errors) VALUES (%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT(space_id,concept_id) DO UPDATE SET score=excluded.score,attempts=excluded.attempts,streak=excluded.streak,errors=excluded.errors",
                (
                    s["space_id"],
                    q["concept_id"],
                    updated["score"],
                    updated["attempts"],
                    updated["streak"],
                    Jsonb(updated["errors"]),
                ),
            )
            conn.execute("UPDATE quizzes SET status='answered' WHERE id=%s", (q["id"],))
            state = dict(s["state"], feedback=grade, pending_submission=None)
            conn.execute("UPDATE sessions SET status='running',state=%s WHERE id=%s", (Jsonb(state), s["id"]))
            conn.execute(
                "INSERT INTO memories(id,owner_id,source_space_id,concept_id,kind,content,source_id) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (
                    uid(),
                    self.settings.user_id,
                    s["space_id"],
                    q["concept_id"],
                    "attempt",
                    ("正确: " if grade["correct"] else "错误: ") + answer[:500],
                    q["id"],
                ),
            )
        self.db.event(
            s["space_id"],
            "assess_and_update",
            {
                "quiz_id": q["id"],
                "submission_id": sub["submission_id"],
                "correct": grade["correct"],
                "mastery": updated,
                "memory_validation": {"valid_history": True, "source": q["id"]},
            },
            s["id"],
        )
        return {"done": False}

    def _run(self, s, conn, initial=False, submission=None):
        graph = self.graph(PostgresSaver(conn))
        config = {
            "configurable": {"thread_id": s["thread_id"]},
            "recursion_limit": 8 * self.settings.max_session_steps + 8,
        }
        try:
            pending = submission or s["state"].get("pending_submission")
            if initial:
                value = {"space_id": s["space_id"], "session_id": s["id"], "done": False}
            else:
                snapshot = graph.get_state(config)
                if not snapshot.values:
                    value = {"space_id": s["space_id"], "session_id": s["id"], "done": False}
                elif snapshot.next == ("wait_for_student",):
                    if not pending:
                        return
                    value = Command(resume=pending) if snapshot.interrupts else None
                else:
                    value = None
            graph.invoke(value, config=config, durability="sync")
            # A quiz can commit before its prepare/interrupt checkpoint. First
            # recreate that interrupt, then deliver the durable pending answer.
            latest = self.db.session(s["space_id"], s["id"])
            if pending and latest["state"].get("pending_submission") == pending:
                snapshot = graph.get_state(config)
                if snapshot.interrupts and latest["state"].get("quiz_id") == pending["quiz_id"]:
                    graph.invoke(Command(resume=pending), config=config, durability="sync")
        except Exception as exc:
            latest = self.db.session(s["space_id"], s["id"])
            # Do not include remote response bodies or credentials in persisted errors.
            message = (
                str(exc)[:400]
                if isinstance(exc, DomainError)
                else "模型或学习工具暂时不可用，记录已保存；修复服务后点击继续。"
            )
            self.save_state(latest, error=message)
            self.db.execute("UPDATE sessions SET status='error' WHERE id=%s", (s["id"],))
            self.db.event(s["space_id"], "failure", {"type": type(exc).__name__, "message": message}, s["id"])

    def start(self, space_id, concept_id):
        self.db.concept(space_id, concept_id)
        sid = uid()
        s = self.db.one(
            "INSERT INTO sessions(id,space_id,thread_id,goal_concept_id,current_concept_id,status) "
            "VALUES (%s,%s,%s,%s,%s,'running') RETURNING *",
            (sid, space_id, f"study:{space_id}:{sid}", concept_id, concept_id),
        )
        with self.db.lock(sid) as conn:
            self._run(s, conn, initial=True)
        return self.view(space_id, sid)

    def submit(self, space_id, session_id, submission):
        with self.db.lock(session_id) as conn:
            s = self.db.session(space_id, session_id)
            if s["status"] == "stopped":
                raise DomainError("此会话已结束，不能继续提交。", 409)
            existing = self.db.one(
                "SELECT * FROM attempts WHERE session_id=%s AND submission_id=%s",
                (session_id, submission["submission_id"]),
            )
            if existing:
                if (
                    existing["quiz_id"] != submission["quiz_id"]
                    or existing["answer"] != submission["answer"].strip()
                ):
                    raise DomainError("提交标识已用于不同答案。", 409)
                if s["status"] in ("error", "running"):
                    self._run(s, conn, submission=submission)
                return self.view(space_id, session_id)
            if s["status"] in ("completed", "needs_clarification"):
                raise DomainError("此会话已结束，不能继续提交。", 409)
            q = self.db.one(
                "SELECT * FROM quizzes WHERE id=%s AND session_id=%s AND space_id=%s AND status='active'",
                (submission["quiz_id"], session_id, space_id),
            )
            if not q or q["id"] != s["state"].get("quiz_id"):
                raise DomainError("测验已过期或不属于该会话。", 409)
            submission = dict(submission, answer=submission["answer"].strip())
            self.save_state(s, pending_submission=submission)
            self.db.execute("UPDATE sessions SET status='running' WHERE id=%s", (session_id,))
            self._run(s, conn, submission=submission)
        return self.view(space_id, session_id)

    def resume(self, space_id, session_id):
        with self.db.lock(session_id) as conn:
            s = self.db.session(space_id, session_id)
            if s["status"] in ("stopped", "completed", "needs_clarification"):
                raise DomainError("会话已结束，请建立新的学习会话。", 409)
            if s["status"] != "waiting" or s["state"].get("pending_submission"):
                self._run(s, conn)
        return self.view(space_id, session_id)

    def stop(self, space_id, session_id):
        with self.db.lock(session_id):
            self.db.session(space_id, session_id)
            with self.db.connect() as conn, conn.transaction():
                conn.execute("UPDATE sessions SET status='stopped' WHERE id=%s", (session_id,))
                conn.execute(
                    "UPDATE quizzes SET status='cancelled' WHERE session_id=%s AND status='active'",
                    (session_id,),
                )
            self.db.event(space_id, "stop", {"reason": "用户主动停止；不再执行工具。"}, session_id)
        return self.view(space_id, session_id)

    def view(self, space_id, session_id):
        s = self.db.session(space_id, session_id)
        st = s["state"]
        quiz = self.db.one(
            "SELECT id,question,options,concept_id,evidence_ids FROM quizzes WHERE session_id=%s AND space_id=%s AND status='active' ORDER BY sequence DESC LIMIT 1",
            (session_id, space_id),
        )
        return {
            key: s[key]
            for key in (
                "id",
                "space_id",
                "thread_id",
                "status",
                "goal_concept_id",
                "current_concept_id",
                "step",
            )
        } | {
            "explanation": st.get("explanation", ""),
            "mode": st.get("mode", "explanation"),
            "feedback": st.get("feedback"),
            "quiz": quiz,
            "citations": st.get("citations", []),
            "decision": st.get("decision"),
            "error": st.get("error"),
        }
