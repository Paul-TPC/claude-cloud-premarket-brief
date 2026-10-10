"""測試共用：讀 fixture、假的 HTTP session（測試不打網路）。"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Callable

import requests

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_bytes(name: str) -> bytes:
    path = FIXTURES / name
    if path.exists():
        return path.read_bytes()
    return gzip.decompress((FIXTURES / (name + ".gz")).read_bytes())


def fixture_json(name: str):
    return json.loads(fixture_bytes(name))


class FakeAdapter(requests.adapters.BaseAdapter):
    """依網址回傳事先準備好的回應，或丟出例外。"""

    def __init__(self, handler: Callable[[requests.PreparedRequest], tuple[int, bytes] | Exception]) -> None:
        super().__init__()
        self.handler = handler
        self.requests: list[requests.PreparedRequest] = []

    def send(self, request, **kwargs):
        self.requests.append(request)
        result = self.handler(request)
        if isinstance(result, Exception):
            raise result
        status, body = result
        resp = requests.Response()
        resp.status_code = status
        resp._content = body
        resp.url = request.url
        resp.request = request
        resp.headers["Content-Type"] = "application/json"
        return resp

    def close(self):
        pass


def fake_session(handler) -> tuple[requests.Session, FakeAdapter]:
    s = requests.Session()
    s.trust_env = False
    adapter = FakeAdapter(handler)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s, adapter
