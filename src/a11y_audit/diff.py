"""Comparação entre duas execuções.

Esta é a razão de existir da ferramenta. Auditar uma página o axe DevTools já faz; o
que ele não faz é responder o que mudou desde a auditoria anterior.

**Identidade de uma violação.** Duas violações são consideradas a mesma quando têm a
mesma URL, a mesma regra e o mesmo seletor CSS.

Limitação conhecida e assumida: o seletor depende da estrutura do DOM. Se o site é
reestruturado, o seletor muda e uma violação não corrigida aparece como "corrigida" e
"nova" ao mesmo tempo. Não existe identidade estável para elemento de página sem
cooperação do site auditado. A alternativa seria comparar por trecho de HTML, que é
ainda mais frágil porque qualquer mudança de texto quebra. Ficamos com o seletor e
avisamos no relatório.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from .models import impact_rank

# (url, rule_id, selector)
ViolationKey = tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class ViolationRef:
    """Violação identificada, com o mínimo necessário para exibir no diff."""

    url: str
    rule_id: str
    selector: str
    impact: str = "minor"
    description: str = ""

    @property
    def key(self) -> ViolationKey:
        return (self.url, self.rule_id, self.selector)


@dataclass(slots=True)
class DiffResult:
    new: list[ViolationRef] = field(default_factory=list)
    fixed: list[ViolationRef] = field(default_factory=list)
    persisting: list[ViolationRef] = field(default_factory=list)
    urls_only_in_before: set[str] = field(default_factory=set)
    urls_only_in_after: set[str] = field(default_factory=set)

    @property
    def is_clean(self) -> bool:
        return not self.new and not self.persisting

    @property
    def summary(self) -> dict[str, int]:
        return {
            "new": len(self.new),
            "fixed": len(self.fixed),
            "persisting": len(self.persisting),
        }


def _sorted(refs: Iterable[ViolationRef]) -> list[ViolationRef]:
    return sorted(refs, key=lambda r: (-impact_rank(r.impact), r.url, r.rule_id, r.selector))


def compare(before: Iterable[ViolationRef], after: Iterable[ViolationRef]) -> DiffResult:
    """Compara duas listas de violações.

    Só compara URLs presentes nas duas execuções. Uma URL adicionada à configuração
    entre uma auditoria e outra apareceria inteira como "violações novas", o que
    inflaria o resultado sem que nada tenha piorado. Essas URLs são reportadas à parte.
    """
    before_list = list(before)
    after_list = list(after)

    before_urls = {ref.url for ref in before_list}
    after_urls = {ref.url for ref in after_list}
    common_urls = before_urls & after_urls

    before_map = {ref.key: ref for ref in before_list if ref.url in common_urls}
    after_map = {ref.key: ref for ref in after_list if ref.url in common_urls}

    before_keys = set(before_map)
    after_keys = set(after_map)

    return DiffResult(
        new=_sorted(after_map[k] for k in after_keys - before_keys),
        fixed=_sorted(before_map[k] for k in before_keys - after_keys),
        persisting=_sorted(after_map[k] for k in before_keys & after_keys),
        urls_only_in_before=before_urls - after_urls,
        urls_only_in_after=after_urls - before_urls,
    )
