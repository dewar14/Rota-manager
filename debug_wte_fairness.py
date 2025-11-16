#!/usr/bin/env python3
"""
Debug WTE-adjusted fairness with verbose output
"""

import yaml
import datetime as dt
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from rostering.models import ProblemInput, Person, Config, ConstraintWeights
from rostering.sequential_solver import SequentialSolver

# Load minimal data for debugging
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

# Use only first 4 COMET eligible doctors for easier debugging
people = [
    Person(id='reg1', name='Mei Yi Goh', grade='Registrar', wte=0.8, comet_eligible=True),
    Person(id='reg2', name='David White', grade='Registrar', wte=0.8, comet_eligible=True),
    Person(id='reg6', name='Abdifatah Mohamud', grade='Registrar', wte=1.0, comet_eligible=True),
    Person(id='reg11', name='Sarah Walker', grade='Registrar', wte=0.6, comet_eligible=True)
]

problem = ProblemInput(people=people, config=config, weights=ConstraintWeights())

print('Testing WTE-adjusted fairness with 4 doctors:')
print('reg1: WTE 0.8, reg2: WTE 0.8, reg6: WTE 1.0, reg11: WTE 0.6')
print(f'Total WTE: {sum(p.wte for p in people)}')
print()

# Calculate expected distribution
total_wte = sum(p.wte for p in people)
total_nights = len(config.comet_on_weeks) * 7
print(f'Total COMET nights: {total_nights}')
for person in people:
    expected = (total_nights * person.wte) / total_wte
    print(f'{person.id}: Expected {expected:.1f} nights')

print()
print('Running solver (first 10 rounds only)...')

solver = SequentialSolver(problem, historical_comet_counts=None)

# Monkey patch to limit output
original_method = solver._assign_comet_night_blocks_sequentially
def limited_output(*args, **kwargs):
    print("Starting block assignment...")
    return original_method(*args, **kwargs)

solver._assign_comet_night_blocks_sequentially = limited_output

result = solver.solve_stage('comet', timeout_seconds=30)

print()
print('Final distribution:')
for person in people:
    count = sum(1 for day_assignments in solver.partial_roster.values() 
                for pid, assignment in day_assignments.items() 
                if pid == person.id and assignment == 'CMN')
    expected = (total_nights * person.wte) / total_wte
    deviation = count - expected
    print(f'{person.id}: {count} nights (expected {expected:.1f}, deviation {deviation:+.1f})')