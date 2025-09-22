#!/usr/bin/env python3
"""Test the main solve_roster function directly"""

import yaml
import pandas as pd
import datetime as dt
from rostering.models import ProblemInput, Person, Config, Weights
from rostering.solver import _solve

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

weights = Weights(locum=10000)
problem = ProblemInput(people=people, config=config, weights=weights)

print("Testing _solve function...")
res, solver, x, locums, days, people = _solve(problem)

print(f"Solver result: {res}")
if res in (2, 4):  # OPTIMAL or FEASIBLE
    locum_total = sum(int(solver.Value(v)) for arr in locums.values() for v in arr if hasattr(v, '__iter__') == False)
    print(f"Total locums: {locum_total}")
    
    # Show a sample of assignments
    print("\nSample assignments (first 3 days):")
    for d_idx in range(min(3, len(days))):
        day = days[d_idx]
        print(f"{day}: ", end="")
        assignments = []
        for p_idx, person in enumerate(people):
            for shift in ["SD", "LD", "N", "CMD", "CMN"]:
                if solver.Value(x[p_idx, d_idx, shift]) == 1:
                    assignments.append(f"{person.id}:{shift}")
        print(", ".join(assignments) if assignments else "No assignments")
else:
    print("Solver failed")