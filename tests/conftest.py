"""Fixtures compartilhadas.

O servidor local é o que torna os testes de integração determinísticos: em vez de
auditar um site de terceiro (que muda, cai e depende de rede), servimos páginas com
violações plantadas e sabemos exatamente o que deve ser encontrado.
"""

from __future__ import annotations

import functools
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
PAGES = FIXTURES / "pages"


@pytest.fixture(scope="session")
def page_server():
    """Sobe um servidor HTTP local servindo tests/fixtures/pages."""
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(PAGES))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def axe_sample() -> dict:
    with (FIXTURES / "axe" / "sample_result.json").open(encoding="utf-8") as handle:
        return json.load(handle)
