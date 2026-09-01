"""Conversão do JSON bruto do axe-core para o modelo de domínio.

Este módulo é deliberadamente puro: não abre navegador, não toca no banco. Recebe um
dicionário e devolve dataclasses. É o que permite testá-lo com um JSON salvo em
arquivo, sem Playwright e sem rede.

Formato de entrada (resumido), conforme a saída de ``axe.run()``::

    {
      "testEngine": {"name": "axe-core", "version": "4.10.2"},
      "violations": [
        {
          "id": "image-alt",
          "impact": "critical",
          "description": "...",
          "helpUrl": "https://...",
          "tags": ["cat.text-alternatives", "wcag2a", "wcag111"],
          "nodes": [{"target": ["img"], "html": "<img src=\\"a.png\\">"}]
        }
      ]
    }

Cada *node* do axe vira uma violação separada aqui. O axe agrupa por regra; para
auditoria em lote interessa o elemento individual, porque é ele que é corrigido.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from .models import impact_rank

# Prefixos de tag que indicam critério WCAG. O axe também emite tags de categoria
# ("cat.forms") e de boas práticas ("best-practice"), que não são critérios e por isso
# ficam fora de wcag_tags.
_WCAG_PREFIXES = ("wcag", "section508", "en-301-549", "ACT")


@dataclass(frozen=True, slots=True)
class NormalizedViolation:
    rule_id: str
    impact: str
    wcag_tags: str
    selector: str
    html_snippet: str
    description: str
    help_url: str

    @property
    def key(self) -> tuple[str, str]:
        """Identidade da violação para efeito de comparação entre execuções."""
        return (self.rule_id, self.selector)


@dataclass(slots=True)
class NormalizedResult:
    violations: list[NormalizedViolation] = field(default_factory=list)
    axe_version: str | None = None
    incomplete_count: int = 0
    """Checagens que o axe não conseguiu decidir sozinho.

    Não são violações e não entram no relatório como tal, mas o número é registrado
    porque representa exatamente a parte que exige revisão manual.
    """


def extract_wcag_tags(tags: Iterable[str]) -> str:
    wcag = sorted(t for t in tags if t.lower().startswith(tuple(p.lower() for p in _WCAG_PREFIXES)))
    return ",".join(wcag)


def _selector_from_target(target: Any) -> str:
    """O ``target`` do axe é uma lista; com iframes, vem aninhado.

    Achatamos com ' >>> ', que é a convenção que o próprio axe usa para indicar
    travessia de frame.
    """
    if isinstance(target, str):
        return target
    if isinstance(target, (list, tuple)):
        parts = [_selector_from_target(item) for item in target]
        return " >>> ".join(p for p in parts if p)
    return str(target or "")


def normalize(
    raw: dict[str, Any],
    *,
    ignored_rules: Iterable[str] = (),
    min_impact: str | None = None,
) -> NormalizedResult:
    """Achata a saída do axe-core em uma lista de violações por elemento."""
    ignored = {r.strip().lower() for r in ignored_rules if r and r.strip()}
    floor = impact_rank(min_impact) if min_impact else 0

    result = NormalizedResult(
        axe_version=(raw.get("testEngine") or {}).get("version"),
        incomplete_count=len(raw.get("incomplete") or []),
    )

    for rule in raw.get("violations") or []:
        rule_id = (rule.get("id") or "").strip()
        if not rule_id or rule_id.lower() in ignored:
            continue

        impact = (rule.get("impact") or "minor").lower()
        if impact_rank(impact) < floor:
            continue

        wcag_tags = extract_wcag_tags(rule.get("tags") or [])
        description = (rule.get("description") or "").strip()
        help_url = (rule.get("helpUrl") or "").strip()

        nodes = rule.get("nodes") or []
        if not nodes:
            # Regra violada sem nó associado é raro, mas não pode ser descartada em
            # silêncio: vira uma violação sem seletor.
            nodes = [{}]

        for node in nodes:
            result.violations.append(
                NormalizedViolation(
                    rule_id=rule_id,
                    impact=impact,
                    wcag_tags=wcag_tags,
                    selector=_selector_from_target(node.get("target")),
                    html_snippet=(node.get("html") or "").strip()[:2000],
                    description=description,
                    help_url=help_url,
                )
            )

    result.violations.sort(key=lambda v: (-impact_rank(v.impact), v.rule_id, v.selector))
    return result
