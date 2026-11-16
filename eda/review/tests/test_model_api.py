import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

import pytest

from test_review import R, _confirm_all, _es_answer, _fixture, _q


@pytest.fixture
def endpoint():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append((self.path, self.headers.get("Authorization"), body))
            content = body["messages"][1]["content"]
            prompt = content if isinstance(content, str) else content[0]["text"]
            payload = json.loads(prompt.split("\nREQUEST\n", 1)[1])
            if "feedback" in payload:
                answer = {"rows": [{"row_id": row["row_id"], "status_code": "NOT_ANSWERABLE_YET",
                                    "observed": row["observed"], "basis": row["basis"], "reach": row["reach"],
                                    "missing": ["Component or assay measurements."]} for row in payload["rows"]]}
            elif "required_rules" in payload:
                answer = _confirm_all({"payload": payload})
            else:
                answer = _es_answer(payload["species"], {})
            if body["model"] == "incomplete":
                del answer["omissions"]
            reply = {"choices": [{"message": {"content": json.dumps(answer)}}]}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(reply).encode())

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/v1", calls
        finally:
            server.shutdown()
            thread.join()


def test_cli_custom_api_paths_images_and_resume(tmp_path, endpoint, monkeypatch):
    base, calls = endpoint
    source = tmp_path / "case #1"
    source.mkdir()
    _fixture(source)
    (source / "report.html").write_text("Study report", encoding="utf-8")
    out = tmp_path / "chosen destination" / "review A"
    monkeypatch.setenv("EDA_REVIEW_API_KEY", "test-only")
    args = [str(source), "--out", str(out), "--only", "elimination-s01-dog", "--resume"]
    api = ["--api-base", base, "--model", "my-vision-model"]
    R.main(args + api)
    rec = json.loads((out / "review.json").read_bytes())
    assert rec["self_review"] == "PASSED" and rec["model_provider"]["model"] == "my-vision-model"
    path, auth, body = calls[0]
    assert (path, auth, body["model"]) == ("/v1/chat/completions", "Bearer test-only", "my-vision-model")
    assert json.loads(body["messages"][0]["content"].split("\n", 1)[1]) == R.ERR_SCHEMA
    parts = body["messages"][1]["content"]
    encoded = [v["image_url"]["url"] for v in parts if v["type"] == "image_url"]
    assert len(encoded) == 2
    assert all(v.startswith("data:image/png;base64,") and base64.b64decode(v.split(",")[1]) == b"png" for v in encoded)
    assert "test-only" not in (out / "review.json").read_text(encoding="utf-8")
    html = (out / "index.html").read_text(encoding="utf-8")
    href = html.split('<nav><a href="', 1)[1].split('"', 1)[0]
    assert "%23" in href and (out / unquote(href)).resolve() == source / "report.html"
    R.main(args + api)
    R.main(args)  # offline replay of this endpoint's answers
    assert len(calls) == 1
    R.main(args + ["--api-base", base, "--model", "second-model"])
    R.main(args + ["--api-base", base + "/other", "--model", "second-model"])
    assert len(calls) == 3


def test_api_schema_failure_and_no_key(tmp_path, endpoint, monkeypatch):
    base, calls = endpoint
    monkeypatch.delenv("EDA_REVIEW_API_KEY", raising=False)
    _fixture(tmp_path)
    with pytest.raises(SystemExit) as stopped:
        R.main([str(tmp_path), "--only", "elimination-s01-rat", "--api-base", base, "--model", "incomplete"])
    assert stopped.value.code == 2 and calls[0][1] is None
    rec = json.loads((tmp_path / "review/review.json").read_bytes())
    assert rec["self_review"] == "PENDING" and "schema" in rec["err"][0]["problems"][0]
    assert isinstance(calls[0][2]["messages"][1]["content"], str)


def test_review_output_cannot_overwrite_input_report(tmp_path):
    _fixture(tmp_path)
    page = tmp_path / "index.html"
    page.write_bytes(b"original")
    with pytest.raises(ValueError, match="separate review output"):
        R.run(tmp_path, out_dir=tmp_path)
    assert page.read_bytes() == b"original"


def test_api_writer_recheck_and_summary_use_selected_model(tmp_path, endpoint):
    base, calls = endpoint
    _fixture(tmp_path)
    board = {"study": "S01", "species": "Rat", "key": "s01-rat", "components": [], "in_vitro": [],
             "questions": [_q(7, "ANSWERABLE", "No component or assay measurements.")]}
    (tmp_path / "elimination/elimination.json").write_text(json.dumps({"boards": [board]}), encoding="utf-8")
    for model in ("first", "second"):
        calls.clear()
        R.main([str(tmp_path), "--api-base", base, "--model", model, "--resume"])
        record = json.loads((tmp_path / "review/review.json").read_bytes())
        assert record["self_review"] == "PASSED" and record["es"]["status"] == "ACCEPTED"
        board_review = next(e["self_review"] for e in record["err"] if "s01-rat" in e["id"])
        assert next(iter(board_review["updated_rows"].values()))["status_code"] == "NOT_ANSWERABLE_YET"
        assert {req["model"] for _, _, req in calls} == {model}
        prompts = [req["messages"][1]["content"] for _, _, req in calls]
        assert any(isinstance(p, str) and p.startswith("Revise the flagged") for p in prompts)
        assert any(isinstance(p, str) and '"previous_findings":' in p for p in prompts)
