"""merge_pass1_kept_into_signals ordering and field attachment."""

from data_analyst_agent.brief_utils import merge_pass1_kept_into_signals


def test_merge_orders_by_rank_and_attaches_fields():
    signals = [
        {"id": "a", "category": "Trend", "detail": "x", "metric": "m1", "source": "s", "score": 1.0, "title": "t"},
        {"id": "b", "category": "Variance", "detail": "y", "metric": "m2", "source": "s", "score": 0.9, "title": "t"},
    ]
    kept = [
        {
            "id": "b",
            "rank": 1,
            "one_line_why": "why b",
            "category": "Revenue",
            "metric_description": "desc b",
            "clean_name": "CN B",
            "dimension": "Region: East",
        },
        {
            "id": "a",
            "rank": 2,
            "one_line_why": "why a",
            "category": "Capacity",
            "metric_description": "desc a",
            "clean_name": "CN A",
            "dimension": "Network",
        },
    ]
    out = merge_pass1_kept_into_signals(signals, kept)
    assert [x["id"] for x in out] == ["b", "a"]
    assert out[0]["category"] == "Variance"
    assert out[0]["executive_category"] == "Revenue"
    assert out[0]["clean_name"] == "CN B"
    assert out[0]["pass1_rank"] == 1
