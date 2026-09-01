import pytest

from a11y_audit.config import ConfigError, load_config, parse_config

BASE = {"sites": [{"name": "Exemplo", "urls": ["https://exemplo.gov.br/"]}]}


def test_defaults():
    config = parse_config(BASE)
    assert config.concurrency == 4
    assert config.standard == "wcag21aa"
    assert config.respect_robots is True
    assert config.all_urls == [("Exemplo", "https://exemplo.gov.br/")]


def test_duplicate_urls_are_audited_once():
    config = parse_config(
        {
            "sites": [
                {"name": "A", "urls": ["https://a.gov.br/", "https://a.gov.br/"]},
                {"name": "B", "urls": ["https://a.gov.br/"]},
            ]
        }
    )
    assert len(config.all_urls) == 1


def test_hash_is_stable_regardless_of_url_order():
    first = parse_config({"sites": [{"name": "A", "urls": ["https://a.gov.br/", "https://b.gov.br/"]}]})
    second = parse_config({"sites": [{"name": "A", "urls": ["https://b.gov.br/", "https://a.gov.br/"]}]})
    assert first.hash() == second.hash()


def test_hash_changes_when_standard_changes():
    first = parse_config(BASE)
    second = parse_config({**BASE, "standard": "wcag2a"})
    assert first.hash() != second.hash()


@pytest.mark.parametrize(
    "payload, trecho",
    [
        ({}, "sites"),
        ({"sites": [{"name": "A", "urls": []}]}, "nenhuma URL"),
        ({"sites": [{"name": "A", "urls": ["exemplo.gov.br"]}]}, "precisa começar com http"),
        ({**BASE, "standard": "wcag9z"}, "desconhecido"),
        ({**BASE, "min_impact": "grave"}, "inválido"),
        ({**BASE, "concurrency": 0}, ">= 1"),
        ({**BASE, "concurrency": "muitos"}, "número inteiro"),
    ],
)
def test_invalid_configs_explain_the_problem(payload, trecho):
    with pytest.raises(ConfigError) as erro:
        parse_config(payload)
    assert trecho in str(erro.value)


def test_missing_file():
    with pytest.raises(ConfigError, match="não encontrado"):
        load_config("/tmp/nao-existe-config.yaml")


def test_accepts_portuguese_keys():
    config = parse_config({"sites": [{"nome": "Órgão", "urls": ["https://a.gov.br/"]}]})
    assert config.sites[0].name == "Órgão"


def test_standard_expands_to_cumulative_axe_tags():
    """O axe marca cada regra com o nível em que ela foi introduzida.

    Pedir apenas 'wcag21aa' roda só as regras novas da 2.1 e deixa passar violações
    básicas como image-alt, que é wcag2a. Regressão encontrada em teste real.
    """
    config = parse_config({**BASE, "standard": "wcag21aa"})
    assert config.axe_tags == ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]
    assert "wcag2a" in parse_config({**BASE, "standard": "wcag2aa"}).axe_tags


def test_stricter_standard_never_runs_fewer_tags():
    aa = set(parse_config({**BASE, "standard": "wcag21aa"}).axe_tags)
    a = set(parse_config({**BASE, "standard": "wcag2a"}).axe_tags)
    assert a <= aa
