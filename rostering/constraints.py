from ortools.sat.python import cp_model
from typing import Dict, Tuple, List, Set
import datetime as dt
from dateutil.rrule import rrule, DAILY
from rostering.models import ProblemInput

ShiftCode = str
Var = cp_model.IntVar

def daterange(start: dt.date, end: dt.date):
    for d in rrule(DAILY, dtstart=start, until=end):
        yield d.date()

def is_weekend(d: dt.date) -> bool:
    return d.weekday() >= 5

def is_monday(d: dt.date) -> bool:
    return d.weekday() == 0

def build_index(problem: ProblemInput):
    # Calendar
    days = list(daterange(problem.config.start_date, problem.config.end_date))
    day_index = {d:i for i,d in enumerate(days)}
    # People filtered by start_date
    people = [p for p in problem.people if (p.start_date is None or p.start_date <= problem.config.end_date)]
    person_index = {p.id:i for i,p in enumerate(people)}
    return days, day_index, people, person_index

def basic_shift_catalog():
    # code, label, hours, count_in_cover, grade_requirement
    return {
        "SD":  ("Short Day", 9.0, True, None),           # 08:30-17:30
        "LD":  ("Long Day", 13.0, True, None),           # 08:30-21:30
        "N":   ("Night", 12.0, True, None),              # 20:30-08:30
        "CMD": ("COMET Day", 12.0, True, "Registrar"),
        "CMN": ("COMET Night", 12.0, True, "Registrar"),
        "CPD": ("CPD", 9.0, False, None),
        "TREG":("Registrar Teaching", 9.0, False, None),
        "TSHO":("SHO Teaching", 9.0, False, None),
        "TPCCU":("PCCU Teaching", 9.0, False, None),
        "IND": ("Induction", 9.0, False, None),
        "OFF": ("Off", 0.0, False, None),
        "LOC": ("Locum", 0.0, True, None)  # virtual coverage, not assigned to persons
    }

