#!/usr/bin/env python3
"""Debug with sample configuration"""

import yaml
import pandas as pd
import datetime as dt
from rostering.models import ProblemInput, Person, Config, Weights
from rostering.constraints import add_core_constraints, soft_objective
from ortools.sat.python import cp_model

# Load sample configuration
with open("data/sample_config.yml") as f:
    cfg = yaml.safe_load(f)

config = Config(
    start_date=dt.date.fromisoformat(str(cfg["start_date"])[:10]),
    end_date=dt.date.fromisoformat(str(cfg["end_date"])[:10]),
    bank_holidays=[dt.date.fromisoformat(str(d)[:10]) for d in cfg.get("bank_holidays",[])],
    comet_on_weeks=[dt.date.fromisoformat(str(d)[:10]) for d in cfg.get("comet_on_weeks",[])],
)

# Load people
df = pd.read_csv("data/sample_people.csv")
people = []
for _,r in df.iterrows():
    sd = None
    if isinstance(r.get("start_date"), str) and r.get("start_date"):
        sd = dt.date.fromisoformat(r["start_date"])
    fdo = None
    if not pd.isna(r.get("fixed_day_off")):
        try:
            fdo = int(r["fixed_day_off"])
        except Exception:
            fdo = None
    people.append(Person(
        id=r["id"], name=r["name"], grade=r["grade"],
        wte=float(r["wte"]), fixed_day_off=fdo,
        comet_eligible=bool(r["comet_eligible"]) if str(r["comet_eligible"]).lower() not in ["true","false"] else str(r["comet_eligible"]).lower()=="true",
        start_date=sd
    ))

print(f"People: {[p.id + ':' + p.grade for p in people]}")
print(f"Date range: {config.start_date} to {config.end_date} ({(config.end_date - config.start_date).days + 1} days)")
print(f"COMET weeks: {config.comet_on_weeks}")

# Use improved weights
weights = Weights(locum=10000)

problem = ProblemInput(people=people, config=config, weights=weights)

print("\nTesting with sample configuration...")

# Test Pass 1: nights-only
print("Testing Pass 1 (nights only)...")
model1 = cp_model.CpModel()
x1, locums1, days, people = add_core_constraints(problem, model1, options={"nights_only": True})
soft_objective(problem, model1, x1, locums1, days, people, options={"nights_only": True})
solver1 = cp_model.CpSolver()
solver1.parameters.max_time_in_seconds = 60.0
solver1.parameters.num_search_workers = 8
solver1_res = solver1.Solve(model1)

print(f"Pass 1 result: {solver1_res}")
if solver1_res == cp_model.INFEASIBLE:
    print("Pass 1 is infeasible")
else:
    print("Pass 1 successful")
    locum_total_1 = sum(int(solver1.Value(v)) for k in ["loc_n_sho", "loc_n_reg", "loc_cmn"] for v in locums1[k])
    print(f"Locums needed in Pass 1: {locum_total_1}")

# Test Pass 2: full constraints
print("\nTesting Pass 2 (full constraints)...")
model2 = cp_model.CpModel()
x2, locums2, days, people = add_core_constraints(problem, model2, options={})
soft_objective(problem, model2, x2, locums2, days, people, options={})
solver2 = cp_model.CpSolver()
solver2.parameters.max_time_in_seconds = 180.0  # More time
solver2.parameters.num_search_workers = 8
solver2_res = solver2.Solve(model2)

print(f"Pass 2 result: {solver2_res}")
if solver2_res == cp_model.INFEASIBLE:
    print("Pass 2 is infeasible")
else:
    print("Pass 2 successful")
    locum_total_2 = sum(int(solver2.Value(v)) for arr in locums2.values() for v in arr if hasattr(v, '__iter__') == False)
    print(f"Locums needed in Pass 2: {locum_total_2}")