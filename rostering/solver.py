from ortools.sat.python import cp_model
from typing import Dict
import pandas as pd
import datetime as dt
import math
from rostering.models import ProblemInput, SolveResult
from rostering.constraints import add_core_constraints, soft_objective, PERSON_SHIFT_CODES, WORK_SHIFT_CODES

def _solve(problem: ProblemInput):
    # Pass 1: nights-only to stabilize night allocation
    model1 = cp_model.CpModel()
    x1, locums1, days, people = add_core_constraints(problem, model1, options={"nights_only": True})
    soft_objective(problem, model1, x1, locums1, days, people, options={"nights_only": True})
    solver1 = cp_model.CpSolver()
    solver1.parameters.max_time_in_seconds = 120.0  # Increased from 60
    solver1.parameters.num_search_workers = 8
    solver1_res = solver1.Solve(model1)
    freeze = []
    if solver1_res in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for p_idx in range(len(people)):
            for d_idx in range(len(days)):
                for code in ('NS', 'NR', 'CMN'):
                    if (p_idx, d_idx, code) in x1 and int(solver1.Value(x1[p_idx, d_idx, code])) == 1:
                        freeze.append((p_idx, d_idx, code))
    # Pass 2: full objective with frozen nights
    model = cp_model.CpModel()
    x, locums, days, people = add_core_constraints(problem, model, options={"freeze_nights": freeze})
    soft_objective(problem, model, x, locums, days, people)

    # Add solution hints from Pass 1 nights to guide search (keeps CP-SAT near the nights layout)
    try:
        hinted_vars = []
        hinted_vals = []
        for (p_idx, d_idx, s) in freeze:
            hinted_vars.append(x[p_idx, d_idx, s])
            hinted_vals.append(1)
            # Also hint paired registrar night types to 0 to reduce flips
            others: list[str] = []
            if s == "NR":
                others = ["CMN"]
            elif s == "CMN":
                others = ["NR"]
            for other in others:
                if (p_idx, d_idx, other) in x:
                    hinted_vars.append(x[p_idx, d_idx, other])
                    hinted_vals.append(0)
        if hinted_vars:
            model.AddHint(hinted_vars, hinted_vals)
    except Exception:
        pass

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 120.0  # Reasonable timeout
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = 1
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
            for night_code in ('NS', 'NR', 'CMN'):
                if (p_idx, d_idx, night_code) in x and int(solver.Value(x[p_idx, d_idx, night_code])) == 1:
                    code = night_code
                    break
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
            for s in PERSON_SHIFT_CODES:
                if solver.Value(x[p_idx, d_idx, s]) == 1:
                    code = s
                    break
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
        "comet_night": [],
        "firm_weekend_frequency": [],
        "firm_weekend_pairs": [],
        "training_attendance": []
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
    shift_hours = {
        "SD": 9,
        "LDS": 13,
        "LDR": 13,
        "NS": 13,
        "NR": 13,
        "CMD": 12,
        "CMN": 12,
        "CPD": 9,
        "TREG": 9,
        "TSHO": 9,
        "TPCCU": 9,
        "IND": 9,
        "LV": 9,
        "SLV": 9,
        "LTFT": 0,
        "OFF": 0,
    }
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
        reg_training = 0
        sho_training = 0
        unit_training = 0
        cpd_days = 0
        leave_days = 0
        study_days = 0
        induction_days = 0
        # Sum hours and counts
        for d_idx, day in enumerate(days):
            code = roster[day.isoformat()][person.id]
            total_hours += shift_hours.get(code, 0)
            if code in ("LDR", "LDS", "CMD"):
                long_days += 1
                ld_equiv += 1
            if code in ("NR", "NS", "CMN"):
                nights += 1
                n_equiv += 1
            if code == "TREG":
                reg_training += 1
            if code == "TSHO":
                sho_training += 1
            if code == "TPCCU":
                unit_training += 1
            if code == "CPD":
                cpd_days += 1
            if code == "LV":
                leave_days += 1
            if code == "SLV":
                study_days += 1
            if code == "IND":
                induction_days += 1
        # Weekends worked: any non-OFF assignment on Sat or Sun
        weekends = 0
        weekend_split_details = []
        for sat, sun in weekend_blocks:
            sat_code = roster[days[sat].isoformat()][person.id]
            worked_sat = sat_code in WORK_SHIFT_CODES
            worked_sun = False
            if sun is not None:
                sun_code = roster[days[sun].isoformat()][person.id]
                worked_sun = sun_code in WORK_SHIFT_CODES
            if worked_sat or worked_sun:
                weekends += 1
            if sun is not None and worked_sat != worked_sun:
                worked_days = []
                if worked_sat:
                    worked_days.append("sat")
                if worked_sun:
                    worked_days.append("sun")
                weekend_split_details.append({
                    "weekend_start": days[sat].isoformat(),
                    "worked_days": worked_days
                })
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
            "registrar_training_days": int(reg_training),
            "sho_training_days": int(sho_training),
            "unit_training_days": int(unit_training),
            "cpd_days": int(cpd_days),
            "leave_days": int(leave_days),
            "study_leave_days": int(study_days),
            "induction_days": int(induction_days),
        }
        if weekend_split_details:
            per_person[person.id]["weekend_single_days"] = weekend_split_details

    # Compute firm weekend breaches and training fairness diagnostics
    weekend_caps = locums.get("weekend_firm_caps", {})
    def training_band_bounds(target: float, band: float = 0.33) -> tuple[int, int]:
        if target <= 0:
            return 0, 0
        if target < 1:
            return 0, max(1, math.ceil(target + 1))
        lower = max(0, math.floor(target * (1 - band)))
        upper = max(lower, math.ceil(target * (1 + band)))
        return lower, upper

    reg_training_days = sorted(problem.config.global_registrar_teaching_days or [])
    sho_training_days = sorted(problem.config.global_sho_teaching_days or [])
    unit_training_days = sorted(problem.config.global_unit_teaching_days or [])

    for p_idx, person in enumerate(people):
        pid = person.id
        pdata = per_person.get(pid, {})
        worked_weekends = int(pdata.get("weekends", 0))
        firm_cap = weekend_caps.get(p_idx, 0)
        if worked_weekends > firm_cap:
            breaches["firm_weekend_frequency"].append({
                "person_id": pid,
                "worked_weekends": worked_weekends,
                "firm_cap": firm_cap
            })
        split_info = pdata.get("weekend_single_days", [])
        for entry in split_info:
            breaches["firm_weekend_pairs"].append({
                "person_id": pid,
                **entry
            })

        start_date = person.start_date or problem.config.start_date
        wte = getattr(person, "wte", 1.0) or 1.0
        wte = max(0.2, min(1.0, float(wte)))

        if person.grade == "Registrar" and reg_training_days:
            available = sum(1 for d in reg_training_days if d >= start_date)
            target = available * wte
            low, high = training_band_bounds(target)
            pdata["registrar_training_window"] = {"min": low, "max": high}
            actual = int(pdata.get("registrar_training_days", 0))
            if available and (actual < low or actual > high):
                breaches["training_attendance"].append({
                    "person_id": pid,
                    "type": "registrar",
                    "actual": actual,
                    "min_expected": low,
                    "max_expected": high
                })

        if person.grade == "SHO" and sho_training_days:
            available = sum(1 for d in sho_training_days if d >= start_date)
            target = available * wte
            low, high = training_band_bounds(target)
            pdata["sho_training_window"] = {"min": low, "max": high}
            actual = int(pdata.get("sho_training_days", 0))
            if available and (actual < low or actual > high):
                breaches["training_attendance"].append({
                    "person_id": pid,
                    "type": "sho",
                    "actual": actual,
                    "min_expected": low,
                    "max_expected": high
                })

        if unit_training_days:
            available = sum(1 for d in unit_training_days if d >= start_date)
            target = available * wte
            low, high = training_band_bounds(target)
            pdata["unit_training_window"] = {"min": low, "max": high}
            actual = int(pdata.get("unit_training_days", 0))
            if available and (actual < low or actual > high):
                breaches["training_attendance"].append({
                    "person_id": pid,
                    "type": "unit",
                    "actual": actual,
                    "min_expected": low,
                    "max_expected": high
                })
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
