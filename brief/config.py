"""讀 config.toml。"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config.toml"


@dataclass(frozen=True)
class WatchItem:
    code: str
    name: str


def load_watchlist(path: Path = DEFAULT_PATH) -> list[WatchItem]:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return [WatchItem(code=str(x["code"]), name=str(x["name"])) for x in data.get("watchlist", [])]
