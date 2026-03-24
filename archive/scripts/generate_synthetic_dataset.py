import pandas as pd
import numpy as np
from pathlib import Path

rng = np.random.default_rng(42)

flows = ["imports", "exports"]

regions_states = {
    "West": [("CA", "California"), ("WA", "Washington")],
    "South": [("TX", "Texas"), ("FL", "Florida")],
    "Midwest": [("IL", "Illinois"), ("MI", "Michigan")],
    "Northeast": [("NY", "New York"), ("PA", "Pennsylvania")],
}

state_ports = {
    "CA": [("LAX", "Los Angeles"), ("LGB", "Long Beach"), ("OAK", "Oakland")],
    "WA": [("SEA", "Seattle"), ("TAC", "Tacoma"), ("EVE", "Everett")],
    "TX": [("HOU", "Houston"), ("DAL", "Dallas"), ("ELP", "El Paso")],
    "FL": [("MIA", "Miami"), ("JAX", "Jacksonville"), ("TPA", "Tampa")],
    "IL": [("CHI", "Chicago"), ("RFD", "Rockford"), ("PEO", "Peoria")],
    "MI": [("DET", "Detroit"), ("GRR", "Grand Rapids"), ("SAG", "Saginaw")],
    "NY": [("NYC", "New York"), ("NWK", "Newark"), ("BUF", "Buffalo")],
    "PA": [("PHL", "Philadelphia"), ("PIT", "Pittsburgh"), ("ABE", "Allentown")],
}

hs_map = {
    "27": ("Energy", [("2710", "Refined petroleum"), ("2711", "Natural gas")]),
    "84": ("Machinery", [("8409", "Engine parts"), ("8471", "Computers")]),
    "85": ("Electronics", [("8517", "Telecom equipment"), ("8542", "Semiconductors")]),
    "87": ("Vehicles", [("8703", "Passenger vehicles"), ("8708", "Auto parts")]),
    "30": ("Pharma", [("3004", "Medicaments"), ("3002", "Biotech products")]),
    "39": ("Plastics", [("3901", "Polymers of ethylene"), ("3923", "Plastic packaging")]),
}

monthly_dates = pd.date_range("2019-01-31", "2025-12-31", freq="ME")
weekly_dates = pd.date_range("2019-01-06", "2025-12-28", freq="W-SUN")

flow_multiplier = {"imports": 1.18, "exports": 1.0}
region_multiplier = {"West": 1.22, "South": 1.14, "Midwest": 1.02, "Northeast": 0.94}
state_multiplier = {
    "CA": 1.30, "WA": 1.00, "TX": 1.22, "FL": 0.95,
    "IL": 1.05, "MI": 1.00, "NY": 1.08, "PA": 0.90
}
hs2_multiplier = {"27": 1.10, "84": 0.95, "85": 1.20, "87": 1.08, "30": 0.88, "39": 0.92}

rows = []

def baseline_value(flow, region, state, port_code, hs2, hs4, dt, grain):
    port_idx = sum(ord(c) for c in port_code) % 9
    hs4_idx = int(hs4) % 17
    base = 3_800_000
    base *= flow_multiplier[flow]
    base *= region_multiplier[region]
    base *= state_multiplier[state]
    base *= hs2_multiplier[hs2]
    base *= (0.92 + port_idx * 0.03)
    base *= (0.90 + hs4_idx * 0.012)
    year_offset = dt.year - 2019
    base *= (1.0 + 0.035 * year_offset)
    if grain == "monthly":
        m = dt.month
        season = 1.0 + 0.10 * np.sin((m - 1) / 12 * 2 * np.pi) + 0.03 * np.cos((m - 1) / 12 * 4 * np.pi)
        grain_mult = 1.0
    else:
        week = dt.isocalendar().week
        season = 1.0 + 0.06 * np.sin((week - 1) / 52 * 2 * np.pi)
        grain_mult = 0.26
    return base * season * grain_mult

def volume_from_value(value, hs2):
    unit_factor = {"27": 0.00085, "84": 0.00018, "85": 0.00012, "87": 0.00016, "30": 0.00009, "39": 0.00022}
    return value * unit_factor[hs2]

