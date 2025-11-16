import yaml
import pandas as pd
import datetime as dt
import sys
import os

# Add the parent directory to the path so we can import rostering
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rostering.models import ProblemInput, Person, Config, ConstraintWeights
from rostering.sequential_solver import SequentialSolver

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

print(f"Testing COMET + Unit Nights for {len(people)} people over {(config.end_date - config.start_date).days + 1} days...")

solver = SequentialSolver(problem, historical_comet_counts=None)

# Step 1: Solve COMET nights
print("\n" + "="*80)
print("STEP 1: COMET NIGHTS")
print("="*80)
comet_result = solver.solve_stage("comet_nights", timeout_seconds=60)

if comet_result.success:
    print(f"✅ COMET stage: {comet_result.message}")
    
    # Step 2: Solve Unit nights  
    print("\n" + "="*80)
    print("STEP 2: UNIT NIGHTS")
    print("="*80)
    nights_result = solver.solve_stage("nights", timeout_seconds=60)
    
    if nights_result.success:
        print(f"✅ Unit nights stage: {nights_result.message}")
        
        # Display combined analysis
        print("\n" + "="*80)
        print("COMBINED COMET + UNIT NIGHTS ANALYSIS")
        print("="*80)
        
        # Count night assignments for each person
        night_assignments = {}
        for person in people:
            night_assignments[person.name] = {
                'comet_nights': 0,
                'unit_nights': 0,
                'total_nights': 0
            }
        
        # Count assignments from final roster
        for day_str, day_assignments in solver.partial_roster.items():
            for person_id, shift in day_assignments.items():
                person = next(p for p in people if p.id == person_id)
                if shift == 'CMN':
                    night_assignments[person.name]['comet_nights'] += 1
                elif shift == 'N_REG':
                    night_assignments[person.name]['unit_nights'] += 1
        
        # Calculate totals
        for name in night_assignments:
            counts = night_assignments[name]
            counts['total_nights'] = counts['comet_nights'] + counts['unit_nights']
        
        print("\nCombined night shift assignments:")
        print("Doctor                | COMET | Unit  | Total | Grade")
        print("---------------------|-------|-------|-------|--------")
        for person in people:
            name = person.name
            counts = night_assignments[name]
            print(f"{name:20} | {counts['comet_nights']:5} | {counts['unit_nights']:5} | {counts['total_nights']:5} | {person.grade}")
            
        # Summary stats
        total_comet = sum(counts['comet_nights'] for counts in night_assignments.values())
        total_unit = sum(counts['unit_nights'] for counts in night_assignments.values())
        total_nights = total_comet + total_unit
        
        print("\nSummary:")
        print(f"  Total COMET nights assigned: {total_comet}")
        print(f"  Total Unit nights assigned: {total_unit}")
        print(f"  Total night shifts assigned: {total_nights}")
        print(f"  Expected total nights: {(config.end_date - config.start_date).days + 1}")
        
    else:
        print(f"❌ Unit nights stage failed: {nights_result.message}")
        
else:
    print(f"❌ COMET stage failed: {comet_result.message}")