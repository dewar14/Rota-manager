#!/usr/bin/env python3
"""Test script to run full sequential solver and check for constraint violations."""

import yaml, pandas as pd, datetime as dt, sys, os

# Add the parent directory to the path so we can import rostering
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rostering.models import ProblemInput, Person, Config, ConstraintWeights, ShiftType
from rostering.sequential_solver import SequentialSolver

# Load config
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

problem = ProblemInput(people=people, config=config, weights=ConstraintWeights())

print(f"Solving roster for {len(people)} people over {(config.end_date - config.start_date).days + 1} days...")
print("Running full sequential solver...")

solver = SequentialSolver(problem, historical_comet_counts=None)

# Run all stages
stages = ["comet", "nights", "weekend_holidays", "weekday_long_days", "short_days"]
all_success = True

for stage in stages:
    result = solver.solve_stage(stage, timeout_seconds=60)
    if result.success:
        print(f"✓ {stage.upper()} stage completed: {result.message}")
    else:
        print(f"✗ {stage.upper()} stage failed: {result.message}")
        all_success = False
        break

if all_success:
    # Get final roster and check for constraint violations
    final_roster = solver.partial_roster
    
    print("\nChecking for constraint violations...")
    
    # Check night-to-day violations
    night_shifts = [ShiftType.NIGHT_REG.value, ShiftType.NIGHT_SHO.value, ShiftType.COMET_NIGHT.value]
    working_shifts = [s.value for s in ShiftType if s not in [ShiftType.OFF, ShiftType.LTFT]]
    
    violations = []
    
    # Build person name mapping
    person_names = {p.id: p.name for p in people}
    
    # Convert roster to list of dates for checking
    dates = sorted(final_roster.keys())
    
    for i, date in enumerate(dates[:-2]):  # Check all but last 2 days
        for person_id, shift in final_roster[date].items():
            if shift in night_shifts:
                # Check next 2 days for working shifts (should be OFF)
                for j in range(1, 3):
                    if i + j < len(dates):
                        next_date = dates[i + j]
                        next_shift = final_roster[next_date][person_id]
                        if next_shift in working_shifts and next_shift != ShiftType.OFF.value:
                            violations.append({
                                'person': person_names.get(person_id, person_id),
                                'night_date': date,
                                'night_shift': shift,
                                'work_date': next_date,
                                'work_shift': next_shift,
                                'days_apart': j
                            })
    
    if violations:
        print(f"\n❌ Found {len(violations)} night rest violations:")
        for v in violations:
            print(f"  {v['person']}: {v['night_shift']} on {v['night_date']} followed by {v['work_shift']} on {v['work_date']} ({v['days_apart']} day{'s' if v['days_apart'] > 1 else ''} later)")
    else:
        print("✅ No night rest violations found!")
    
    # Save the full roster
    os.makedirs("out", exist_ok=True)
    df_roster = pd.DataFrame(final_roster).T
    df_roster.to_csv("out/full_roster.csv")
    print(f"\nFull roster saved to out/full_roster.csv")
    
else:
    print("Sequential solve failed, cannot check constraints.")