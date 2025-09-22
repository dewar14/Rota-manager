from ortools.sat.python import cp_model
from typing import Dict
import pandas as pd
import datetime as dt
from rostering.models import ProblemInput, SolveResult
from rostering.constraints import add_core_constraints, soft_objective

def _solve(problem: ProblemInput):
    # Pass 1: nights-only to stabilize night allocation
    model1 = cp_model.CpModel()
    x1, locums1, days, people = add_core_constraints(problem, model1, options={"nights_only": True})
    soft_objective(problem, model1, x1, locums1, days, people, options={"nights_only": True})
    solver1 = cp_model.CpSolver()
    solver1.parameters.max_time_in_seconds = 60.0
    solver1.parameters.num_search_workers = 8
    solver1_res = solver1.Solve(model1)
    freeze = []
    if solver1_res in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for p_idx in range(len(people)):
            for d_idx in range(len(days)):
                if int(solver1.Value(x1[p_idx, d_idx, 'N'])) == 1:
                    freeze.append((p_idx, d_idx, 'N'))
                if int(solver1.Value(x1[p_idx, d_idx, 'CMN'])) == 1:
                    freeze.append((p_idx, d_idx, 'CMN'))
    # Pass 2: full objective with frozen nights
    model = cp_model.CpModel()
    x, locums, days, people = add_core_constraints(problem, model, options={"freeze_nights": freeze})
    soft_objective(problem, model, x, locums, days, people)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 120.0
    solver.parameters.num_search_workers = 8
    res = solver.Solve(model)
    return res, solver, x, locums, days, people

def solve_nights_only(problem: ProblemInput) -> SolveResult:
    model = cp_model.CpModel()
    x, locums, days, people = add_core_constraints(problem, model, options={"nights_only": True})
    soft_objective(problem, model, x, locums, days, people, options={"nights_only": True})
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 60.0
    solver.parameters.num_search_workers = 8
    res = solver.Solve(model)
    if res not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # Nights-only should be feasible with locum slack; return empty scaffold if not
        roster = {d.isoformat(): {p.id: "OFF" for p in people} for d in days}
        for d in days:
            dkey = d.isoformat()
            roster[dkey]["LOC_SHO_N"] = "LOCUM"
            roster[dkey]["LOC_REG_N"] = "LOCUM"
            roster[dkey]["LOC_REG_CMN"] = "LOCUM"
        summary = {"locum_slots": float(len(days) * 3)}
        return SolveResult(success=True, message="Solved (nights-only, locum-only)", roster=roster, breaches={}, summary=summary)

    # Build nights-only roster: only N/CMN assignments reflected; everything else OFF
    roster: Dict[str, Dict[str, str]] = {}
    for d_idx, day in enumerate(days):
        dkey = day.isoformat()
        roster[dkey] = {}
        for p_idx, person in enumerate(people):
            code = "OFF"
            if int(solver.Value(x[p_idx, d_idx, 'N'])) == 1:
                code = 'N'
            elif int(solver.Value(x[p_idx, d_idx, 'CMN'])) == 1:
                code = 'CMN'
            roster[dkey][person.id] = code
        # Locum columns for nights
        roster[dkey]["LOC_SHO_N"] = "LOCUM" if int(solver.Value(locums["loc_n_sho"][d_idx])) > 0 else ""
        roster[dkey]["LOC_REG_N"] = "LOCUM" if int(solver.Value(locums["loc_n_reg"][d_idx])) > 0 else ""
        roster[dkey]["LOC_REG_CMN"] = "LOCUM" if int(solver.Value(locums["loc_cmn"][d_idx])) > 0 else ""

    # Summary: locums and basic per-person night counts
    locum_total = 0
    for k in ("loc_n_sho", "loc_n_reg", "loc_cmn"):
        locum_total += sum(int(solver.Value(v)) for v in locums[k])
    summary = {"locum_slots": float(locum_total)}

    # Save CSV
    import pandas as pd
    import os
    os.makedirs("out", exist_ok=True)
    pd.DataFrame(roster).T.to_csv("out/roster_nights.csv")

    return SolveResult(success=True, message="Solved (nights-only)", roster=roster, breaches={}, summary=summary)

