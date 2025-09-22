#!/usr/bin/env python3
"""Debug exactly what solve_sample.py is doing"""

import yaml, pandas as pd, datetime as dt
import os, sys
# Ensure repository root is on sys.path when running as a script
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)
from rostering.models import ProblemInput, Person, Config, Weights

with open("data/sample_config.yml") as f:
    cfg = yaml.safe_load(f)
config = Config(
    start_date=dt.date.fromisoformat(str(cfg["start_date"])[:10]),
    end_date=dt.date.fromisoformat(str(cfg["end_date"])[:10]),
    bank_holidays=[dt.date.fromisoformat(str(d)[:10]) for d in cfg.get("bank_holidays",[])],
    comet_on_weeks=[dt.date.fromisoformat(str(d)[:10]) for d in cfg.get("comet_on_weeks",[])],
    max_day_clinicians=cfg.get("max_day_clinicians",5),
    ideal_weekday_day_clinicians=cfg.get("ideal_weekday_day_clinicians",4),
    min_weekday_day_clinicians=cfg.get("min_weekday_day_clinicians",3),
)

df = pd.read_csv("data/sample_people.csv")
print(f"CSV has {len(df)} rows")
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
    person = Person(
        id=r["id"], name=r["name"], grade=r["grade"],
        wte=float(r["wte"]), fixed_day_off=fdo,
        comet_eligible=bool(r["comet_eligible"]) if str(r["comet_eligible"]).lower() not in ["true","false"] else str(r["comet_eligible"]).lower()=="true",
        start_date=sd
    )
    people.append(person)
    print(f"Added person: {person.id} - {person.name} - {person.grade}")

print(f"\nFinal people count: {len(people)}")
problem = ProblemInput(people=people, config=config)

print(f"Problem people count: {len(problem.people)}")
print(f"People IDs: {[p.id for p in problem.people]}")

# Now test if something in solver is changing this
from rostering.solver import solve_roster
print("\nCalling solve_roster...")
res = solve_roster(problem)
print(f"Result message: {res.message}")
print(f"Roster keys (first few): {list(res.roster.keys())[:3] if res.roster else 'No roster'}")
if res.roster:
    first_date = list(res.roster.keys())[0]
    people_in_roster = [k for k in res.roster[first_date].keys() if not k.startswith('LOC_')]
    print(f"People in roster: {len(people_in_roster)}")
    print(f"Roster people IDs: {people_in_roster[:10]}...")  # First 10