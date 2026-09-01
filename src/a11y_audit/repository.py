"""Persistência. Isola o resto do código do SQLAlchemy."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from .diff import ViolationRef
from .models import Base, Page, Run, Violation
from .runner import PageResult

DEFAULT_DB = "a11y.db"


def make_engine(database: str | Path = DEFAULT_DB):
    """SQLite por padrão.

    A string de conexão é o único ponto que muda para usar PostgreSQL, o que é o
    motivo de o projeto usar SQLAlchemy em vez de sqlite3 direto. Para quem clona o
    repositório, porém, precisa funcionar sem instalar banco nenhum.
    """
    url = str(database)
    if "://" not in url:
        url = f"sqlite:///{url}"
    engine = create_engine(url, future=True)
    Base.metadata.create_all(engine)
    return engine


def make_session_factory(database: str | Path = DEFAULT_DB) -> sessionmaker[Session]:
    return sessionmaker(bind=make_engine(database), future=True)


def save_run(
    session: Session,
    results: Iterable[PageResult],
    *,
    label: str | None,
    config_hash: str,
    started_at: dt.datetime,
) -> Run:
    results = list(results)
    axe_version = next(
        (r.result.axe_version for r in results if r.result and r.result.axe_version), None
    )
    run = Run(
        label=label,
        started_at=started_at,
        finished_at=dt.datetime.now(dt.UTC),
        axe_version=axe_version,
        config_hash=config_hash,
    )

    for page_result in results:
        page = Page(
            site=page_result.site,
            url=page_result.url,
            http_status=page_result.http_status,
            load_time_ms=page_result.load_time_ms,
            error=page_result.error,
        )
        if page_result.result is not None:
            for violation in page_result.result.violations:
                page.violations.append(
                    Violation(
                        rule_id=violation.rule_id,
                        impact=violation.impact,
                        wcag_tags=violation.wcag_tags,
                        selector=violation.selector,
                        html_snippet=violation.html_snippet,
                        description=violation.description,
                        help_url=violation.help_url,
                    )
                )
        run.pages.append(page)

    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def get_run(session: Session, run_id: int) -> Run | None:
    return session.get(Run, run_id)


def list_runs(session: Session, limit: int = 20) -> Sequence[Run]:
    stmt = select(Run).order_by(Run.started_at.desc()).limit(limit)
    return session.scalars(stmt).all()


def violation_refs(run: Run) -> list[ViolationRef]:
    """Converte uma execução persistida no formato consumido por ``diff.compare``."""
    return [
        ViolationRef(
            url=page.url,
            rule_id=violation.rule_id,
            selector=violation.selector,
            impact=violation.impact,
            description=violation.description,
        )
        for page in run.pages
        for violation in page.violations
    ]