def solve_roster(problem: ProblemInput) -> SolveResult:
    # Single-pass solve: all rules are enforced hard; unfilled coverage is captured by locum slack variables.
    res, solver, x, locums, days, people = _solve(problem)
    if res not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # Extremely rare given slack; return locum-only diagnostic scaffold
        def drange(s, e):
            cur = s
            out = []
            while cur <= e:
                out.append(cur)
                cur += dt.timedelta(days=1)
            return out
        days = drange(problem.config.start_date, problem.config.end_date)
        people = problem.people
        roster = {d.isoformat(): {p.id: "OFF" for p in people} for d in days}
        for d in days:
            dkey = d.isoformat()
            for col in ["LOC_SHO_LD","LOC_REG_LD","LOC_SHO_N","LOC_REG_N","LOC_REG_CMD","LOC_REG_CMN"]:
                roster[dkey][col] = "LOCUM"
        # Minimal diagnostics
        summary = {"note": "Locum-only: solver could not find a feasible assignment even with slack.", "locum_slots": float(len(days) * 6)}
        return SolveResult(success=True, message="Solved (locum-only)", roster=roster, breaches={}, summary=summary)

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

        # Add explicit locum columns for this day based on locum variables
        # Initialize empty
        roster[dkey]["LOC_SHO_LD"] = ""
        roster[dkey]["LOC_REG_LD"] = ""
        roster[dkey]["LOC_SHO_N"]  = ""
        roster[dkey]["LOC_REG_N"]  = ""
        roster[dkey]["LOC_REG_CMD"] = ""
        roster[dkey]["LOC_REG_CMN"] = ""
        if int(solver.Value(locums["loc_ld_sho"][d_idx])) > 0:
            roster[dkey]["LOC_SHO_LD"] = "LOCUM"
        if int(solver.Value(locums["loc_ld_reg"][d_idx])) > 0:
            roster[dkey]["LOC_REG_LD"] = "LOCUM"
        if int(solver.Value(locums["loc_n_sho"][d_idx])) > 0:
            roster[dkey]["LOC_SHO_N"] = "LOCUM"
        if int(solver.Value(locums["loc_n_reg"][d_idx])) > 0:
            roster[dkey]["LOC_REG_N"] = "LOCUM"
        if int(solver.Value(locums["loc_cmd"][d_idx])) > 0:
            roster[dkey]["LOC_REG_CMD"] = "LOCUM"
        if int(solver.Value(locums["loc_cmn"][d_idx])) > 0:
            roster[dkey]["LOC_REG_CMN"] = "LOCUM"

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
    # Breaches based on locum usage: record dates where coverage relied on locums
    breaches = {
        "ld_reg": [],
        "ld_sho": [],
        "sd_weekday": [],
        "n_reg": [],
        "n_sho": [],
        "comet_day": [],
        "comet_night": []
    }
    for d_idx, day in enumerate(days):
        d = day.isoformat()
        if int(solver.Value(locums["loc_ld_reg"][d_idx])) > 0:
            breaches["ld_reg"].append(d)
        if int(solver.Value(locums["loc_ld_sho"][d_idx])) > 0:
            breaches["ld_sho"].append(d)
        # sd_weekday: only track on weekdays (we disallow SD on weekends)
        if day.weekday() < 5 and int(solver.Value(locums["loc_sd_any"][d_idx])) > 0:
            breaches["sd_weekday"].append(d)
        if int(solver.Value(locums["loc_n_reg"][d_idx])) > 0:
            breaches["n_reg"].append(d)
        if int(solver.Value(locums["loc_n_sho"][d_idx])) > 0:
            breaches["n_sho"].append(d)
        if int(solver.Value(locums["loc_cmd"][d_idx])) > 0:
            breaches["comet_day"].append(d)
        if int(solver.Value(locums["loc_cmn"][d_idx])) > 0:
            breaches["comet_night"].append(d)

    # Per-person stats: avg weekly hours, LD, nights, weekends, LD/N equivalents
    shift_hours = {"SD":9,"LD":13,"N":12,"CMD":12,"CMN":12,"CPD":9,"TREG":9,"TSHO":9,"TPCCU":9,"IND":9,"OFF":0}
    days_count = len(days)
    weeks = days_count/7.0 if days_count > 0 else 0.0
    per_person: Dict[str, Dict[str, float | int | str]] = {}
    # Build weekend blocks (Saturday with following Sunday if present)
    weekend_blocks = []
    for i in range(len(days)):
        if days[i].weekday() == 5:  # Saturday
            j = i+1 if i+1 < len(days) and days[i+1].weekday() == 6 else None
            weekend_blocks.append((i, j))
    # Compute
    for p_idx, person in enumerate(people):
        total_hours = 0.0
        long_days = 0
        nights = 0
        ld_equiv = 0
        n_equiv = 0
        # Sum hours and counts
        for d_idx, day in enumerate(days):
            code = roster[day.isoformat()][person.id]
            total_hours += shift_hours.get(code, 0)
            if code in ("LD","CMD"):
                long_days += 1
                ld_equiv += 1
            if code in ("N","CMN"):
                nights += 1
                n_equiv += 1
        # Weekends worked: any non-OFF assignment on Sat or Sun
        weekends = 0
        for sat, sun in weekend_blocks:
            worked = False
            sat_code = roster[days[sat].isoformat()][person.id]
            if sat_code and sat_code != "OFF":
                worked = True
            if not worked and sun is not None:
                sun_code = roster[days[sun].isoformat()][person.id]
                if sun_code and sun_code != "OFF":
                    worked = True
            if worked:
                weekends += 1
        avg_weekly_hours = (total_hours / weeks) if weeks > 0 else 0.0
        per_person[person.id] = {
            "name": person.name,
            "grade": person.grade,
            "wte": person.wte,
            "avg_weekly_hours": round(avg_weekly_hours, 1),
            "long_days": int(long_days),
            "nights": int(nights),
            "ld_equiv": int(ld_equiv),
            "n_equiv": int(n_equiv),
            "weekends": int(weekends),
        }
    summary["per_person"] = per_person

    # Aggregates: overall and by-grade for LD/N equivalents; registrar detail map
    # Build convenience arrays
    regs = [pid for pid, s in per_person.items() if (s.get('grade') == 'Registrar')]
    shos = [pid for pid, s in per_person.items() if (s.get('grade') == 'SHO')]
    def agg_for(ids):
        cnt = len(ids)
        if cnt == 0:
            return {"count": 0, "ld_equiv_total": 0, "n_equiv_total": 0, "ld_equiv_avg": 0.0, "n_equiv_avg": 0.0}
        ld_total = sum(int(per_person[i].get('ld_equiv', 0)) for i in ids)
        n_total  = sum(int(per_person[i].get('n_equiv', 0)) for i in ids)
        return {
            "count": cnt,
            "ld_equiv_total": ld_total,
            "n_equiv_total": n_total,
            "ld_equiv_avg": round(ld_total / cnt, 2),
            "n_equiv_avg": round(n_total / cnt, 2),
        }
    all_ids = list(per_person.keys())
    aggregates = {
        "all": agg_for(all_ids),
        "registrar": agg_for(regs),
        "sho": agg_for(shos),
    }
    # Registrar detail map for quick inspection/sorting
    registrar_ld_equiv = { pid: int(per_person[pid].get('ld_equiv', 0)) for pid in regs }
    summary["aggregates"] = aggregates
    summary["registrar_ld_equiv"] = registrar_ld_equiv

    # Write summaries
    import json
    with open(f"{out_dir}/summary.json","w") as f:
        json.dump(summary, f, indent=2)
    with open(f"{out_dir}/breaches.json","w") as f:
        json.dump(breaches, f, indent=2)

    # Per-day eligibility diagnostics removed per request

    return SolveResult(success=True, message="Solved", roster=roster, breaches=breaches, summary=summary)
