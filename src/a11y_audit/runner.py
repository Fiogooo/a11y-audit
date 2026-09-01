"""Execução da auditoria: abre cada página, injeta o axe-core e coleta o resultado.

Decisões:

* **Playwright e não Selenium.** Instala o próprio navegador, espera por rede ociosa
  sem ``sleep`` espalhado pelo código e tem API assíncrona nativa.
* **axe-core baixado e cacheado, com versão fixada.** Empacotar o arquivo no
  repositório obrigaria a versionar código de terceiro; depender de CDN em tempo de
  execução tornaria a auditoria dependente de rede externa a cada rodada. O meio termo
  é baixar uma vez, guardar em cache local e registrar a versão em cada execução.
* **Uma falha de página não derruba a execução.** Portal fora do ar é o caso comum, não
  a exceção; a página é gravada com o erro e a auditoria segue.
"""

from __future__ import annotations

import asyncio
import time
import urllib.robotparser
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import urlopen

from .config import Config
from .normalizer import NormalizedResult, normalize

AXE_VERSION = "4.10.2"
AXE_URL = f"https://cdn.jsdelivr.net/npm/axe-core@{AXE_VERSION}/axe.min.js"
CACHE_DIR = Path.home() / ".cache" / "a11y-audit"


@dataclass(slots=True)
class PageResult:
    site: str
    url: str
    http_status: int | None = None
    load_time_ms: int | None = None
    error: str | None = None
    result: NormalizedResult | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def ensure_axe_script(cache_dir: Path = CACHE_DIR) -> str:
    """Devolve o conteúdo do axe-core, baixando na primeira vez."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"axe-{AXE_VERSION}.min.js"
    if not cached.exists():
        with urlopen(AXE_URL, timeout=60) as response:  # noqa: S310 - URL fixa e confiável
            cached.write_bytes(response.read())
    return cached.read_text(encoding="utf-8")


class RobotsCache:
    """Cache de robots.txt por domínio.

    Auditar sem checar robots.txt é falta de educação técnica e, dependendo do site,
    problema jurídico. Em caso de erro ao buscar o arquivo, liberamos o acesso: robots
    inacessível não é o mesmo que robots proibindo.
    """

    def __init__(self, user_agent: str) -> None:
        self.user_agent = user_agent
        self._parsers: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._parsers:
            parser = urllib.robotparser.RobotFileParser()
            parser.set_url(urljoin(origin, "/robots.txt"))
            try:
                parser.read()
            except Exception:
                self._parsers[origin] = None
            else:
                self._parsers[origin] = parser
        parser = self._parsers[origin]
        if parser is None:
            return True
        return parser.can_fetch(self.user_agent, url)


_AXE_RUN_JS = """
async (tags) => {
    return await axe.run(document, {
        runOnly: { type: 'tag', values: tags },
        resultTypes: ['violations', 'incomplete']
    });
}
"""


async def audit_url(context, url: str, site: str, config: Config, axe_script: str) -> PageResult:
    page = await context.new_page()
    started = time.perf_counter()
    try:
        response = await page.goto(url, wait_until="networkidle", timeout=config.timeout_ms)
        elapsed = int((time.perf_counter() - started) * 1000)
        status = response.status if response else None

        # Uma URL quebrada ainda devolve HTML: a página de erro do servidor. Auditá-la
        # contaminaria o relatório com violações que não são do site. Registramos o
        # status e não auditamos.
        if status is not None and status >= 400:
            return PageResult(
                site=site, url=url, http_status=status, load_time_ms=elapsed,
                error=f"HTTP {status} — página não auditada",
            )

        await page.add_script_tag(content=axe_script)
        raw = await page.evaluate(_AXE_RUN_JS, config.axe_tags)
        return PageResult(
            site=site,
            url=url,
            http_status=status,
            load_time_ms=elapsed,
            result=normalize(
                raw, ignored_rules=config.ignored_rules, min_impact=config.min_impact
            ),
        )
    except Exception as exc:  # noqa: BLE001 - qualquer falha vira resultado, não exceção
        return PageResult(
            site=site,
            url=url,
            load_time_ms=int((time.perf_counter() - started) * 1000),
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        await page.close()


async def run_audit(config: Config, *, on_progress=None) -> list[PageResult]:
    """Audita todas as URLs da configuração, respeitando concorrência e intervalo."""
    from playwright.async_api import async_playwright  # import tardio: CLI abre rápido

    axe_script = ensure_axe_script()
    robots = RobotsCache(config.user_agent) if config.respect_robots else None
    semaphore = asyncio.Semaphore(config.concurrency)
    results: list[PageResult] = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context(user_agent=config.user_agent)

        async def worker(site: str, url: str) -> PageResult:
            async with semaphore:
                if robots is not None and not robots.allowed(url):
                    return PageResult(site=site, url=url, error="Bloqueado por robots.txt")
                result = await audit_url(context, url, site, config, axe_script)
                if config.delay_ms:
                    await asyncio.sleep(config.delay_ms / 1000)
                return result

        tasks = [asyncio.create_task(worker(site, url)) for site, url in config.all_urls]
        for task in asyncio.as_completed(tasks):
            result = await task
            results.append(result)
            if on_progress is not None:
                on_progress(result)

        await context.close()
        await browser.close()

    order = {url: i for i, (_, url) in enumerate(config.all_urls)}
    results.sort(key=lambda r: order.get(r.url, 0))
    return results
