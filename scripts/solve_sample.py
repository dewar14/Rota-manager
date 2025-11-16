import yaml, pandas as pd, datetime as dt, sys, os

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

# Test new sequential solver with cumulative fairness
print(f"Solving roster for {len(people)} people over {(config.end_date - config.start_date).days + 1} days...")

solver = SequentialSolver(problem, historical_comet_counts=None)
result = solver.solve_stage("comet", timeout_seconds=60)

if result.success:
    print(f"COMET stage: {result.message}")
    
    # Count assignments by person
    comet_assignments = {}
    for person in people:
        if person.comet_eligible:
            comet_assignments[person.name] = {"cmd": 0, "cmn": 0}
    
    for day_str, assignments in result.partial_roster.items():
        for person_id, shift in assignments.items():
            person_name = next((p.name for p in people if p.id == person_id), person_id)
            if shift == 'CMD':
                comet_assignments[person_name]["cmd"] += 1
            elif shift == 'CMN':
                comet_assignments[person_name]["cmn"] += 1
    
    print("\nCOMET assignments with new fairness system:")
    for name, counts in comet_assignments.items():
        total = counts["cmd"] + counts["cmn"]
        print(f"  {name}: {counts['cmd']} CMD + {counts['cmn']} CMN = {total} total")
    
    # Continue to Unit Nights stage
    print("\n==================================================")
    print("STEP 2: UNIT NIGHT ASSIGNMENTS")
    print("==================================================\n")
    unit_result = solver.solve_stage("nights", timeout_seconds=180)
    
    if unit_result.success:
        print(f"\nUnit Nights stage: {unit_result.message}")
    else:
        print(f"\nUnit Nights stage failed: {unit_result.message}")
else:
    print(f"COMET stage failed: {result.message}")

