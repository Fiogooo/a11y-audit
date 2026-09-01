"""Exportação em CSV, para quem quer levar o resultado para planilha ou Pandas."""

from __future__ import annotations

import csv
from pathlib import Path

from ..models import Run

COLUMNS = [
    "run_id",
    "site",
    "url",
    "http_status",
    "rule_id",
    "impact",
    "wcag_tags",
    "selector",
    "description",
    "help_url",
]


def write_csv(run: Run, path: str | Path) -> Path:
    path = Path(path)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for page in run.pages:
            for violation in page.violations:
                writer.writerow(
                    {
                        "run_id": run.id,
                        "site": page.site,
                        "url": page.url,
                        "http_status": page.http_status,
                        "rule_id": violation.rule_id,
                        "impact": violation.impact,
                        "wcag_tags": violation.wcag_tags,
                        "selector": violation.selector,
                        "description": violation.description,
                        "help_url": violation.help_url,
                    }
                )
    return path
