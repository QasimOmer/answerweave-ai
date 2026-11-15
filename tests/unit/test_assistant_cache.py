"""The assistant cache must not serve a stale copy past its TTL (regression: dashboard
settings appeared not to save on Vercel because reads of other assistants kept
refreshing one shared cache timestamp)."""
from app import db


def test_entry_expires_even_while_other_assistants_are_read(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(db.time, "time", lambda: clock["t"])
    rows = {"a": {"id": "a", "v": 1}, "b": {"id": "b", "v": 1}}

    class Cur:
        def execute(self, sql, params): self.row = rows.get(params[0])
        def fetchone(self): return self.row
    class Conn:
        def cursor(self): return Cur()
        def close(self): pass
    monkeypatch.setattr(db, "get_db", lambda: Conn())
    db._ASSISTANTS_CACHE.clear(); db._ASSISTANTS_CACHE_AT.clear()

    assert db.get_assistant("a")["v"] == 1
    rows["a"] = {"id": "a", "v": 2}          # changed by another server instance
    for step in range(10):                    # steady traffic on a different assistant
        clock["t"] += 5
        db.get_assistant("b")
    assert db.get_assistant("a")["v"] == 2, "stale cache entry outlived its TTL"


def test_fresh_read_bypasses_cache(monkeypatch):
    rows = {"a": {"id": "a", "v": 1}}
    class Cur:
        def execute(self, sql, params): self.row = rows.get(params[0])
        def fetchone(self): return self.row
    class Conn:
        def cursor(self): return Cur()
        def close(self): pass
    monkeypatch.setattr(db, "get_db", lambda: Conn())
    db._ASSISTANTS_CACHE.clear(); db._ASSISTANTS_CACHE_AT.clear()
    db.get_assistant("a")
    rows["a"] = {"id": "a", "v": 2}
    assert db.get_assistant("a")["v"] == 1
    assert db.get_assistant("a", fresh=True)["v"] == 2