def anomaly_for_row(flow, region, state, port_code, hs2, hs4, dt, grain):
    if (flow == "imports" and region == "West" and state == "CA" and port_code == "LAX" and hs2 == "85" and hs4 == "8542"):
        if grain == "weekly" and pd.Timestamp("2022-09-04") <= dt <= pd.Timestamp("2022-10-30"):
            return (0.56, "A1", "volume_drop", "negative", "high", "Tariff-style shock: West imports, California, Los Angeles, HS4 8542 semiconductors dropped sharply for 8 weeks.")
        if grain == "monthly" and dt in set(pd.to_datetime(["2022-09-30", "2022-10-31"])):
            return (0.62, "A1", "volume_drop", "negative", "high", "Tariff-style shock: West imports, California, Los Angeles, HS4 8542 semiconductors dropped sharply in Sep-Oct 2022.")

    if (flow == "exports" and region == "South" and state == "TX" and port_code == "HOU" and hs2 == "27"):
        if grain == "weekly" and pd.Timestamp("2024-04-07") <= dt <= pd.Timestamp("2024-06-30"):
            mult = 1.42 if hs4 == "2711" else 1.28
            return (mult, "B1", "surge", "positive", "high", "Energy export surge: Texas Houston exports accelerated in Q2 2024, led by HS2 27 and strongest in HS4 2711 natural gas.")
        if grain == "monthly" and dt in set(pd.to_datetime(["2024-04-30", "2024-05-31", "2024-06-30"])):
            mult = 1.36 if hs4 == "2711" else 1.22
            return (mult, "B1", "surge", "positive", "high", "Energy export surge: Texas Houston exports accelerated in Q2 2024, led by HS2 27 and strongest in HS4 2711 natural gas.")

    if (region == "Northeast" and state == "NY" and port_code == "NWK" and hs2 in {"30", "85"}):
        if grain == "weekly" and pd.Timestamp("2023-01-08") <= dt <= pd.Timestamp("2023-02-19"):
            return (0.71, "C1", "weather_disruption", "negative", "medium", "Weather disruption: Northeast/Newark throughput fell across pharma and electronics during Jan-Feb 2023.")
        if grain == "monthly" and dt in set(pd.to_datetime(["2023-01-31", "2023-02-28"])):
            return (0.76, "C1", "weather_disruption", "negative", "medium", "Weather disruption: Northeast/Newark throughput fell across pharma and electronics in Jan-Feb 2023.")

    if (region == "Midwest" and state == "IL" and port_code == "CHI" and hs2 == "84"):
        if grain == "weekly" and pd.Timestamp("2021-07-04") <= dt <= pd.Timestamp("2021-08-29"):
            return (1.23, "D1", "rebound", "positive", "medium", "Supply normalization rebound: Midwest Chicago machinery volumes recovered in Jul-Aug 2021.")
        if grain == "monthly" and dt in set(pd.to_datetime(["2021-07-31", "2021-08-31"])):
            return (1.20, "D1", "rebound", "positive", "medium", "Supply normalization rebound: Midwest Chicago machinery volumes recovered in Jul-Aug 2021.")

    if (flow == "exports" and region == "Midwest" and state == "MI" and hs4 == "8708"):
        if grain == "weekly" and pd.Timestamp("2020-03-29") <= dt <= pd.Timestamp("2020-05-31"):
            return (0.63, "E1", "shutdown", "negative", "high", "Manufacturing shutdown: Michigan export auto parts volumes fell materially in spring 2020.")
        if grain == "monthly" and dt in set(pd.to_datetime(["2020-03-31", "2020-04-30", "2020-05-31"])):
            return (0.68, "E1", "shutdown", "negative", "high", "Manufacturing shutdown: Michigan export auto parts volumes fell materially in spring 2020.")

    if (flow == "imports" and region == "South" and state == "FL" and hs2 == "39"):
        if grain == "weekly" and pd.Timestamp("2025-02-02") <= dt <= pd.Timestamp("2025-04-27"):
            return (1.18, "F1", "demand_shift", "positive", "medium", "Packaging demand shift: Florida plastics imports increased in spring 2025.")
        if grain == "monthly" and dt in set(pd.to_datetime(["2025-02-28", "2025-03-31", "2025-04-30"])):
            return (1.15, "F1", "demand_shift", "positive", "medium", "Packaging demand shift: Florida plastics imports increased in spring 2025.")

    return (1.0, "", "", "", "", "")

