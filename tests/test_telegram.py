import json
import logging
import socket

import pytest
import requests

from brief import net, telegram
from brief.net import Fetcher
from conftest import fake_session

# 故意不像真的 Telegram token（數字:一長串英數），免得被 GitGuardian 這類掃描工具當成外洩的金鑰。
FAKE_TOKEN = "fake-bot-token-for-tests-only"
FAKE_CHAT = "fake-chat-id-for-tests"


# ---------- Markdown → Telegram HTML ----------


def test_bold_and_link():
    md = "**📊 台股盤前整理｜2026-10-08**\n[外資賣超](https://example.com/a?x=1&y=2)（經濟日報）"
    assert telegram.md_to_html(md) == (
        "<b>📊 台股盤前整理｜2026-10-08</b>\n"
        '<a href="https://example.com/a?x=1&amp;y=2">外資賣超</a>（經濟日報）'
    )


def test_escapes_plain_text():
    assert telegram.md_to_html("A&B <tag> 1>0") == "A&amp;B &lt;tag&gt; 1&gt;0"


def test_escapes_inside_bold_and_link_text():
    assert telegram.md_to_html("**<b>&**") == "<b>&lt;b&gt;&amp;</b>"
    assert telegram.md_to_html("[a<b](https://e.com/\"q)") == '<a href="https://e.com/&quot;q">a&lt;b</a>'


def test_link_inside_bold():
    assert telegram.md_to_html("**看 [這裡](https://e.com)**") == '<b>看 <a href="https://e.com">這裡</a></b>'


def test_non_http_link_is_plain_text():
    assert telegram.md_to_html("[點我](javascript:alert(1))") == "[點我](javascript:alert(1))"


def test_unmatched_markers_stay_as_text():
    assert telegram.md_to_html("**沒有結尾 和 [沒有網址]") == "**沒有結尾 和 [沒有網址]"


# ---------- 拆分 ----------


def test_short_message_is_one():
    assert telegram.to_messages("**標題**\n內容\n\n第二段") == ["<b>標題</b>\n內容\n\n第二段"]


def test_split_by_paragraph():
    paragraphs = [f"第{i}段 " + "字" * 1000 for i in range(10)]
    msgs = telegram.to_messages("\n\n".join(paragraphs))
    assert len(msgs) > 1
    assert all(telegram.tg_len(m) <= telegram.LIMIT for m in msgs)
    # 段落沒有被切斷，順序不變
    assert "\n\n".join(msgs).split("\n\n") == paragraphs


def test_long_paragraph_split_by_line():
    lines = [f"第{i}行 " + "字" * 500 for i in range(20)]
    msgs = telegram.to_messages("\n".join(lines))
    assert len(msgs) > 1
    assert all(telegram.tg_len(m) <= telegram.LIMIT for m in msgs)
    assert "\n".join(msgs).split("\n") == lines


def test_single_huge_line_hard_split():
    line = "a&b" * 3000  # 跳脫後每個 & 變 5 個字
    msgs = telegram.to_messages(line)
    assert all(telegram.tg_len(m) <= telegram.LIMIT for m in msgs)
    assert "".join(msgs) == telegram.md_to_html(line)


def test_emoji_counts_as_two():
    assert telegram.tg_len("📊") == 2
    msgs = telegram.to_messages("📊" * 2100)
    assert len(msgs) == 2 and all(telegram.tg_len(m) <= telegram.LIMIT for m in msgs)


# ---------- send 指令 ----------


def test_dry_run_needs_no_env(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    f = tmp_path / "r.md"
    f.write_text("**粗體** & <x>", encoding="utf-8")
    assert telegram.run(f, dry_run=True) == 0
    out = capsys.readouterr().out
    assert "<b>粗體</b> &amp; &lt;x&gt;" in out
    assert "共 1 則" in out


@pytest.mark.parametrize("missing", ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"])
def test_missing_env(tmp_path, monkeypatch, capsys, missing):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", FAKE_TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", FAKE_CHAT)
    monkeypatch.delenv(missing)
    f = tmp_path / "r.md"
    f.write_text("hi", encoding="utf-8")
    assert telegram.run(f) == 1
    out, err = capsys.readouterr()
    assert "缺少 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID" in err
    assert FAKE_TOKEN not in out + err and FAKE_CHAT not in out + err


def _env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", FAKE_TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", FAKE_CHAT)


def _report(tmp_path):
    f = tmp_path / "r.md"
    f.write_text("**測試**", encoding="utf-8")
    return f


