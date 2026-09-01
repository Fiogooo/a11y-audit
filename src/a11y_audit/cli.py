"""Interface de linha de comando."""

from __future__ import annotations

import asyncio
import datetime as dt
from pathlib import Path

import typer

from . import __version__
from .config import ConfigError, load_config
from .diff import compare
from .reports import render_html, write_csv
from .repository import (
    DEFAULT_DB,
    get_run,
    list_runs,
    make_session_factory,
    save_run,
    violation_refs,
)

app = typer.Typer(
    add_completion=False,
    help="Auditoria de acessibilidade web em lote, com histórico entre execuções.",
)

DbOption = typer.Option(DEFAULT_DB, "--db", help="Caminho do banco (SQLite) ou URL de conexão.")


def _fail(message: str) -> None:
    typer.secho(f"Erro: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=2)


@app.command()
def version() -> None:
    """Mostra a versão instalada."""
    typer.echo(f"a11y-audit {__version__}")


@app.command()
def run(
    config: Path = typer.Option(..., "--config", "-c", help="Arquivo YAML com os sites."),
    label: str | None = typer.Option(None, "--label", "-l", help="Rótulo desta execução."),
    db: str = DbOption,
) -> None:
    """Audita todas as URLs do arquivo de configuração."""
    from .runner import run_audit  # tardio: só paga o custo do Playwright aqui

    try:
        settings = load_config(config)
    except ConfigError as exc:
        _fail(str(exc))
        return

    total = len(settings.all_urls)
    typer.echo(f"Auditando {total} URL(s) com concorrência {settings.concurrency}...")

    done = 0

    def progress(result) -> None:
        nonlocal done
        done += 1
        if result.ok:
            count = len(result.result.violations) if result.result else 0
            cor = typer.colors.YELLOW if count else typer.colors.GREEN
            status = typer.style(f"{count} violação(ões)", fg=cor)
        else:
            status = typer.style(result.error or "falhou", fg=typer.colors.RED)
        typer.echo(f"  [{done}/{total}] {result.url} — {status}")

    started_at = dt.datetime.now(dt.UTC)
    results = asyncio.run(run_audit(settings, on_progress=progress))

    session_factory = make_session_factory(db)
    with session_factory() as session:
        saved = save_run(
            session,
            results,
            label=label,
            config_hash=settings.hash(),
            started_at=started_at,
        )
        typer.secho(
            f"\nExecução {saved.id} gravada: "
            f"{len(saved.pages)} página(s), {saved.violation_count} violação(ões).",
            fg=typer.colors.GREEN,
        )
        typer.echo(f"Relatório: a11y-audit report --run {saved.id} --output relatorio.html")


@app.command(name="runs")
def runs_command(
    limit: int = typer.Option(20, "--limit", "-n"),
    db: str = DbOption,
) -> None:
    """Lista as execuções gravadas."""
    with make_session_factory(db)() as session:
        found = list_runs(session, limit=limit)
        if not found:
            typer.echo("Nenhuma execução registrada ainda.")
            return
        typer.echo(f"{'ID':>4}  {'DATA':<17} {'PÁGS':>5} {'VIOL':>6}  RÓTULO")
        for item in found:
            typer.echo(
                f"{item.id:>4}  {item.started_at.strftime('%d/%m/%Y %H:%M'):<17} "
                f"{len(item.pages):>5} {item.violation_count:>6}  {item.label or ''}"
            )


@app.command()
def report(
    run_id: int = typer.Option(..., "--run", "-r", help="ID da execução."),
    output: Path = typer.Option(Path("relatorio.html"), "--output", "-o"),
    baseline: int | None = typer.Option(
        None, "--baseline", "-b", help="ID de uma execução anterior, para incluir o diff."
    ),
    db: str = DbOption,
) -> None:
    """Gera o relatório HTML de uma execução."""
    with make_session_factory(db)() as session:
        current = get_run(session, run_id)
        if current is None:
            _fail(f"Execução {run_id} não encontrada.")
            return

        difference = None
        if baseline is not None:
            previous = get_run(session, baseline)
            if previous is None:
                _fail(f"Execução {baseline} não encontrada.")
                return
            _warn_on_config_mismatch(previous, current)
            difference = compare(violation_refs(previous), violation_refs(current))

        path = render_html(current, output, diff=difference)
        typer.secho(f"Relatório gerado em {path}", fg=typer.colors.GREEN)


@app.command()
def compare_runs(
    before: int = typer.Option(..., "--from", "-f", help="Execução anterior."),
    after: int = typer.Option(..., "--to", "-t", help="Execução mais recente."),
    db: str = DbOption,
) -> None:
    """Compara duas execuções e mostra o que mudou."""
    with make_session_factory(db)() as session:
        first = get_run(session, before)
        second = get_run(session, after)
        if first is None or second is None:
            _fail("Uma das execuções informadas não existe. Veja 'a11y-audit runs'.")
            return

        _warn_on_config_mismatch(first, second)
        result = compare(violation_refs(first), violation_refs(second))

        typer.secho(f"\nNovas: {len(result.new)}", fg=typer.colors.RED)
        for item in result.new[:20]:
            typer.echo(f"  {item.impact:<9} {item.rule_id:<24} {item.url}  {item.selector}")

        typer.secho(f"\nCorrigidas: {len(result.fixed)}", fg=typer.colors.GREEN)
        for item in result.fixed[:20]:
            typer.echo(f"  {item.impact:<9} {item.rule_id:<24} {item.url}  {item.selector}")

        typer.echo(f"\nPersistentes: {len(result.persisting)}")

        if result.urls_only_in_after:
            typer.secho(
                f"\n{len(result.urls_only_in_after)} URL(s) só existem na execução mais recente "
                "e ficaram fora da comparação.",
                fg=typer.colors.YELLOW,
            )
        if result.urls_only_in_before:
            typer.secho(
                f"{len(result.urls_only_in_before)} URL(s) auditadas antes não foram auditadas "
                "desta vez.",
                fg=typer.colors.YELLOW,
            )


@app.command()
def export(
    run_id: int = typer.Option(..., "--run", "-r"),
    output: Path = typer.Option(Path("violacoes.csv"), "--output", "-o"),
    db: str = DbOption,
) -> None:
    """Exporta as violações de uma execução em CSV."""
    with make_session_factory(db)() as session:
        current = get_run(session, run_id)
        if current is None:
            _fail(f"Execução {run_id} não encontrada.")
            return
        path = write_csv(current, output)
        typer.secho(f"CSV gerado em {path}", fg=typer.colors.GREEN)


def _warn_on_config_mismatch(before, after) -> None:
    if before.config_hash and after.config_hash and before.config_hash != after.config_hash:
        typer.secho(
            "Aviso: as duas execuções usaram configurações diferentes (padrão WCAG, regras "
            "ignoradas ou lista de URLs). O diff pode refletir mudança de critério, não do site.",
            fg=typer.colors.YELLOW,
        )
    if before.axe_version and after.axe_version and before.axe_version != after.axe_version:
        typer.secho(
            f"Aviso: versões diferentes do axe-core ({before.axe_version} → {after.axe_version}). "
            "Regras podem ter sido renomeadas ou adicionadas entre as versões.",
            fg=typer.colors.YELLOW,
        )


if __name__ == "__main__":  # pragma: no cover
    app()
