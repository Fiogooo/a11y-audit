"""Leitura e validação do arquivo de configuração."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# O axe-core marca cada regra com o nível em que ela foi INTRODUZIDA: `image-alt` é
# `wcag2a` e continua sendo, mesmo valendo para WCAG 2.1 AA. Passar apenas "wcag21aa"
# para o `runOnly` roda só as regras novas da versão 2.1 e deixa passar quase tudo.
# Por isso cada padrão é expandido no conjunto acumulado de níveis que ele engloba.
STANDARD_TAGS: dict[str, list[str]] = {
    "wcag2a": ["wcag2a"],
    "wcag2aa": ["wcag2a", "wcag2aa"],
    "wcag2aaa": ["wcag2a", "wcag2aa", "wcag2aaa"],
    "wcag21a": ["wcag2a", "wcag21a"],
    "wcag21aa": ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"],
    "wcag22aa": ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"],
}

VALID_STANDARDS = set(STANDARD_TAGS)
VALID_IMPACTS = {"minor", "moderate", "serious", "critical"}


class ConfigError(ValueError):
    """Configuração inválida. Mensagem escrita para ser lida por humano."""


@dataclass(slots=True)
class Site:
    name: str
    urls: list[str]


@dataclass(slots=True)
class Config:
    sites: list[Site]
    concurrency: int = 4
    delay_ms: int = 500
    timeout_ms: int = 30_000
    respect_robots: bool = True
    standard: str = "wcag21aa"
    ignored_rules: list[str] = field(default_factory=list)
    min_impact: str | None = None
    user_agent: str = "a11y-audit (+https://github.com/SEU-USUARIO/a11y-audit)"

    @property
    def axe_tags(self) -> list[str]:
        """Tags que o axe-core deve rodar para o padrão configurado."""
        return STANDARD_TAGS[self.standard]

    @property
    def all_urls(self) -> list[tuple[str, str]]:
        return [(site.name, url) for site in self.sites for url in site.urls]

    def hash(self) -> str:
        """Hash estável da configuração.

        Serve para detectar comparação entre execuções feitas com parâmetros
        diferentes, que é uma fonte silenciosa de diff enganoso.
        """
        payload = {
            "standard": self.standard,
            "ignored_rules": sorted(self.ignored_rules),
            "min_impact": self.min_impact,
            "urls": sorted(url for _, url in self.all_urls),
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _require_positive(value: Any, name: str, minimum: int = 1) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ConfigError(f"'{name}' precisa ser um número inteiro, recebi {value!r}") from None
    if number < minimum:
        raise ConfigError(f"'{name}' precisa ser >= {minimum}, recebi {number}")
    return number


def parse_config(data: dict[str, Any]) -> Config:
    if not isinstance(data, dict):
        raise ConfigError("O arquivo de configuração precisa ser um mapeamento YAML.")

    raw_sites = data.get("sites")
    if not raw_sites:
        raise ConfigError("Nenhum site configurado: a chave 'sites' está vazia ou ausente.")

    sites: list[Site] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_sites, start=1):
        if not isinstance(raw, dict):
            raise ConfigError(f"O site #{index} precisa ser um mapeamento com 'nome' e 'urls'.")
        name = str(raw.get("name") or raw.get("nome") or f"site-{index}")
        urls = raw.get("urls") or []
        if not urls:
            raise ConfigError(f"O site '{name}' não tem nenhuma URL.")

        clean: list[str] = []
        for url in urls:
            url = str(url).strip()
            if not url.startswith(("http://", "https://")):
                raise ConfigError(f"URL inválida em '{name}': {url!r} (precisa começar com http)")
            if url in seen:
                continue  # a mesma URL em dois sites seria auditada duas vezes à toa
            seen.add(url)
            clean.append(url)
        sites.append(Site(name=name, urls=clean))

    standard = str(data.get("standard") or data.get("padrao_wcag") or "wcag21aa").lower()
    if standard not in VALID_STANDARDS:
        raise ConfigError(
            f"Padrão '{standard}' desconhecido. Use um destes: {', '.join(sorted(VALID_STANDARDS))}"
        )

    min_impact = data.get("min_impact")
    if min_impact is not None:
        min_impact = str(min_impact).lower()
        if min_impact not in VALID_IMPACTS:
            raise ConfigError(
                f"Impacto mínimo '{min_impact}' inválido. Use: {', '.join(sorted(VALID_IMPACTS))}"
            )

    config = Config(
        sites=sites,
        concurrency=_require_positive(data.get("concurrency", 4), "concurrency"),
        delay_ms=_require_positive(data.get("delay_ms", 500), "delay_ms", minimum=0),
        timeout_ms=_require_positive(data.get("timeout_ms", 30_000), "timeout_ms", minimum=1000),
        respect_robots=bool(data.get("respect_robots", True)),
        standard=standard,
        ignored_rules=[str(r) for r in (data.get("ignored_rules") or [])],
        min_impact=min_impact,
    )
    if data.get("user_agent"):
        config.user_agent = str(data["user_agent"])
    return config


def load_config(path: str | Path) -> Config:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"Arquivo de configuração não encontrado: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return parse_config(data)
