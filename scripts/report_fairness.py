import json
import pandas as pd
import datetime as dt
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
OUT_DIR = Path(__file__).resolve().parents[1] / "out"

people_path = DATA_DIR / "people.json"
roster_path = OUT_DIR / "roster.csv"

if not roster_path.exists():
    raise SystemExit("out/roster.csv not found. Run a solve first.")
if not people_path.exists():
    raise SystemExit("data/people.json not found.")

df = pd.read_csv(roster_path, index_col=0)
with open(people_path) as f:
    people = {p["id"]: p for p in json.load(f)}

# Horizon dates from roster index
dates = [dt.date.fromisoformat(str(d)) for d in df.index]
start_date, end_date = dates[0], dates[-1]
days_count = len(dates)

def group_ids(grade: str):
    return [pid for pid, p in people.items() if p.get("grade") == grade]

sho_ids = group_ids("SHO")
reg_ids = group_ids("Registrar")

def ld_n_counts(pid: str):
    if pid not in df.columns:
        return 0, 0
    col = df[pid].astype(str)
    grade = people[pid].get("grade")
    if grade == "SHO":
        ld = int((col == "LDS").sum())
        n = int((col == "NS").sum())
    elif grade == "Registrar":
        ld = int(((col == "LDR") | (col == "CMD")).sum())
        n = int(((col == "NR") | (col == "CMN")).sum())
    else:
        ld = int(((col == "LDR") | (col == "LDS") | (col == "CMD")).sum())
        n = int(((col == "NR") | (col == "NS") | (col == "CMN")).sum())
    return ld, n

def active_days_for(pid: str):
    sd = people[pid].get("start_date")
    if sd:
        try:
            sd = dt.date.fromisoformat(sd)
        except Exception:
            sd = start_date
    else:
        sd = start_date
    return sum(1 for d in dates if d >= sd)

def proportional_targets(ids):
    # Total cover for LD and N per grade = number of days in horizon
    total_cover = days_count
    # Weights = WTE * active_days
    weights = []
    for pid in ids:
        wte = float(people[pid].get("wte") or 1.0)
        wte = max(0.2, min(1.0, wte))
        weights.append(wte * active_days_for(pid))
    denom = sum(weights) or 1.0
    targets = {pid: (total_cover * (weights[i] / denom)) for i, pid in enumerate(ids)}
    return targets

def report_for(ids, label):
    targets_ld = proportional_targets(ids)
    targets_n = proportional_targets(ids)
    rows = []
    for pid in ids:
        ld, n = ld_n_counts(pid)
        t_ld = targets_ld[pid]
        t_n = targets_n[pid]
        var_ld = 0.0 if t_ld == 0 else (ld - t_ld) / t_ld
        var_n = 0.0 if t_n == 0 else (n - t_n) / t_n
        rows.append({
            "id": pid,
            "name": people[pid]["name"],
            "wte": people[pid].get("wte", 1.0),
            "active_days": active_days_for(pid),
            "LD_actual": ld,
            "LD_target": round(t_ld, 2),
            "LD_variance_pct": round(var_ld * 100, 1),
            "N_actual": n,
            "N_target": round(t_n, 2),
            "N_variance_pct": round(var_n * 100, 1),
            "LD_within_15pct": abs(var_ld) <= 0.15,
            "N_within_15pct": abs(var_n) <= 0.15,
        })
    table = pd.DataFrame(rows).sort_values("id")
    print(f"\n=== {label} Fairness (±15%) {start_date}..{end_date} ===")
    print(table.to_string(index=False))
    # Quick summary
    ok_ld = table["LD_within_15pct"].mean()*100
    ok_n = table["N_within_15pct"].mean()*100
    print(f"{label}: LD within 15%: {ok_ld:.1f}%  |  N within 15%: {ok_n:.1f}%")

if sho_ids:
    report_for(sho_ids, "SHO")
if reg_ids:
    report_for(reg_ids, "Registrar")
