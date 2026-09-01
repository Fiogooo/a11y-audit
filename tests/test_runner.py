"""Teste de integração do runner.

Roda o fluxo completo (navegador, injeção do axe-core, normalização) contra páginas
servidas localmente, com violações plantadas. Determinístico: não depende de internet,
nem de site de terceiro que muda sem aviso.

Exige o navegador do Playwright instalado::

    python -m playwright install chromium

Sem ele, os testes são pulados em vez de falhar.
"""

from __future__ import annotations

import asyncio

import pytest

from a11y_audit.config import parse_config
from a11y_audit.runner import run_audit

pytestmark = pytest.mark.browser


def _has_browser() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:  # pragma: no cover
        return False
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            browser.close()
    except Exception:  # pragma: no cover - navegador não instalado
        return False
    return True


requires_browser = pytest.mark.skipif(
    not _has_browser(), reason="navegador do Playwright não instalado"
)


def audit(page_server: str, pages: list[str], **overrides):
    config = parse_config(
        {
            "concurrency": 2,
            "delay_ms": 0,
            "respect_robots": False,  # servidor local não tem robots.txt
            "sites": [{"name": "fixtures", "urls": [f"{page_server}/{p}" for p in pages]}],
            **overrides,
        }
    )
    return asyncio.run(run_audit(config))


@requires_browser
def test_detects_planted_violations(page_server):
    results = audit(page_server, ["sem_alt.html", "sem_label.html", "contraste_baixo.html"])
    found = {
        r.url.rsplit("/", 1)[-1]: {v.rule_id for v in r.result.violations}
        for r in results
        if r.result
    }

    assert "image-alt" in found["sem_alt.html"]
    assert "label" in found["sem_label.html"]
    assert "color-contrast" in found["contraste_baixo.html"]


@requires_browser
def test_clean_page_has_no_violations(page_server):
    (result,) = audit(page_server, ["ok.html"])
    assert result.ok
    assert result.result is not None
    assert result.result.violations == []


@requires_browser
def test_standard_is_expanded_to_cumulative_tags(page_server):
    """Regressão: filtrar pela tag exata 'wcag21aa' não roda as regras da WCAG 2.0.

    `image-alt` é marcada pelo axe como `wcag2a`, então pedir só `wcag21aa` a deixava
    passar e a ferramenta reportava zero violações numa página claramente inacessível.
    """
    (result,) = audit(page_server, ["sem_alt.html"], standard="wcag21aa")
    assert {v.rule_id for v in result.result.violations} == {"image-alt"}


@requires_browser
def test_error_page_is_recorded_but_not_audited(page_server):
    """Um 404 devolve HTML válido (a página de erro do servidor).

    Auditá-la contaria as violações da página de erro como se fossem do site.
    """
    results = audit(page_server, ["ok.html", "nao-existe-404.html"])
    falha = next(r for r in results if r.url.endswith("nao-existe-404.html"))

    assert falha.http_status == 404
    assert falha.error is not None and "404" in falha.error
    assert falha.result is None
    # a execução seguiu e a página boa foi auditada normalmente
    assert next(r for r in results if r.url.endswith("ok.html")).ok


@requires_browser
def test_unreachable_host_does_not_break_the_run(page_server):
    config_urls = ["ok.html"]
    results = audit(page_server, config_urls)
    assert results[0].ok

    # porta fechada: erro de conexão, não de HTTP
    from a11y_audit.config import parse_config
    from a11y_audit.runner import run_audit

    config = parse_config(
        {
            "delay_ms": 0,
            "timeout_ms": 5000,
            "respect_robots": False,
            "sites": [{"name": "off", "urls": ["http://127.0.0.1:9/offline.html"]}],
        }
    )
    (falha,) = asyncio.run(run_audit(config))
    assert not falha.ok and falha.result is None


@requires_browser
def test_ignored_rules_are_respected(page_server):
    (result,) = audit(page_server, ["sem_alt.html"], ignored_rules=["image-alt"])
    assert result.result.violations == []
