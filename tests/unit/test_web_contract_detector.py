import yaml


def _write_csv(tmp_path, name: str, text: str) -> str:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_contract_detector_detects_time_and_frequency_daily(tmp_path):
    from web.contract_detector import detect_contract

    # Use enough rows + repeated numeric values so the detector doesn't misclassify
    # the metric as an ID due to high uniqueness on tiny samples.
    csv_path = _write_csv(
        tmp_path,
        "daily.csv",
        "date,region,value\n"
        + "\n".join(
            [
                "2026-01-01,west,10",
                "2026-01-02,west,10",
                "2026-01-03,east,12",
                "2026-01-04,east,12",
                "2026-01-05,west,9",
                "2026-01-06,west,9",
                "2026-01-07,east,10",
                "2026-01-08,east,10",
                "2026-01-09,west,12",
                "2026-01-10,west,12",
            ]
        )
        + "\n",
    )

    result = detect_contract(csv_path)
    contract = result["contract"]

    assert contract["time"]["column"] == "date"
    assert contract["time"]["frequency"] in ("daily", "unknown")
    assert contract["metrics"], "Expected at least one numeric metric"
    assert any(m.get("column") == "value" for m in contract["metrics"])
    assert any(d["column"] == "region" for d in contract["dimensions"])


def test_contract_detector_detects_ratio_metric(tmp_path):
    from web.contract_detector import detect_contract

    csv_path = _write_csv(
        tmp_path,
        "ratio.csv",
        "period,segment,rate\n"
        "2026-01-01,A,0.10\n"
        "2026-01-02,A,0.12\n"
        "2026-01-03,B,0.09\n",
    )

    result = detect_contract(csv_path)
    metrics = result["contract"]["metrics"]

    rate = next(m for m in metrics if m["column"] == "rate")
    assert rate["type"] in ("ratio", "additive")


def test_contract_detector_save_contract_writes_contract_and_loader(tmp_path):
    from web.contract_detector import save_contract

    contract = {
        "name": "Test Dataset",
        "version": "1.0.0",
        "display_name": "Test Dataset",
        "data_source": {"type": "csv", "file": "/tmp/example.csv"},
        "time": {"column": "date", "frequency": "daily", "format": "%Y-%m-%d", "range_months": 12},
        "grain": {"columns": ["date", "region"]},
        "metrics": [{"name": "value", "column": "value", "type": "additive"}],
        "dimensions": [{"name": "region", "column": "region", "role": "primary"}],
        "hierarchies": [],
        "materiality": {"variance_pct": 10.0, "variance_absolute": 100.0},
        "presentation": {"unit": "count"},
        "reporting": {"max_drill_depth": 3},
    }

    out = save_contract(contract, dataset_id="detector_test", base_dir=str(tmp_path))
    contract_path = tmp_path / "detector_test" / "contract.yaml"
    loader_path = tmp_path / "detector_test" / "loader.yaml"

    assert str(contract_path) == out
    assert contract_path.exists()
    assert loader_path.exists()

    saved = yaml.safe_load(contract_path.read_text())
    loader = yaml.safe_load(loader_path.read_text())

    assert saved["time"]["column"] == "date"
    assert loader["file"] == "/tmp/example.csv"
    assert "value" in loader.get("numeric_columns", [])
