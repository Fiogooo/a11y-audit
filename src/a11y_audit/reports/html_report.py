"""Relatório HTML.

Arquivo único, sem CSS externo e sem JavaScript, para que possa ser anexado em e-mail
ou aberto direto do disco. Um relatório de acessibilidade que depende de CDN para
renderizar seria uma ironia dispensável.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..diff import DiffResult
from ..models import Run, impact_rank

TEMPLATE_DIR = Path(__file__).parent / "templates"


@dataclass(slots=True)
class SiteSummary:
    name: str
    pages: int
    failed_pages: int
    violations: int
    by_impact: dict[str, int]


def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def summarize(run: Run) -> list[SiteSummary]:
    grouped: dict[str, list] = {}
    for page in run.pages:
        grouped.setdefault(page.site or "—", []).append(page)

    summaries: list[SiteSummary] = []
    for name, pages in grouped.items():
        counter: Counter[str] = Counter()
        total = 0
        for page in pages:
            for violation in page.violations:
                counter[violation.impact] += 1
                total += 1
        summaries.append(
            SiteSummary(
                name=name,
                pages=len(pages),
                failed_pages=sum(1 for p in pages if not p.ok),
                violations=total,
                by_impact=dict(sorted(counter.items(), key=lambda kv: -impact_rank(kv[0]))),
            )
        )
    summaries.sort(key=lambda s: -s.violations)
    return summaries


def top_rules(run: Run, limit: int = 10) -> list[tuple[str, int, str]]:
    """Regras mais violadas. É por onde uma equipe deve começar a corrigir."""
    counter: Counter[str] = Counter()
    impacts: dict[str, str] = {}
    for page in run.pages:
        for violation in page.violations:
            counter[violation.rule_id] += 1
            impacts.setdefault(violation.rule_id, violation.impact)
    return [(rule, count, impacts.get(rule, "")) for rule, count in counter.most_common(limit)]


def render_html(run: Run, path: str | Path, *, diff: DiffResult | None = None) -> Path:
    path = Path(path)
    template = _environment().get_template("report.html.j2")
    html = template.render(
        run=run,
        summaries=summarize(run),
        top_rules=top_rules(run),
        pages=sorted(run.pages, key=lambda p: (-len(p.violations), p.url)),
        diff=diff,
        total_violations=run.violation_count,
        failed_pages=[p for p in run.pages if not p.ok],
    )
    path.write_text(html, encoding="utf-8")
    return path
