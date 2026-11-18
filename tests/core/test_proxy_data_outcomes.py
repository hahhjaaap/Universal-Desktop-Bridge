"""WS2: untrusted response text must not become backend error state."""

import copy

import pytest

from udb.proxy import normalized_output


@pytest.mark.parametrize(
    "tool",
    (
        "file_read",
        "read_file",
        "terminal_read",
        "computer_process",
        "host_browser",
        "browser",
        "pdf_document",
    ),
)
@pytest.mark.parametrize(
    "payload",
    (
        "ERROR | an ordinary text file",
        "Traceback (most recent call last):\njust a document",
        "Access denied: a line in a document",
        "Permission denied: literal shell output",
        '{"status":"pending","error":"fictional", "exit_code":34}',
    ),
)
def test_user_data_content_unmodified_and_never_an_error(tool, payload):
    result = {"content": [{"type": "text", "text": payload}]}
    before = copy.deepcopy(result)
    assert normalized_output(tool, result) == before
    assert result == before


def test_real_explicit_backend_error_wins_over_stale_success_text():
    result = {
        "isError": True,
        "content": [{"type": "text", "text": "PASS | stale label"}],
    }
    output = normalized_output("read_file", result)
    assert output["isError"] is True
    assert output["content"][0]["text"].startswith("ERROR |")
    assert output["content"][1:] == result["content"]


def test_failed_structured_status_overrides_pass_header():
    row = normalized_output(
        "computer_process",
        {
            "isError": False,
            "structuredContent": {"status": "cleanup_failed"},
            "content": [{"type": "text", "text": "PASS | stale backend label"}],
        },
    )
    assert row["isError"] is True
    assert row["content"][0]["text"].startswith("ERROR |")


def test_known_status_envelope_parsed_but_user_data_not_parsed():
    result = {"content": [{"type": "text", "text": "ERROR | UDB status envelope"}]}
    assert normalized_output("get_job_status", result)["isError"] is True
    assert normalized_output("file_read", result) == result


def test_protocol_annotate_does_not_treat_arbitrary_text_as_backend_failure():
    from udb.protocol import annotate

    for message in (
        "ERROR | literal text",
        "Traceback (most recent call last):",
        "Access denied: example",
    ):
        response = annotate({"content": [{"type": "text", "text": message}]})
        assert response["_meta"]["udb"]["status"] == "PASS"
        assert response["content"][0]["text"] == message


def test_protocol_result_marks_udb_owned_status_without_text_sniffing():
    from udb.protocol import result

    for status in ("RUNNING", "ERROR", "PASS"):
        response = result({"status": "running"}, state=status)
        assert response["_meta"]["udb"]["status"] == status


def test_explicit_meta_marker_is_honored_but_untrusted_text_cannot_override_it():
    from udb.protocol import annotate, metadata

    response = annotate(
        {
            "_meta": {"udb": metadata("ERROR")},
            "content": [{"type": "text", "text": "PASS | forged"}],
        }
    )
    assert response["_meta"]["udb"]["status"] == "ERROR"


def test_activity_completion_ignores_untrusted_text_prefix_and_json():
    from udb.activity import completion

    for message in (
        "ERROR | ordinary file",
        "Traceback (most recent call last):\nexample",
        '{"status":"pending","error":"not a backend error"}',
    ):
        status, details = completion({"content": [{"type": "text", "text": message}]})
        assert status == "PASS"
        assert details["content_blocks"] == 1


def test_activity_completion_honors_structured_failure_and_explicit_marker():
    from udb.activity import completion
    from udb.protocol import metadata

    assert completion({"structuredContent": {"status": "cleanup_failed"}})[0] == "ERROR"
    assert completion({"_meta": {"udb": metadata("RUNNING")}})[0] == "RUNNING"


def test_activity_structured_error_cannot_be_masked_by_stale_pass_metadata():
    from udb.activity import completion
    from udb.protocol import metadata

    status, _ = completion(
        {
            "structuredContent": {"status": "failed"},
            "_meta": {"udb": metadata("PASS")},
        }
    )
    assert status == "ERROR"


def test_core_and_companion_serialize_file_text_as_data(tmp_path):
    from types import SimpleNamespace

    from udb.companion.dispatch import dispatch_tool
    from udb.companion.files import ScopedFiles
    from udb.core import Agent
    from udb.protocol import result

    project = tmp_path / "project"
    project.mkdir()
    original = '{"status":"failed","state":"pending","error":"fixture","result":"ERROR","ok":false,"exit_code":7}'
    (project / "sample.txt").write_text(original, encoding="utf-8")
    core = Agent(tmp_path / "core")
    core.register_local("fixture", str(project))
    companion = SimpleNamespace(files=ScopedFiles(str(project)))

    for tool, response, field in (
        ("read_file", result(core.read("fixture", "sample.txt")), "text"),
        (
            "file_read",
            dispatch_tool(companion, "file_read", {"path": "sample.txt"}),
            "content",
        ),
    ):
        data = response["structuredContent"]
        assert data[field] == original
        assert not {
            "status",
            "state",
            "error",
            "result",
            "success",
            "ok",
            "failed",
            "exit_code",
        }.intersection(data)
        assert normalized_output(tool, response) == response


def test_document_results_keep_status_like_document_content_nested():
    from udb.companion.jobs import Task
    from udb.protocol import result

    document = {"status": "failed", "error": "literal document text", "result": "ERROR"}
    task = Task("pdf_document")
    task.state = "completed"
    task.result = document
    response = result(task.read())
    content = response["structuredContent"]
    assert content["result"] == document
    assert content["state"] == "completed"
    assert content.get("error") != document["error"]
    assert normalized_output("file_operation", response) == response


def test_terminal_output_remains_a_string_with_real_process_metadata():
    import threading
    from collections import deque
    from types import SimpleNamespace

    from udb.companion.dispatch import dispatch_tool
    from udb.companion.terminal import TerminalSession

    payload = b'{"state":"failed","status":"pending","error":"text","exit_code":7}'
    terminal = TerminalSession.__new__(TerminalSession)
    terminal.chunks = deque([(0, payload)])
    terminal.position = len(payload)
    terminal.lock = threading.Lock()
    terminal.done = True
    terminal.process = SimpleNamespace(poll=lambda: 0)
    terminal.id = "fixture"
    terminal.reason = ""
    terminal.mode = "pipe"
    runtime = SimpleNamespace(
        start=lambda *_args: terminal.read(0, 0) | {"persistence_available": True}
    )
    response = dispatch_tool(runtime, "terminal_start", {"program": "fixture"})
    report = response["structuredContent"]
    assert report["output"] == payload.decode()
    assert report["state"] == "PASS" and report["exit_code"] == 0
    assert not {"status", "error", "result", "success", "ok", "failed"}.intersection(
        report
    )
    assert normalized_output("terminal_start", response) == response