for grain, dates in [("weekly", weekly_dates), ("monthly", monthly_dates)]:
    for flow in flows:
        for region, states in regions_states.items():
            for state, state_name in states:
                for port_code, port_name in state_ports[state]:
                    for hs2, (hs2_name, hs4_list) in hs_map.items():
                        for hs4, hs4_name in hs4_list:
                            for dt in dates:
                                base = baseline_value(flow, region, state, port_code, hs2, hs4, dt, grain)
                                noise = rng.normal(1.0, 0.045 if grain == "monthly" else 0.06)
                                anomaly_mult, scenario_id, anomaly_type, anomaly_direction, severity, insight = anomaly_for_row(
                                    flow, region, state, port_code, hs2, hs4, dt, grain
                                )
                                value = max(10_000, base * noise * anomaly_mult)
                                volume = max(1, volume_from_value(value, hs2) * rng.normal(1.0, 0.04))
                                rows.append({
                                    "grain": grain,
                                    "period_end": dt.date().isoformat(),
                                    "flow": flow,
                                    "region": region,
                                    "state": state,
                                    "state_name": state_name,
                                    "port_code": port_code,
                                    "port_name": port_name,
                                    "hs2": hs2,
                                    "hs2_name": hs2_name,
                                    "hs4": hs4,
                                    "hs4_name": hs4_name,
                                    "trade_value_usd": round(value, 2),
                                    "volume_units": round(volume, 2),
                                    "anomaly_flag": 1 if scenario_id else 0,
                                    "scenario_id": scenario_id,
                                    "anomaly_type": anomaly_type,
                                    "anomaly_direction": anomaly_direction,
                                    "anomaly_severity": severity,
                                    "ground_truth_insight": insight,
                                })

df = pd.DataFrame(rows)
df["hierarchy_path"] = (
    df["flow"] + " > " + df["region"] + " > " + df["state"] + " > " + df["port_code"] +
    " > " + df["hs2"] + " > " + df["hs4"]
)
df["hierarchy_depth"] = 6
df["year"] = pd.to_datetime(df["period_end"]).dt.year
df["month"] = pd.to_datetime(df["period_end"]).dt.month
iso = pd.to_datetime(df["period_end"]).dt.isocalendar()
df["iso_week"] = iso.week.astype(int)
df = df.sort_values(
    ["grain", "period_end", "flow", "region", "state", "port_code", "hs2", "hs4"]
).reset_index(drop=True)

out_dir = Path("/data/data-analyst-agent/data/synthetic")
out_dir.mkdir(parents=True, exist_ok=True)
main_path = out_dir / "synthetic_hierarchical_trade_dataset_250k.csv"
df.to_csv(main_path, index=False)

scenario_summary = (
    df[df["anomaly_flag"] == 1]
    .groupby(["scenario_id", "grain", "anomaly_type", "anomaly_direction", "anomaly_severity", "ground_truth_insight"], as_index=False)
    .agg(
        rows_impacted=("anomaly_flag", "size"),
        first_period=("period_end", "min"),
        last_period=("period_end", "max"),
        total_trade_value_usd=("trade_value_usd", "sum"),
    )
    .sort_values(["scenario_id", "grain"])
)
summary_path = out_dir / "synthetic_hierarchical_trade_dataset_ground_truth_summary.csv"
scenario_summary.to_csv(summary_path, index=False)

meta = f"""Synthetic hierarchical trade dataset
Rows: {len(df):,}
Main file: {main_path.name}
Companion summary: {summary_path.name}

Hierarchy (6 levels):
flow -> region -> state -> port_code -> hs2 -> hs4

Cadence:
- weekly
- monthly

Embedded anomaly scenarios:
- A1 tariff-style semiconductor import shock
- B1 energy export surge
- C1 weather disruption
- D1 machinery rebound
- E1 manufacturing shutdown
- F1 packaging demand shift
"""
meta_path = out_dir / "synthetic_hierarchical_trade_dataset_README.txt"
meta_path.write_text(meta)

print({
    "rows": len(df),
    "main_file": str(main_path),
    "summary_file": str(summary_path),
    "readme": str(meta_path),
    "anomaly_rows": int(df["anomaly_flag"].sum()),
})