def add_core_constraints(problem: ProblemInput, model: cp_model.CpModel):
    days, day_index, people, person_index = build_index(problem)
    S = basic_shift_catalog()
    P = range(len(people))
    D = range(len(days))
    shift_codes = ["SD","LD","N","CMD","CMN","CPD","TREG","TSHO","TPCCU","IND","OFF"]
    # Decision vars: x[p,d,s] ∈ {0,1}
    x: Dict[Tuple[int,int,str], Var] = {}
    for p in P:
        for d in D:
            for s in shift_codes:
                x[p,d,s] = model.NewBoolVar(f"x_p{p}_d{d}_{s}")
    # Locum coverage slack per day/shift category (for cover counts)
    loc_ld_reg = [model.NewIntVar(0, 1, f"loc_ld_reg_d{d}") for d in D]
    loc_ld_sho = [model.NewIntVar(0, 1, f"loc_ld_sho_d{d}") for d in D]
    loc_sd_any = [model.NewIntVar(0, 5, f"loc_sd_any_d{d}") for d in D]
    loc_n_reg  = [model.NewIntVar(0, 1, f"loc_n_reg_d{d}")  for d in D]
    loc_n_sho  = [model.NewIntVar(0, 1, f"loc_n_sho_d{d}")  for d in D]
    loc_cmd    = [model.NewIntVar(0, 1, f"loc_cmd_d{d}")    for d in D]
    loc_cmn    = [model.NewIntVar(0, 1, f"loc_cmn_d{d}")    for d in D]

    # Helper sets
    reg_ids = {i for i,p in enumerate(people) if p.grade == "Registrar"}
    sho_ids = {i for i,p in enumerate(people) if p.grade == "SHO"}
    sup_ids = {i for i,p in enumerate(people) if p.grade == "Supernumerary"}

    # 1) At most one assigned shift per person per day
    for p in P:
        for d in D:
            model.Add(sum(x[p,d,s] for s in shift_codes if s != "OFF") <= 1)

    # 2) Supernumerary only SD (short day) or OFF/CPD/TEACH/IND (no LD/N/COMET)
    banned_for_sup = ["LD","N","CMD","CMN"]
    for p in sup_ids:
        for d in D:
            for s in banned_for_sup:
                model.Add(x[p,d,s] == 0)

    # 3) Fixed LTFT day off (hard unless manually overridden upstream)
    for p_idx, person in enumerate(people):
        if person.fixed_day_off is not None and person.wte < 1.0:
            for d_idx, day in enumerate(days):
                if day.weekday() == person.fixed_day_off:
                    model.Add(sum(x[p_idx,d_idx,s] for s in shift_codes if s != "OFF") == 0)

    # 4) Coverage requirements
    for d_idx, day in enumerate(days):
        wknd = is_weekend(day) or (day in problem.config.bank_holidays)

        # Long Days: weekdays need exactly 1 Reg + 1 SHO; weekends/bank holidays also exactly 1 each
        model.Add(sum(x[p,d_idx,"LD"] for p in reg_ids) + loc_ld_reg[d_idx] == 1)
        model.Add(sum(x[p,d_idx,"LD"] for p in sho_ids) + loc_ld_sho[d_idx] == 1)

        # Short Day: weekdays need at least 1 additional clinician (any grade), target 4 total (soft); weekends/bank holidays no SDs
        if not wknd:
            model.Add(sum(x[p,d_idx,"SD"] for p in P if p not in sup_ids) + loc_sd_any[d_idx] >= 1)
            # cap total day clinicians by config.max_day_clinicians — accounted in soft objective only (not hard cap).
        else:
            for p in P:
                model.Add(x[p,d_idx,"SD"] == 0)

        # Nights: exactly 1 Reg + 1 SHO
        model.Add(sum(x[p,d_idx,"N"] for p in reg_ids) + loc_n_reg[d_idx] == 1)
        model.Add(sum(x[p,d_idx,"N"] for p in sho_ids) + loc_n_sho[d_idx] == 1)

        # COMET shifts only if this week is an "on" week (marked by Monday in config)
        if any((monday == day if is_monday(day) else monday <= day <= monday + dt.timedelta(days=6)) for monday in problem.config.comet_on_weeks):
            # exactly 1 CMD and 1 CMN by comet-eligible registrars
            model.Add(sum(x[p,d_idx,"CMD"] for p in reg_ids) + loc_cmd[d_idx] == 1)
            model.Add(sum(x[p,d_idx,"CMN"] for p in reg_ids) + loc_cmn[d_idx] == 1)
            # eligibility
            for p in reg_ids:
                if not people[p].comet_eligible:
                    model.Add(x[p,d_idx,"CMD"] == 0)
                    model.Add(x[p,d_idx,"CMN"] == 0)
        else:
            for p in P:
                model.Add(x[p,d_idx,"CMD"] == 0)
                model.Add(x[p,d_idx,"CMN"] == 0)

    # 5) No daytime assignment on the calendar day after a night (rest rule; approximates 46h rest elsewhere)
    for p in P:
        for d in D[:-1]:
            model.Add(x[p,d,"N"] + sum(x[p,d+1,s] for s in ["SD","LD","CMD","CPD","TREG","TSHO","TPCCU","IND"]) <= 1)

        # 46h rest after any night block: enforce no assignment for two days after any night
        for d in D[:-2]:
            model.Add(x[p,d,"N"] + sum(x[p,d+1,s] for s in shift_codes if s != "OFF") + sum(x[p,d+2,s] for s in shift_codes if s != "OFF") <= 1)

    # 6) Max 72 hours in any rolling 7-day window
    shift_hours = {"SD":9,"LD":13,"N":12,"CMD":12,"CMN":12,"CPD":9,"TREG":9,"TSHO":9,"TPCCU":9,"IND":9}
    for p in P:
        for start in range(len(D)-6):
            expr = []
            for d in range(start, start+7):
                expr += [x[p,d,s]*shift_hours[s] for s in shift_codes if s in shift_hours]
            model.Add(sum(expr) <= 72)

    # 7) Max 1 assignment per night/day combination already ensures 11h rest and max shift length defined by catalog

    # 8) Prevent teaching for those on nights same 24h (covered by rule 5)

    return x, {
        "loc_ld_reg":loc_ld_reg, "loc_ld_sho":loc_ld_sho, "loc_sd_any":loc_sd_any,
        "loc_n_reg":loc_n_reg, "loc_n_sho":loc_n_sho, "loc_cmd":loc_cmd, "loc_cmn":loc_cmn
    }, days, people

def soft_objective(problem: ProblemInput, model: cp_model.CpModel, x, locums, days, people):
    # Minimize locums heavily + gentle push towards weekday day target counts
    terms = []
    W = problem.weights

    # Locum penalties
    for k in ["loc_ld_reg","loc_ld_sho","loc_sd_any","loc_n_reg","loc_n_sho","loc_cmd","loc_cmn"]:
        for v in locums[k]:
            terms.append(W.locum * v)

    # Weekday day target (aim 4 clinicians on weekdays; supernumerary don't count)
    for d_idx, day in enumerate(days):
        if day.weekday() < 5 and day not in problem.config.bank_holidays:
            # count = LD(2 people) + SD(any count) excluding supernumerary; LDs are exactly 2 already by grade requirement
            # encourage SD count to reach ideal (min 1 is hard)
            # we can't use absolute value easily; approximate with hinge loss from ideal
            ideal = problem.config.ideal_weekday_day_clinicians
            # Decision: approximate penalty for deviation from ideal using extra slack ints
            # Create per-day deviation variable
            dev_pos = model.NewIntVar(0, 5, f"devpos_d{d_idx}")
            dev_neg = model.NewIntVar(0, 5, f"devneg_d{d_idx}")
            # sum SDs among non-supernumerary
            sd_sum = sum(x[p,d_idx,"SD"] for p in range(len(people)) if people[p].grade != "Supernumerary")
            # total clinicians = 2 (LD pair) + sd_sum
            # enforce dev_pos - dev_neg = (2 + sd_sum) - ideal
            model.Add(dev_pos - dev_neg == 2 + sd_sum - ideal)
            terms.append(problem.weights.weekday_day_target_penalty * (dev_pos + dev_neg))

    model.Minimize(sum(terms))
