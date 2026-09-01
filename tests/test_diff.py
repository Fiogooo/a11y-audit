from a11y_audit.diff import ViolationRef, compare


def ref(url="https://a.gov.br/", rule="image-alt", selector="img", impact="critical"):
    return ViolationRef(url=url, rule_id=rule, selector=selector, impact=impact)


def test_detects_new_fixed_and_persisting():
    before = [ref(selector="img.logo"), ref(rule="color-contrast", selector="p")]
    after = [ref(selector="img.logo"), ref(rule="frame-title", selector="iframe")]

    result = compare(before, after)

    assert [v.rule_id for v in result.new] == ["frame-title"]
    assert [v.rule_id for v in result.fixed] == ["color-contrast"]
    assert [v.rule_id for v in result.persisting] == ["image-alt"]


def test_identical_runs_produce_no_change():
    violations = [ref(), ref(rule="color-contrast", selector="p")]
    result = compare(violations, list(violations))
    assert result.summary == {"new": 0, "fixed": 0, "persisting": 2}


def test_urls_absent_from_one_side_are_excluded_from_the_diff():
    before = [ref(url="https://a.gov.br/")]
    after = [ref(url="https://a.gov.br/"), ref(url="https://b.gov.br/", selector="img")]

    result = compare(before, after)

    # a URL nova não deve inflar "novas violações"
    assert result.new == []
    assert result.urls_only_in_after == {"https://b.gov.br/"}


def test_same_rule_on_different_selectors_are_different_violations():
    before = [ref(selector="img:nth-child(1)")]
    after = [ref(selector="img:nth-child(2)")]
    result = compare(before, after)
    assert len(result.new) == 1 and len(result.fixed) == 1


def test_new_violations_are_ordered_by_impact():
    after = [
        ref(rule="a", selector="1", impact="minor"),
        ref(rule="b", selector="2", impact="critical"),
        ref(rule="c", selector="3", impact="moderate"),
    ]
    result = compare([ref(rule="z", selector="0")], after)
    assert [v.impact for v in result.new] == ["critical", "moderate", "minor"]


def test_empty_runs():
    assert compare([], []).summary == {"new": 0, "fixed": 0, "persisting": 0}
