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
