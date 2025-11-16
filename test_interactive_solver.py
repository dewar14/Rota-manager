#!/usr/bin/env python3
"""
Interactive Solver Test - Demonstrates the new checkpoint and continue functionality.

This script shows how to use the enhanced sequential solver with:
- Interactive checkpoints between stages
- Detailed statistics and violation checking
- Resume functionality for paused sessions
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
    print("🚀 Interactive Sequential Solver Demo")
    print("="*50)
    
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
    
    print("\n" + "="*50)
    print("INTERACTIVE SOLVER OPTIONS:")
    print("="*50)
    print()
    print("1. [auto] - Run all stages automatically (no checkpoints)")
    print("2. [interactive] - Run with interactive checkpoints")
    print("3. [stage] - Run a specific stage only")
    print("4. [resume] - Resume from a specific stage")
    print()
    
    while True:
        choice = input("Choose an option [auto/interactive/stage/resume]: ").strip().lower()
        
        if choice in ['auto', 'a']:
            print("\n🚀 Running all stages automatically...")
            result = solver.solve_with_checkpoints(timeout_per_stage=300, auto_continue=True)
            break
            
        elif choice in ['interactive', 'i']:
            print("\n🛑 Running with interactive checkpoints...")
            print("You'll be prompted between each stage to continue, pause, or review.")
            result = solver.solve_with_checkpoints(timeout_per_stage=300, auto_continue=False)
            break
            
        elif choice in ['stage', 's']:
            stages = ["comet_nights", "nights", "weekend_holidays", "comet_days", "weekday_long_days", "short_days"]
            print(f"\nAvailable stages: {', '.join(stages)}")
            stage_name = input("Which stage to run? ").strip().lower()
            
            if stage_name in stages:
                print(f"\n🎯 Running stage: {stage_name}")
                result = solver.solve_stage(stage_name, timeout_seconds=300)
                break
            else:
                print("Invalid stage name. Please try again.")
                continue
                
        elif choice in ['resume', 'r']:
            stages = ["comet_nights", "nights", "weekend_holidays", "comet_days", "weekday_long_days", "short_days"]
            print(f"\nAvailable stages: {', '.join(stages)}")
            stage_name = input("Resume from which stage? ").strip().lower()
            
            if stage_name in stages:
                print(f"\n🔄 Resuming from stage: {stage_name}")
                result = solver.resume_from_stage(stage_name, timeout_per_stage=300)
                break
            else:
                print("Invalid stage name. Please try again.")
                continue
                
        else:
            print("Invalid choice. Please choose auto, interactive, stage, or resume.")
    
    # Show final results
    print("\n" + "="*50)
    print("FINAL RESULTS")
    print("="*50)
    
    if result.success:
        print(f"✅ Success: {result.message}")
        
        # Show basic statistics
        stats = solver.get_roster_statistics()
        print(f"\n📊 Final Statistics:")
        print(f"   Total shifts assigned: {stats['total_assigned']}")
        print(f"   Days covered: {stats['days_covered']}")
        print(f"   Coverage: {(stats['days_covered']/len(solver.days)*100):.1f}%")
        
        # Show next stage if paused
        if hasattr(result, 'next_stage') and result.next_stage:
            print(f"\n▶️  Next stage ready: {result.next_stage}")
            print(f"   To resume: solver.resume_from_stage('{result.next_stage}')")
            
    else:
        print(f"❌ Failed: {result.message}")
    
    print(f"\nStage completed: {result.stage}")
    print("\n🎉 Demo completed!")

if __name__ == "__main__":
    main()