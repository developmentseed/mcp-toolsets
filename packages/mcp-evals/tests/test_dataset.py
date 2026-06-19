from mcp_evals.dataset import EvalCase, parse_cases, select

CSV = """test_id,group,query,expected_answer,expected_dataset_ids,expected_tools,forbidden_tools,status,notes
a,cds,find era5,picks era5,"reanalysis-era5-single-levels, reanalysis-era5-land",search_datasets; search_eqc,,,first
b,aoi,bbox alps,a bbox,,aoi_from_place,,,
c,smoke,placeholder,,,,,skip,draft

,,,,,,,,
"""


def test_parse_splits_lists_on_the_right_separator():
    cases = {c.test_id: c for c in parse_cases(CSV)}
    assert cases["a"].expected_dataset_ids == [
        "reanalysis-era5-single-levels",
        "reanalysis-era5-land",
    ]
    assert cases["a"].expected_tools == ["search_datasets", "search_eqc"]
    assert cases["b"].expected_dataset_ids == []


def test_parse_skips_blank_rows():
    # The trailing all-empty row is dropped, the skip row is kept (filtered later).
    assert {c.test_id for c in parse_cases(CSV)} == {"a", "b", "c"}


def test_status_is_normalized_and_drives_is_active():
    case = EvalCase(test_id="x", query="q", status=" SKIP ")
    assert case.status == "skip"
    assert not case.is_active
    assert EvalCase(test_id="y", query="q").is_active


def test_has_expectation():
    assert not EvalCase(test_id="x", query="q").has_expectation
    assert EvalCase(test_id="x", query="q", expected_answer="a").has_expectation
    assert EvalCase(test_id="x", query="q", expected_dataset_ids=["d"]).has_expectation


def test_select_filters_skip_then_group_then_sample():
    cases = parse_cases(CSV)
    assert {c.test_id for c in select(cases)} == {"a", "b"}  # skip dropped
    assert [c.test_id for c in select(cases, group="cds")] == ["a"]
    assert len(select(cases, sample=1)) == 1


def test_select_keeps_rows_missing_some_expectations():
    # Only status=skip drops a whole row; a row with no expected_* is kept
    # (its unset dimensions are simply not scored later, not failed).
    cases = [
        EvalCase(test_id="a", query="q", expected_tools=["t"]),
        EvalCase(test_id="b", query="q"),  # no expectation at all
        EvalCase(test_id="c", query="q", status="skip"),
    ]
    assert {c.test_id for c in select(cases)} == {"a", "b"}


def test_unknown_columns_are_preserved():
    case = parse_cases("test_id,query,priority\nx,do it,high\n")[0]
    assert case.model_extra == {"priority": "high"}
