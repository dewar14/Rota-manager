#!/usr/bin/env python3
"""Debug the constraint infeasibility"""

import datetime as dt
from rostering.models import ProblemInput, Person, Config, Weights
from rostering.constraints import add_core_constraints, soft_objective
from ortools.sat.python import cp_model

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

print("Testing constraint feasibility...")

# Test Pass 1: nights-only to stabilize night allocation
print("\nTesting Pass 1 (nights only)...")
model1 = cp_model.CpModel()
x1, locums1, days, people = add_core_constraints(problem, model1, options={"nights_only": True})
soft_objective(problem, model1, x1, locums1, days, people, options={"nights_only": True})
solver1 = cp_model.CpSolver()
solver1.parameters.max_time_in_seconds = 60.0
solver1.parameters.num_search_workers = 8
solver1_res = solver1.Solve(model1)

print(f"Pass 1 result: {solver1_res}")
if solver1_res == cp_model.INFEASIBLE:
    print("Pass 1 is infeasible - checking constraints")
elif solver1_res in (cp_model.OPTIMAL, cp_model.FEASIBLE):
    print("Pass 1 successful")
    # Show night assignments
    for d_idx, day in enumerate(days):
        print(f"{day}: ", end="")
        for p_idx, person in enumerate(people):
            if solver1.Value(x1[p_idx, d_idx, 'N']) == 1:
                print(f"{person.id}:N ", end="")
            if solver1.Value(x1[p_idx, d_idx, 'CMN']) == 1:
                print(f"{person.id}:CMN ", end="")
        # Check locums
        if solver1.Value(locums1["loc_n_reg"][d_idx]) > 0:
            print("LOCUM_REG_N ", end="")
        if solver1.Value(locums1["loc_n_sho"][d_idx]) > 0:
            print("LOCUM_SHO_N ", end="")
        if solver1.Value(locums1["loc_cmn"][d_idx]) > 0:
            print("LOCUM_CMN ", end="")
        print()

# Test Pass 2: full constraints  
print("\nTesting Pass 2 (full constraints)...")
model2 = cp_model.CpModel()
x2, locums2, days, people = add_core_constraints(problem, model2, options={})
soft_objective(problem, model2, x2, locums2, days, people, options={})
solver2 = cp_model.CpSolver()
solver2.parameters.max_time_in_seconds = 60.0
solver2.parameters.num_search_workers = 8
solver2_res = solver2.Solve(model2)

print(f"Pass 2 result: {solver2_res}")
if solver2_res == cp_model.INFEASIBLE:
    print("Pass 2 is infeasible")
elif solver2_res in (cp_model.OPTIMAL, cp_model.FEASIBLE):
    print("Pass 2 successful")
    locum_total = sum(int(solver2.Value(v)) for arr in locums2.values() for v in arr)
    print(f"Total locums needed: {locum_total}")