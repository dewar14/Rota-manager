#!/usr/bin/env python3
"""
Interactive Solver Demo - Run this directly in terminal for proper interactive experience
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
    print("🚀 Interactive Sequential Solver - Terminal Mode")
    print("="*60)
    print("This version supports proper interactive control with pause/continue")
    print("="*60)
    
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
    
    print(f"\nConfigured for {len(people)} people over {len(solver.days)} days")
    print(f"Period: {config.start_date} to {config.end_date}")
    print(f"COMET weeks: {len(config.comet_on_weeks)}")
    
    print("\n" + "="*60)
    print("INTERACTIVE MODE - You can pause between stages for review")
    print("="*60)

    # Run solver with interactive checkpoints
    try:
        result = solver.solve_with_checkpoints(timeout_per_stage=300, auto_continue=False)
        
        if result.success:
            print("\n🎉 Solver completed successfully!")
        else:
            print(f"\n❌ Solver failed: {result.message}")
            
    except KeyboardInterrupt:
        print("\n\n⏹️ Solver interrupted by user")
    except EOFError:
        print("\n\n⚠️ Input stream closed - this script needs to run in an interactive terminal")
        print("💡 Try running: python interactive_solver_terminal.py")

if __name__ == "__main__":
    main()