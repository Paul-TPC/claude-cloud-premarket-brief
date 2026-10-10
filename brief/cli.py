"""命令列：check、collect、send、articles。"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path


def _parse_date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"日期要是 YYYY-MM-DD：{text}")


class _Parser(argparse.ArgumentParser):
    """參數錯誤時結束碼用 1，不用 argparse 預設的 2（2 在 collect 代表「部分來源失敗」）。"""

    def error(self, message: str):
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: 錯誤：{message}\n")


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="python -m brief", description="台股盤前資訊整理")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="測試每個資料來源和 api.telegram.org 連不連得到")

    c = sub.add_parser("collect", help="抓資料，輸出 data/<報告日>.json")
    c.add_argument("--date", type=_parse_date, default=None, help="報告日 YYYY-MM-DD，預設今天（Asia/Taipei）")
    c.add_argument("--out", type=Path, default=Path("data"), help="輸出目錄，預設 data/")

    s = sub.add_parser("send", help="把報告送到 Telegram")
    s.add_argument("file", type=Path, help="報告檔（簡化的 Markdown）")
    s.add_argument("--dry-run", action="store_true", help="只印出轉換後的內容和拆成幾則，不送出")

    a = sub.add_parser("articles", help="抓新聞內文，輸出 JSON 到標準輸出（內文不寫進 repo）")
    a.add_argument("urls", nargs="+", metavar="網址", help="經濟日報、Yahoo股市、鉅亨網的新聞網址")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _dispatch(args)
    except Exception as e:  # 最後一道防線：例外訊息也要遮蔽，不印 traceback
        from .net import log

        log(f"{args.command} 失敗：{type(e).__name__}: {e}")
        return 1


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "check":
        from .check import run

        return run()
    if args.command == "collect":
        from .collect import run

        return run(report_date=args.date, out_dir=args.out)
    if args.command == "send":
        from .telegram import run

        return run(args.file, dry_run=args.dry_run)
    if args.command == "articles":
        from .articles import run

        return run(args.urls)
    return 1
