"""python -m brief send：簡化 Markdown → Telegram HTML，拆分後送出。"""

from __future__ import annotations

import html
import os
import re
import sys
from pathlib import Path

from .net import Fetcher, log, redact, register_secret

API = "https://api.telegram.org"
LIMIT = 4096
MISSING_ENV = "缺少 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID"

# 只支援 **粗體** 和 [文字](網址)。粗體不跨行。
_INLINE_RE = re.compile(r"\*\*(?P<bold>.+?)\*\*|\[(?P<text>[^\]\n]+)\]\((?P<url>[^)\s]+)\)")
_LINK_RE = re.compile(r"\[(?P<text>[^\]\n]+)\]\((?P<url>[^)\s]+)\)")


class SendError(Exception):
    pass


def _esc(text: str) -> str:
    return html.escape(text, quote=False)


def _link(text: str, url: str, raw: str) -> str:
    if not re.match(r"https?://", url):
        return _esc(raw)  # 不是 http(s) 網址就當一般文字
    return f'<a href="{html.escape(url, quote=True)}">{_esc(text)}</a>'


def _links_only(text: str) -> str:
    out, pos = [], 0
    for m in _LINK_RE.finditer(text):
        out.append(_esc(text[pos:m.start()]))
        out.append(_link(m["text"], m["url"], m[0]))
        pos = m.end()
    out.append(_esc(text[pos:]))
    return "".join(out)


def md_to_html(text: str) -> str:
    """`**粗體**` → `<b>`，`[文字](網址)` → `<a>`，其餘的 &、<、> 跳脫。"""
    out, pos = [], 0
    for m in _INLINE_RE.finditer(text):
        out.append(_esc(text[pos:m.start()]))
        if m["bold"] is not None:
            out.append(f"<b>{_links_only(m['bold'])}</b>")
        else:
            out.append(_link(m["text"], m["url"], m[0]))
        pos = m.end()
    out.append(_esc(text[pos:]))
    return "".join(out)


def tg_len(text: str) -> int:
    """Telegram 用 UTF-16 計長度（emoji 算 2）。這裡連 HTML 標籤一起算，比實際限制保守。"""
    return len(text.encode("utf-16-le")) // 2


def _hard_split(line: str, limit: int) -> list[str]:
    """一行就超過上限：放棄格式，當純文字一個字一個字切。"""
    pieces, cur = [], ""
    for ch in line:
        if tg_len(_esc(cur + ch)) > limit:
            pieces.append(_esc(cur))
            cur = ""
        cur += ch
    if cur:
        pieces.append(_esc(cur))
    return pieces


def _pack(blocks: list[str], sep: str, limit: int) -> list[str]:
    out: list[str] = []
    for b in blocks:
        if out and tg_len(out[-1] + sep + b) <= limit:
            out[-1] += sep + b
        else:
            out.append(b)
    return out


def _split_paragraph(paragraph: str, limit: int) -> list[str]:
    lines: list[str] = []
    for line in paragraph.split("\n"):
        h = md_to_html(line)
        lines.extend([h] if tg_len(h) <= limit else _hard_split(line, limit))
    return _pack(lines, "\n", limit)


def to_messages(markdown: str, limit: int = LIMIT) -> list[str]:
    """轉成 HTML，超過上限時以段落（空行分隔）為單位拆成多則。"""
    paragraphs = [p.strip("\n") for p in re.split(r"\n[ \t]*\n", markdown.strip()) if p.strip()]
    blocks: list[str] = []
    for p in paragraphs:
        h = md_to_html(p)
        blocks.extend([h] if tg_len(h) <= limit else _split_paragraph(p, limit))
    # 硬切可能切出只有空白的片段，Telegram 不收空訊息
    return [m for m in _pack(blocks, "\n\n", limit) if m.strip()]


def send_messages(messages: list[str], token: str, chat_id: str, fetcher: Fetcher) -> None:
    register_secret(token)
    register_secret(chat_id)
    url = f"{API}/bot{token}/sendMessage"
    shown = f"{API}/bot***/sendMessage"
    for i, text in enumerate(messages, 1):
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        }
        r = fetcher.post(url, json=payload, display_url=shown)
        body = None
        if r.response is not None:
            try:
                body = r.response.json()
            except ValueError:
                body = None
        if r.ok and isinstance(body, dict) and body.get("ok"):
            continue
        detail = body.get("description") if isinstance(body, dict) else None
        reason = "；".join(x for x in (r.error, detail) if x) or "回應不是 ok"
        raise SendError(redact(f"第 {i}/{len(messages)} 則送出失敗：{reason}"))


def run(path: Path, *, dry_run: bool = False, fetcher: Fetcher | None = None) -> int:
    try:
        messages = to_messages(Path(path).read_text(encoding="utf-8"))
        if not messages:
            log(f"{path} 是空的，沒有東西可以送")
            return 1
        if dry_run:
            for i, m in enumerate(messages, 1):
                print(f"----- 第 {i}/{len(messages)} 則（{tg_len(m)} 字）-----")
                print(m)
            print(f"共 {len(messages)} 則")
            return 0
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        register_secret(token)
        register_secret(chat_id)
        if not token or not chat_id:
            print(MISSING_ENV, file=sys.stderr)
            return 1
        send_messages(messages, token, chat_id, fetcher or Fetcher())
        print(f"已送出 {len(messages)} 則")
        return 0
    except Exception as e:
        log(f"send 失敗：{type(e).__name__}: {e}")
        return 1
