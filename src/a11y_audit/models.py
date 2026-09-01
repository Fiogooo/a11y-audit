"""Entidades persistidas.

Uma execução (Run) agrupa páginas (Page), e cada página tem violações (Violation).

Duas decisões que valem registro:

* ``axe_version`` fica na execução, não na violação. Regras do axe-core mudam de nome
  entre versões; sem guardar a versão, uma violação que "sumiu" pode ser apenas uma
  regra renomeada, e a comparação entre execuções passa a mentir.
* O índice ``(rule_id, selector)`` existe porque essa dupla é a identidade de uma
  violação para efeito de diff. Ver ``diff.py``.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str | None] = mapped_column(String(120), default=None)
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(dt.UTC)
    )
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)
    axe_version: Mapped[str | None] = mapped_column(String(20), default=None)
    config_hash: Mapped[str] = mapped_column(String(64), default="")

    pages: Mapped[list[Page]] = relationship(
        back_populates="run", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def violation_count(self) -> int:
        return sum(len(page.violations) for page in self.pages)

    def __repr__(self) -> str:  # pragma: no cover - conveniência de debug
        return f"<Run id={self.id} label={self.label!r} pages={len(self.pages)}>"


class Page(Base):
    __tablename__ = "pages"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    site: Mapped[str] = mapped_column(String(120), default="")
    url: Mapped[str] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(Integer, default=None)
    load_time_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    # Preenchido quando a página falhou. Uma URL fora do ar não interrompe a execução.
    error: Mapped[str | None] = mapped_column(Text, default=None)

    run: Mapped[Run] = relationship(back_populates="pages")
    violations: Mapped[list[Violation]] = relationship(
        back_populates="page", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def ok(self) -> bool:
        return self.error is None


class Violation(Base):
    __tablename__ = "violations"

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id"), index=True)
    rule_id: Mapped[str] = mapped_column(String(80))
    impact: Mapped[str] = mapped_column(String(20), default="minor")
    wcag_tags: Mapped[str] = mapped_column(String(200), default="")
    selector: Mapped[str] = mapped_column(Text, default="")
    html_snippet: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    help_url: Mapped[str] = mapped_column(Text, default="")

    page: Mapped[Page] = relationship(back_populates="violations")


Index("ix_violations_rule_selector", Violation.rule_id, Violation.selector)


# Ordem usada para classificar e ordenar relatórios. O axe-core usa estes quatro
# valores; qualquer coisa fora disso cai em 0 e aparece por último.
IMPACT_ORDER: dict[str, int] = {
    "critical": 4,
    "serious": 3,
    "moderate": 2,
    "minor": 1,
}


def impact_rank(impact: str | None) -> int:
    return IMPACT_ORDER.get((impact or "").lower(), 0)
