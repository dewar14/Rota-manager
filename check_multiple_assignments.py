#!/usr/bin/env python3
"""
Check for multiple assignments bug in the COMET solver
"""

import yaml, pandas as pd, datetime as dt, sys, os

# Add the parent directory to the path so we can import rostering
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from rostering.models import ProblemInput, Person, Config, ConstraintWeights
from rostering.sequential_solver import SequentialSolver

# Load data (same as solve_sample.py)
with open('data/sample_config.yml') as f:
    cfg = yaml.safe_load(f)
config = Config(
    start_date=dt.date.fromisoformat(str(cfg['start_date'])[:10]),
    end_date=dt.date.fromisoformat(str(cfg['end_date'])[:10]),
    bank_holidays=[dt.date.fromisoformat(str(d)[:10]) for d in cfg.get('bank_holidays',[])],
    comet_on_weeks=[dt.date.fromisoformat(str(d)[:10]) for d in cfg.get('comet_on_weeks',[])],
    max_day_clinicians=cfg.get('max_day_clinicians',5),
    ideal_weekday_day_clinicians=cfg.get('ideal_weekday_day_clinicians',4),
    min_weekday_day_clinicians=cfg.get('min_weekday_day_clinicians',3),
)

df = pd.read_csv('data/sample_people.csv')
people = []
for _,r in df.iterrows():
    sd = None
    if isinstance(r.get('start_date'), str) and r.get('start_date'):
        sd = dt.date.fromisoformat(r['start_date'])
    fdo = None
    if not pd.isna(r.get('fixed_day_off')):
        try:
            fdo = int(r['fixed_day_off'])
        except Exception:
            fdo = None
    people.append(Person(
        id=r['id'], name=r['name'], grade=r['grade'],
        wte=float(r['wte']), fixed_day_off=fdo,
        comet_eligible=bool(r['comet_eligible']) if str(r['comet_eligible']).lower() not in ['true','false'] else str(r['comet_eligible']).lower()=='true',
        start_date=sd
    ))

problem = ProblemInput(people=people, config=config, weights=ConstraintWeights())

print(f"Solving roster for {len(people)} people over {(config.end_date - config.start_date).days + 1} days...")

# Run solver with reduced output
solver = SequentialSolver(problem, historical_comet_counts=None)

# Disable verbose output for main run
import sys
class SuppressOutput:
    def __enter__(self):
        self._original_stdout = sys.stdout
        sys.stdout = open(os.devnull, 'w')
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout.close()
        sys.stdout = self._original_stdout

print("Running COMET solver (output suppressed)...")
with SuppressOutput():
    result = solver.solve_stage('comet', timeout_seconds=30)

print(f"Result: {result.success}, {result.message}")

# Check specific days that showed issues in previous output
test_days = ['2026-01-08', '2026-01-09', '2026-01-10', '2026-01-06', '2026-01-07']
print('\nFinal roster state for days that showed potential conflicts:')
conflicts_found = False

for day in test_days:
    if day in solver.partial_roster:
        assignments = solver.partial_roster[day]
        comet_assignments = [pid for pid, assignment in assignments.items() if assignment == 'CMN']
        comet_count = len(comet_assignments)
        
        if comet_count > 1:
            print(f'{day}: 🚨 {comet_count} COMET nights -> {comet_assignments}')
            conflicts_found = True
        elif comet_count == 1:
            print(f'{day}: ✅ 1 COMET night -> {comet_assignments[0]}')
        else:
            print(f'{day}: ⭕ No COMET coverage')

if conflicts_found:
    print("\n🚨 MULTIPLE ASSIGNMENT BUG CONFIRMED!")
else:
    print("\n✅ No multiple assignment conflicts detected")

# Also count total COMET assignments per person
print("\nCOMET assignment summary:")
comet_totals = {}
for day_assignments in solver.partial_roster.values():
    for person_id, assignment in day_assignments.items():
        if assignment == 'CMN':
            comet_totals[person_id] = comet_totals.get(person_id, 0) + 1

for person_id, count in comet_totals.items():
    person_name = next(p.name for p in people if p.id == person_id)
    print(f"  {person_id} ({person_name}): {count} COMET nights")