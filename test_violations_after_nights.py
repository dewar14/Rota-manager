#!/usr/bin/env python3
"""
Test script to run until unit nights stage and examine constraint violations
"""

import yaml
import pandas as pd
import datetime as dt
import sys
import os

# Add the parent directory to the path so we can import rostering
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rostering.models import ProblemInput, Person, Config, ConstraintWeights
from rostering.sequential_solver import SequentialSolver

def main():
    print("🚀 Testing Unit Nights Violations")
    print("=" * 50)
    
    # Load configuration
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

    # Create problem input
    problem = ProblemInput(
        config=config,
        people=people,
        constraint_weights=ConstraintWeights()
    )

    # Create solver
    solver = SequentialSolver(problem)
    
    print(f"Configured for {len(people)} people over {len(solver.days)} days")
    print(f"Period: {config.start_date} to {config.end_date}")
    
    # Run COMET nights and unit nights only
    print("\n" + "=" * 80)
    print("STAGE 1: COMET NIGHTS")
    print("=" * 80)
    
    result = solver.solve_stage("comet_nights", timeout_seconds=300)
    if not result.success:
        print(f"❌ COMET nights failed: {result.message}")
        return
        
    print(f"✅ COMET nights completed: {result.message}")
    
    print("\n" + "=" * 80)
    print("STAGE 2: UNIT NIGHTS")  
    print("=" * 80)
    
    result = solver.solve_stage("nights", timeout_seconds=300)
    if not result.success:
        print(f"❌ Unit nights failed: {result.message}")
        return
        
    print(f"✅ Unit nights completed: {result.message}")
    
    # Now examine violations in detail
    print("\n" + "=" * 80)
    print("DETAILED CONSTRAINT VIOLATION ANALYSIS")
    print("=" * 80)
    
    solver._show_constraint_violations()
    
    print("\n" + "=" * 80)
    print("DETAILED ROSTER STATISTICS")
    print("=" * 80)
    
    solver._show_detailed_statistics()

if __name__ == "__main__":
    main()