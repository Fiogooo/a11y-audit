from a11y_audit.normalizer import extract_wcag_tags, normalize


def test_flattens_one_violation_per_node(axe_sample):
    result = normalize(axe_sample)
    # image-alt tem 2 nós, color-contrast 1, region 1, frame-title 1
    assert len(result.violations) == 5
    assert sum(1 for v in result.violations if v.rule_id == "image-alt") == 2


def test_reads_axe_version_and_incomplete(axe_sample):
    result = normalize(axe_sample)
    assert result.axe_version == "4.10.2"
    assert result.incomplete_count == 1


def test_sorts_by_impact(axe_sample):
    result = normalize(axe_sample)
    assert result.violations[0].impact == "critical"
    assert result.violations[-1].impact == "moderate"


def test_ignored_rules_are_dropped(axe_sample):
    result = normalize(axe_sample, ignored_rules=["region"])
    assert all(v.rule_id != "region" for v in result.violations)
    assert len(result.violations) == 4


def test_min_impact_filters_out_lighter_violations(axe_sample):
    result = normalize(axe_sample, min_impact="serious")
    assert {v.impact for v in result.violations} == {"critical", "serious"}


def test_nested_target_becomes_frame_selector(axe_sample):
    result = normalize(axe_sample)
    frame = next(v for v in result.violations if v.rule_id == "frame-title")
    assert frame.selector == "#mapa >>> iframe"


def test_only_wcag_tags_are_kept():
    tags = extract_wcag_tags(["cat.color", "wcag2aa", "wcag143", "best-practice"])
    assert tags == "wcag143,wcag2aa"


def test_violation_without_nodes_is_not_silently_dropped():
    raw = {"violations": [{"id": "orfa", "impact": "minor", "tags": ["wcag2a"], "nodes": []}]}
    result = normalize(raw)
    assert len(result.violations) == 1
    assert result.violations[0].selector == ""


def test_empty_payload():
    result = normalize({})
    assert result.violations == []
    assert result.axe_version is None
