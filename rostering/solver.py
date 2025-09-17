from ortools.sat.python import cp_model
from typing import Dict
import pandas as pd
import datetime as dt
from rostering.models import ProblemInput, SolveResult
from rostering.constraints import add_core_constraints, soft_objective

def solve_roster(problem: ProblemInput) -> SolveResult:
    model = cp_model.CpModel()
    x, locums, days, people = add_core_constraints(problem, model)
    soft_objective(problem, model, x, locums, days, people)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 20.0
    solver.parameters.num_search_workers = 8
    res = solver.Solve(model)

    if res not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return SolveResult(success=False, message="No feasible solution", roster={}, breaches={}, summary={})

    # Build roster table
    roster: Dict[str, Dict[str, str]] = {}
    for d_idx, day in enumerate(days):
        dkey = day.isoformat()
        roster[dkey] = {}
        for p_idx, person in enumerate(people):
            code = "OFF"
            for s in ["SD","LD","N","CMD","CMN","CPD","TREG","TSHO","TPCCU","IND"]:
                if solver.Value(x[p_idx,d_idx,s]) == 1:
                    code = s
            roster[dkey][person.id] = code

    # Simple summaries
    summary = {}
    # Count locums
    locum_total = 0
    for arr in locums.values():
        locum_total += sum(int(solver.Value(v)) for v in arr)
    summary["locum_slots"] = float(locum_total)

    # Save CSV wide
    df = pd.DataFrame(roster).T
    out_dir = "out"
    import os
    os.makedirs(out_dir, exist_ok=True)
    df.to_csv(f"{out_dir}/roster.csv")
    # Breaches placeholder
    breaches = {"note":"Detailed breach accounting to be added incrementally."}

    # Write summaries
    import json
    with open(f"{out_dir}/summary.json","w") as f:
        json.dump(summary, f, indent=2)
    with open(f"{out_dir}/breaches.json","w") as f:
        json.dump(breaches, f, indent=2)

    return SolveResult(success=True, message="Solved", roster=roster, breaches=breaches, summary=summary)
