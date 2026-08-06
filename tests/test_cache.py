from bg_company_lookup.cache import TTLCache


def test_get_returns_none_for_missing_key():
    cache = TTLCache(ttl_seconds=60)
    assert cache.get("missing") is None


def test_set_then_get_returns_stored_value():
    cache = TTLCache(ttl_seconds=60)
    cache.set("q", {"answer": 42})
    assert cache.get("q") == {"answer": 42}


def test_get_returns_none_after_ttl_expires(monkeypatch):
    fake_time = [1000.0]
    monkeypatch.setattr("bg_company_lookup.cache.time.monotonic", lambda: fake_time[0])

    cache = TTLCache(ttl_seconds=10)
    cache.set("q", "value")

    fake_time[0] += 5
    assert cache.get("q") == "value"

    fake_time[0] += 6
    assert cache.get("q") is None


def test_set_overwrites_existing_entry():
    cache = TTLCache(ttl_seconds=60)
    cache.set("q", "first")
    cache.set("q", "second")
    assert cache.get("q") == "second"
