"""Regression guard: ChatGPT's persistent footer is not assistant output."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "src" / "udb" / "computer_uia.ps1"


def reply_candidate_function():
    source = SCRIPT.read_text(encoding="utf-8-sig")
    start = source.index("function Test-ChatGPTReplyCandidate(")
    end = source.index("\ntry {", start)
    definition = source[start:end]
    assert "(Test-ChatGPTReplyCandidate $value)" in source
    return definition


def test_helper_anchored_to_observer():
    helper = reply_candidate_function()
    assert "ChatGPT có thể mắc lỗi" in helper
    assert "ChatGPT can make mistakes" in helper
    assert "IsNullOrWhiteSpace" in helper


@pytest.mark.skipif(sys.platform != "win32", reason="Needs Windows PowerShell 5.1")
def test_powershell_footer_rejection_and_real_text(tmp_path):
    executable = shutil.which("powershell.exe")
    if executable is None:
        pytest.skip("PowerShell unavailable")
    body = reply_candidate_function()
    script = (
        body
        + """
$bad=@(
    'ChatGPT có thể mắc lỗi. Hãy kiểm tra thông tin quan trọng.',
    'ChatGPT can make mistakes. Check important info.',
    'Hỏi ChatGPT', 'Copy', 'Chính sách quyền riêng tư', ''
)
$good=@('Hello! 👋 Bạn muốn mình hỗ trợ gì?', 'This is my answer.')
foreach($s in $bad) {
    if(Test-ChatGPTReplyCandidate $s) {
        throw 'False positive: UI footer/label interpreted as an assistant answer'
    }
}
foreach($s in $good) {
    if(-not (Test-ChatGPTReplyCandidate $s)) {
        throw 'False negative: actual assistant response was suppressed'
    }
}
"""
    )
    file = tmp_path / "test_chatgpt_reply_filter.ps1"
    file.write_text(script, encoding="utf-8-sig")
    result = subprocess.run(
        [
            executable,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(file),
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
