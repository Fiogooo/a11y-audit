"""Testa persistência, relatório e o fluxo completo sem abrir navegador."""

from __future__ import annotations

import datetime as dt

from a11y_audit.diff import compare
from a11y_audit.normalizer import normalize
from a11y_audit.reports import render_html, write_csv
from a11y_audit.repository import (
    get_run,
    list_runs,
    make_session_factory,
    save_run,
    violation_refs,
)
from a11y_audit.runner import PageResult


def build_results(axe_sample, url="https://exemplo.gov.br/"):
    return [
        PageResult(
            site="Exemplo",
            url=url,
            http_status=200,
            load_time_ms=420,
            result=normalize(axe_sample),
        ),
        PageResult(site="Exemplo", url=url + "erro", error="TimeoutError: 30000ms"),
    ]


def make_session(tmp_path):
    return make_session_factory(tmp_path / "teste.db")()


def test_save_and_read_back(tmp_path, axe_sample):
    with make_session(tmp_path) as session:
        run = save_run(
            session,
            build_results(axe_sample),
            label="baseline",
            config_hash="abc",
            started_at=dt.datetime.now(dt.UTC),
        )

        assert run.id is not None
        assert run.axe_version == "4.10.2"
        assert run.violation_count == 5

        reloaded = get_run(session, run.id)
        assert reloaded is not None
        assert len(reloaded.pages) == 2
        assert [p.ok for p in reloaded.pages] == [True, False]
        assert list_runs(session)[0].label == "baseline"


def test_failed_page_does_not_lose_the_run(tmp_path, axe_sample):
    with make_session(tmp_path) as session:
        run = save_run(
            session,
            [PageResult(site="X", url="https://x.gov.br/", error="ConnectionError")],
            label=None,
            config_hash="abc",
            started_at=dt.datetime.now(dt.UTC),
        )
        assert run.violation_count == 0
        assert run.pages[0].error == "ConnectionError"


def test_html_report_includes_the_manual_review_warning(tmp_path, axe_sample):
    with make_session(tmp_path) as session:
        run = save_run(
            session,
            build_results(axe_sample),
            label="r1",
            config_hash="abc",
            started_at=dt.datetime.now(dt.UTC),
        )
        path = render_html(run, tmp_path / "relatorio.html")
        html = path.read_text(encoding="utf-8")

        assert "image-alt" in html
        assert "30% e 40%" in html
        assert "TimeoutError" in html


def test_csv_has_one_line_per_violation(tmp_path, axe_sample):
    with make_session(tmp_path) as session:
        run = save_run(
            session,
            build_results(axe_sample),
            label="r1",
            config_hash="abc",
            started_at=dt.datetime.now(dt.UTC),
        )
        path = write_csv(run, tmp_path / "violacoes.csv")
        linhas = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(linhas) == 6  # cabeçalho + 5 violações


def test_end_to_end_diff_between_two_saved_runs(tmp_path, axe_sample):
    with make_session(tmp_path) as session:
        before = save_run(
            session,
            build_results(axe_sample),
            label="antes",
            config_hash="abc",
            started_at=dt.datetime.now(dt.UTC),
        )

        corrigido = {**axe_sample, "violations": axe_sample["violations"][:1]}
        after = save_run(
            session,
            build_results(corrigido),
            label="depois",
            config_hash="abc",
            started_at=dt.datetime.now(dt.UTC),
        )

        resultado = compare(violation_refs(before), violation_refs(after))
        assert resultado.summary == {"new": 0, "fixed": 3, "persisting": 2}
