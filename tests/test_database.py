def test_schema_and_scope_contract():
    from studyagent.db import Database
    from studyagent.config import Settings

    db = Database(Settings(user_id="database-contract-test"))
    db.migrate()
    db.migrate()
    assert db.one("SELECT extversion FROM pg_extension WHERE extname=%s", ("vector",))
    s = db.create_space("Test course", "course", "machine learning")
    assert db.space(s["id"])["name"] == "Test course"
    assert db.one("SELECT count(*) AS n FROM quizzes")["n"] >= 0
