#!/usr/bin/env python3
"""
Test script to demonstrate the checkpoint functionality in the sequential solver.
"""

import yaml
from rostering.models import ProblemInput
from rostering.sequential_solver import SequentialSolver


def test_checkpoints():
    """Test the sequential solver with checkpoints between stages."""
    
    # Load config same way as test_full_solve.py
    with open("data/sample_config.yml") as f:
        cfg = yaml.safe_load(f)

    import pandas as pd
    import datetime as dt
    from rostering.models import Config, Person, ConstraintWeights
    
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
        if not pd.isna(r.get("start_date")):
            sd = dt.date.fromisoformat(str(r["start_date"])[:10])
        ed = None
        if not pd.isna(r.get("end_date")):
            ed = dt.date.fromisoformat(str(r["end_date"])[:10])
            
        people.append(Person(
            id=r["id"],
            name=r["name"],
            grade=r["grade"],
            wte=r["wte"],
            comet_eligible=r.get("comet_eligible", False),
            start_date=sd,
            end_date=ed
        ))

    # Create problem
    problem = ProblemInput(
        people=people,
        config=config,
        constraint_weights=ConstraintWeights()
    )
    
    print("Testing Sequential Solver with Checkpoints")
    print("=" * 50)
    print(f"Roster period: {problem.config.start_date} to {problem.config.end_date}")
    print(f"Number of people: {len(problem.people)}")
    print(f"COMET weeks: {len(problem.config.comet_on_weeks)}")
    
    # Create solver
    solver = SequentialSolver(problem)
    
    print("\nStarting solve with checkpoints...")
    print("You will be prompted to review each stage before continuing.")
    print("Options at each checkpoint:")
    print("  y = Continue to next stage")
    print("  n = Pause and exit (can resume later)")
    print("  q = Quit completely")
    
    # Solve with checkpoints
    result = solver.solve_with_checkpoints(timeout_per_stage=300, auto_continue=False)
    
    print("\nFinal Result:")
    print(f"  Stage: {result.stage}")
    print(f"  Success: {result.success}")
    print(f"  Message: {result.message}")
    
    if hasattr(result, 'next_stage') and result.next_stage:
        print(f"  Next stage: {result.next_stage}")
        print(f"\nTo resume, use: solver.solve_stage('{result.next_stage}')")


def test_auto_continue():
    """Test the sequential solver with auto-continue (no user prompts)."""
    
    # Load config same way as test_full_solve.py
    with open("data/sample_config.yml") as f:
        cfg = yaml.safe_load(f)

    import pandas as pd
    import datetime as dt
    from rostering.models import Config, Person, ConstraintWeights
    
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
        if not pd.isna(r.get("start_date")):
            sd = dt.date.fromisoformat(str(r["start_date"])[:10])
        ed = None
        if not pd.isna(r.get("end_date")):
            ed = dt.date.fromisoformat(str(r["end_date"])[:10])
            
        people.append(Person(
            id=r["id"],
            name=r["name"],
            grade=r["grade"],
            wte=r["wte"],
            comet_eligible=r.get("comet_eligible", False),
            start_date=sd,
            end_date=ed
        ))

    # Create problem
    problem = ProblemInput(
        people=people,
        config=config,
        constraint_weights=ConstraintWeights()
    )
    
    print("\n" + "=" * 50)
    print("Testing Sequential Solver with Auto-Continue")
    print("=" * 50)
    
    # Create solver
    solver = SequentialSolver(problem)
    
    # Solve with auto-continue (no prompts)
    result = solver.solve_with_checkpoints(timeout_per_stage=300, auto_continue=True)
    
    print("\nFinal Result:")
    print(f"  Stage: {result.stage}")
    print(f"  Success: {result.success}")
    print(f"  Message: {result.message}")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--auto":
        test_auto_continue()
    else:
        test_checkpoints()