def test_send_success(tmp_path, monkeypatch, capsys):
    _env(monkeypatch)
    session, adapter = fake_session(lambda req: (200, b'{"ok":true,"result":{"message_id":1}}'))
    assert telegram.run(_report(tmp_path), fetcher=Fetcher(session, sleep=lambda s: None)) == 0
    req = adapter.requests[0]
    assert req.method == "POST" and req.url.endswith("/sendMessage")
    body = json.loads(req.body)
    assert body["parse_mode"] == "HTML"
    assert body["link_preview_options"] == {"is_disabled": True}
    assert body["text"] == "<b>測試</b>"
    out, err = capsys.readouterr()
    assert "已送出 1 則" in out
    assert FAKE_TOKEN not in out + err and FAKE_CHAT not in out + err


# ---------- token 不能出現在任何輸出或錯誤訊息 ----------


def _assert_no_secret(*texts):
    for t in texts:
        assert FAKE_TOKEN not in t
        assert "fake-bot-token" not in t
        assert FAKE_CHAT not in t


def test_token_not_leaked_on_connection_error(tmp_path, monkeypatch, capsys, caplog):
    """requests 的例外訊息會帶完整網址（含 token），要遮掉。"""
    _env(monkeypatch)
    caplog.set_level(logging.DEBUG)

    def boom(req):
        return requests.ConnectionError(f"HTTPSConnectionPool: Max retries exceeded with url: {req.url} chat={FAKE_CHAT}")

    session, adapter = fake_session(boom)
    assert telegram.run(_report(tmp_path), fetcher=Fetcher(session, sleep=lambda s: None)) == 1
    assert len(adapter.requests) == 2  # 重試 1 次
    assert FAKE_TOKEN in adapter.requests[0].url  # 確認真的有把 token 放進網址
    out, err = capsys.readouterr()
    assert "送出失敗" in err
    _assert_no_secret(out, err, caplog.text)


def test_token_not_leaked_in_exception_message(monkeypatch):
    session, _ = fake_session(lambda req: requests.ConnectionError(f"failed: {req.url}"))
    with pytest.raises(telegram.SendError) as exc:
        telegram.send_messages(["hi"], FAKE_TOKEN, FAKE_CHAT, Fetcher(session, sleep=lambda s: None))
    _assert_no_secret(str(exc.value), repr(exc.value))


def test_token_not_leaked_on_http_error(tmp_path, monkeypatch, capsys, caplog):
    _env(monkeypatch)
    caplog.set_level(logging.DEBUG)
    session, _ = fake_session(lambda req: (401, b'{"ok":false,"error_code":401,"description":"Unauthorized"}'))
    assert telegram.run(_report(tmp_path), fetcher=Fetcher(session, sleep=lambda s: None)) == 1
    out, err = capsys.readouterr()
    assert "HTTP 401" in err and "Unauthorized" in err
    _assert_no_secret(out, err, caplog.text)


def test_token_not_leaked_with_real_requests_stack(tmp_path, monkeypatch, capsys, caplog):
    """用真的 requests / urllib3 連一個本機沒人聽的埠（不出網路），看例外訊息和 DEBUG log。"""
    _env(monkeypatch)
    caplog.set_level(logging.DEBUG)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setattr(telegram, "API", f"http://127.0.0.1:{port}")
    session = requests.Session()
    session.trust_env = False  # 不走 proxy
    assert telegram.run(_report(tmp_path), fetcher=Fetcher(session, sleep=lambda s: None, timeout=2)) == 1
    out, err = capsys.readouterr()
    assert "ConnectionError" in err
    _assert_no_secret(out, err, caplog.text)


def test_redact_patterns():
    net.register_secret(FAKE_TOKEN)
    assert net.redact(f"/bot{FAKE_TOKEN}/sendMessage") == "/bot***/sendMessage"
    assert FAKE_TOKEN not in net.redact(f"/bot{FAKE_TOKEN.replace(':', '%3A')}/x")
    # 沒登記過、但長得像 token 的也遮
    assert net.redact("/bot111111111:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB/x") == "/bot***/x"


def test_no_whitespace_only_message():
    msgs = telegram.to_messages("x" * 4096 + " \n" + "y" * 4095)
    assert msgs and all(m.strip() for m in msgs)


def test_cli_usage_error_exits_1(capsys):
    from brief.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["collect", "--date", "2026/10/08"])
    assert exc.value.code == 1
