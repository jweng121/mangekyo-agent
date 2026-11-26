"""Read parses reuse only fresh, matching, workspace-scoped sources."""

from __future__ import annotations

from mangekyo.tool_cache import ParsedReadCache


def test_parsed_read_cache_reuses_and_recomputes(tmp_path, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr("mangekyo.tool_cache.time.time", lambda: clock[0])
    first_scope = tmp_path / "workspace-one"
    second_scope = tmp_path / "workspace-two"
    first_scope.mkdir()
    second_scope.mkdir()
    data = b'{"account":"SAFE-ACCOUNT"}'

    def parse(cache, workspace, source=data, version="v1", context=None):
        return cache.parse(workspace=workspace, relative_path="invoice.json",
                           source=source, parser="json", tool_version=version,
                           context=context or {"supplier": "supplier-7"}, ttl_seconds=10)

    with ParsedReadCache(tmp_path / "cache") as cache:
        assert parse(cache, first_scope) == ({"account": "SAFE-ACCOUNT"}, "miss")
        assert parse(cache, first_scope) == ({"account": "SAFE-ACCOUNT"}, "hit")
        assert parse(cache, second_scope)[1] == "miss"
        assert parse(cache, first_scope, version="v2")[1] == "miss"
        assert parse(cache, first_scope, context={"supplier": "supplier-8"})[1] == "miss"
        changed = b'{"account":"NEW-ACCOUNT"}'
        assert parse(cache, first_scope, changed) == ({"account": "NEW-ACCOUNT"}, "source_changed")
        clock[0] = 1011.0
        assert parse(cache, first_scope, changed)[1] == "expired"
        assert parse(cache, first_scope, changed)[1] == "hit"


def test_cache_rejects_non_read_parsers_and_escape_paths(tmp_path):
    with ParsedReadCache(tmp_path / "cache") as cache:
        common = {"workspace": tmp_path, "source": b"{}", "tool_version": "v1"}
        try:
            cache.parse(relative_path="invoice.json", parser="write_payment", **common)
        except ValueError as exc:
            assert "cache eligible" in str(exc)
        else:
            raise AssertionError("Side-effecting parser was accepted")
        try:
            cache.parse(relative_path="../invoice.json", parser="json", **common)
        except ValueError as exc:
            assert "workspace relative" in str(exc)
        else:
            raise AssertionError("Escaping path was accepted")


def test_cache_refuses_to_persist_when_redaction_is_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGEKYO_REDACT", "SAFE-ACCOUNT")
    try:
        ParsedReadCache(tmp_path / "cache")
    except ValueError as exc:
        assert "MANGEKYO_REDACT" in str(exc)
    else:
        raise AssertionError("Cache accepted unredacted source with redaction configured")
    assert not (tmp_path / "cache").exists()
