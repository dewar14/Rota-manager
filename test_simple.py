#!/usr/bin/env python3
"""Simple test of rota solver with minimal constraints"""

import datetime as dt
from rostering.models import ProblemInput, Person, Config, Weights
from rostering.solver import solve_roster

# Create a simple 7-day problem with 4 people
people = [
    Person(id="r1", name="Registrar 1", grade="Registrar", wte=1.0, comet_eligible=True),
    Person(id="r2", name="Registrar 2", grade="Registrar", wte=1.0, comet_eligible=False),
    Person(id="s1", name="SHO 1", grade="SHO", wte=1.0),
    Person(id="s2", name="SHO 2", grade="SHO", wte=1.0),
]

config = Config(
    start_date=dt.date(2025, 2, 3),  # Monday
    end_date=dt.date(2025, 2, 9),    # Sunday (7 days)
    comet_on_weeks=[dt.date(2025, 2, 3)]  # Enable COMET this week
)

# Use default weights but with higher locum penalty
weights = Weights(locum=10000)

problem = ProblemInput(people=people, config=config, weights=weights)

print("Testing simple 7-day rota...")
result = solve_roster(problem)

print(f"Result: {result.message}")
print(f"Locum slots: {result.summary.get('locum_slots', 0)}")

if result.success:
    print("\nGenerated roster:")
    for date_str in sorted(result.roster.keys()):
        day_roster = result.roster[date_str]
        print(f"{date_str}: ", end="")
        for person_id, shift in day_roster.items():
            if not person_id.startswith("LOC_"):
                print(f"{person_id}:{shift}", end=" ")
        print()