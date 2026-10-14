import json

from econviz import fetch


class FakeResponse:
    status_code = 200
    content = b"hello"

    def raise_for_status(self):
        pass


def test_get_is_idempotent_and_writes_sidecar(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "RAW", tmp_path)
    calls = []
    monkeypatch.setattr(fetch.requests, "get", lambda *a, **k: calls.append(1) or FakeResponse())
    p = fetch.get("src", "http://x/y", "f.txt")
    fetch.get("src", "http://x/y", "f.txt")
    assert calls == [1] and p.read_bytes() == b"hello"
    side = json.loads((tmp_path / "src" / "f.txt.json").read_text())
    assert side["sha256"] == fetch.sha256(p) and side["url"] == "http://x/y" and side["bytes"] == 5
    assert fetch.retrieved_on("src") == side["retrieved_on"]


def test_get_refetches_corrupted_file(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "RAW", tmp_path)
    monkeypatch.setattr(fetch.requests, "get", lambda *a, **k: FakeResponse())
    p = fetch.get("src", "http://x/y", "f.txt")
    p.write_bytes(b"tampered")
    fetch.get("src", "http://x/y", "f.txt")
    assert p.read_bytes() == b"hello"


def test_retrieved_on_ignores_json_data_files(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "RAW", tmp_path)
    monkeypatch.setattr(fetch.requests, "get", lambda *a, **k: FakeResponse())
    fetch.get("src", "http://x/y", "data.json")  # a .json data file next to its own .json.json sidecar
    assert fetch.retrieved_on("src") == json.loads((tmp_path / "src" / "data.json.json").read_text())["retrieved_on"]


def test_get_retries_a_dropped_connection(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "RAW", tmp_path)
    monkeypatch.setattr(fetch.time, "sleep", lambda s: None)
    calls = []

    def flaky(*a, **k):
        calls.append(1)
        if len(calls) < 3:
            raise fetch.requests.exceptions.ChunkedEncodingError("Response ended prematurely")
        return FakeResponse()
    monkeypatch.setattr(fetch.requests, "get", flaky)
    assert fetch.get("src", "http://x/y", "f.txt").read_bytes() == b"hello" and len(calls) == 3


def test_get_refetches_when_url_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "RAW", tmp_path)
    calls = []
    monkeypatch.setattr(fetch.requests, "get", lambda *a, **k: calls.append(a[0]) or FakeResponse())
    fetch.get("src", "http://x/y?to=2022", "f.txt")
    fetch.get("src", "http://x/y?to=2024", "f.txt")
    assert calls == ["http://x/y?to=2022", "http://x/y?to=2024"]


def test_pinned_wikipedia_url_asks_for_its_revision(tmp_path, monkeypatch):
    assert all(u.startswith(("https://en.", "https://ru.", "https://zh.")) and r.isdigit() for u, r in fetch.pins().items())  # the real file
    monkeypatch.setattr(fetch, "RAW", tmp_path)
    monkeypatch.setattr(fetch, "pins", lambda: {"http://w/api.php?action=parse&page=X&prop=text": "42"})
    calls = []
    monkeypatch.setattr(fetch.requests, "get", lambda *a, **k: calls.append(a[0]) or FakeResponse())
    fetch.get("src", "http://w/api.php?action=parse&page=X&prop=text", "x.json")
    fetch.get("src", "http://w/api.php?action=parse&page=Y", "y.json")
    assert calls == ["http://w/api.php?action=parse&oldid=42&prop=text", "http://w/api.php?action=parse&page=Y"]
