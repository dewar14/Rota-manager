from ortools.sat.python import cp_model
from typing import Dict, Tuple
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
    # People filtered by effective start_date (default to rota start when missing)
    people = [p for p in problem.people if ((p.start_date or problem.config.start_date) <= problem.config.end_date)]
    person_index = {p.id:i for i,p in enumerate(people)}
    return days, day_index, people, person_index

def basic_shift_catalog():
    # code, label, hours, count_in_cover, grade_requirement
    return {
        "SD":  ("Short Day", 9.0, True, None),           # 08:30-17:30
        "LD":  ("Long Day", 13.0, True, None),           # 08:30-21:30
        "N":   ("Night", 13.0, True, None),              # 20:30-08:30
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

def add_core_constraints(problem: ProblemInput, model: cp_model.CpModel, options: dict | None = None):
    options = options or {}
    nights_only: bool = bool(options.get('nights_only', False))
    freeze_nights: list[tuple[int,int,str]] = options.get('freeze_nights', []) or []
    days, day_index, people, person_index = build_index(problem)
    # S = basic_shift_catalog()
    P = range(len(people))
    D = range(len(days))
    shift_codes = ["SD","LD","N","CMD","CMN","CPD","TREG","TSHO","TPCCU","IND","OFF"]
    # Decision vars: x[p,d,s] ∈ {0,1}
    x: Dict[Tuple[int,int,str], Var] = {}
    for p in P:
        for d in D:
            for s in shift_codes:
                x[p,d,s] = model.NewBoolVar(f"x_p{p}_d{d}_{s}")
    # Apply freeze for nights if provided
    if freeze_nights:
        for (pidx, didx, scode) in freeze_nights:
            if scode in ("N","CMN") and 0 <= pidx < len(people) and 0 <= didx < len(days):
                model.Add(x[pidx, didx, scode] == 1)
                # Optional: encourage uniqueness by zeroing others for same day/shift
                for q in P:
                    if q != pidx:
                        model.Add(x[q, didx, scode] == 0)
    # Locum coverage slack per day/shift category (for cover counts)
    loc_ld_reg = [model.NewIntVar(0, 1, f"loc_ld_reg_d{d}") for d in D]
    loc_ld_sho = [model.NewIntVar(0, 1, f"loc_ld_sho_d{d}") for d in D]
    loc_sd_any = [model.NewIntVar(0, 5, f"loc_sd_any_d{d}") for d in D]
    loc_n_reg  = [model.NewIntVar(0, 1, f"loc_n_reg_d{d}")  for d in D]
    loc_n_sho  = [model.NewIntVar(0, 1, f"loc_n_sho_d{d}")  for d in D]
    loc_cmd    = [model.NewIntVar(0, 1, f"loc_cmd_d{d}")    for d in D]
    loc_cmn    = [model.NewIntVar(0, 1, f"loc_cmn_d{d}")    for d in D]

    # Helper sets (normalize grade names defensively)
    def gnorm(g: str | None) -> str:
        return (g or "").strip().lower()
    reg_ids = {i for i,p in enumerate(people) if gnorm(getattr(p, 'grade', None)) == "registrar"}
    sho_ids = {i for i,p in enumerate(people) if gnorm(getattr(p, 'grade', None)) == "sho"}
    sup_ids = {i for i,p in enumerate(people) if gnorm(getattr(p, 'grade', None)) == "supernumerary"}

    # 1) At most one assigned shift per person per day
    for p in P:
        for d in D:
            model.Add(sum(x[p,d,s] for s in shift_codes if s != "OFF") <= 1)
    # 1a) Start-date gating: use effective start = person's start_date or rota start if blank
    for p_idx, person in enumerate(people):
        eff_start = person.start_date or problem.config.start_date
        for d_idx, day in enumerate(days):
            if day < eff_start:
                model.Add(sum(x[p_idx,d_idx,s] for s in shift_codes if s != "OFF") == 0)


    # 2) Supernumerary only SD (short day) or OFF/CPD/TEACH/IND (no LD/N/COMET)
    banned_for_sup = ["LD","N","CMD","CMN"]
    for p in sup_ids:
        for d in D:
            for s in banned_for_sup:
                model.Add(x[p,d,s] == 0)

    # 3) Fixed LTFT day off
    fdo_violations = []
    for p_idx, person in enumerate(people):
        if person.fixed_day_off is not None and person.wte < 1.0:
            for d_idx, day in enumerate(days):
                if day.weekday() == person.fixed_day_off:
                    model.Add(sum(x[p_idx,d_idx,s] for s in shift_codes if s != "OFF") == 0)

    # 4) Coverage requirements
    for d_idx, day in enumerate(days):
        wknd = is_weekend(day) or (day in problem.config.bank_holidays)
        comet_on = any((monday == day if is_monday(day) else monday <= day <= monday + dt.timedelta(days=6)) for monday in problem.config.comet_on_weeks)
        if not nights_only:
            # Long Days
            # SHO LD: always exactly 1 (weekday/weekend alike), with locum slack
            model.Add(sum(x[p,d_idx,"LD"] for p in sho_ids) + loc_ld_sho[d_idx] == 1)
            # Registrar LD: always exactly 1, with locum slack
            model.Add(sum(x[p,d_idx,"LD"] for p in reg_ids) + loc_ld_reg[d_idx] == 1)
            # COMET Day: additional registrar on COMET weeks
            if comet_on:
                model.Add(sum(x[p,d_idx,"CMD"] for p in reg_ids) + loc_cmd[d_idx] == 1)
                for p in reg_ids:
                    if not getattr(people[p], 'comet_eligible', False):
                        model.Add(x[p,d_idx,"CMD"] == 0)
            else:
                for p in P:
                    model.Add(x[p,d_idx,"CMD"] == 0)

            # Short Day: disable SDs on weekends/bank holidays and on global induction days; otherwise use weekday targets
            induction_day = day in (problem.config.global_induction_days or [])
            if induction_day:
                # Everyone not on cover should attend induction; do not schedule SD and no SD locum expectation
                for p in P:
                    model.Add(x[p,d_idx,"SD"] == 0)
                model.Add(loc_sd_any[d_idx] == 0)
            elif not wknd:
                MIN_TOTAL = 3
                MAX_TOTAL = 5
                extra = 1 if comet_on else 0  # COMET adds an extra day clinician
                sd_sum = sum(x[p,d_idx,"SD"] for p in P if p not in sup_ids)
                # Ensure minimum total clinicians
                model.Add(sd_sum + loc_sd_any[d_idx] >= max(0, MIN_TOTAL - 2 - extra))
                # Cap SDs to respect max total clinicians
                if MAX_TOTAL >= 2 + extra:
                    model.Add(sd_sum <= MAX_TOTAL - 2 - extra)
                else:
                    model.Add(sd_sum == 0)
            else:
                for p in P:
                    model.Add(x[p,d_idx,"SD"] == 0)

        # Nights
        # SHO N: always exactly 1, with locum slack
        model.Add(sum(x[p,d_idx,"N"] for p in sho_ids) + loc_n_sho[d_idx] == 1)
        # Registrar N: always exactly 1, with locum slack
        model.Add(sum(x[p,d_idx,"N"] for p in reg_ids) + loc_n_reg[d_idx] == 1)
        # COMET Night: additional registrar on COMET weeks
        if comet_on:
            model.Add(sum(x[p,d_idx,"CMN"] for p in reg_ids) + loc_cmn[d_idx] == 1)
            for p in reg_ids:
                if not getattr(people[p], 'comet_eligible', False):
                    model.Add(x[p,d_idx,"CMN"] == 0)
        else:
            for p in P:
                model.Add(x[p,d_idx,"CMN"] == 0)

    # 5) No daytime assignment on the calendar day after a night (rest rule)
    for p in P:
        for d in D[:-1]:
            model.Add(x[p,d,"N"] + sum(x[p,d+1,s] for s in ["SD","LD","CMD","CPD","TREG","TSHO","TPCCU","IND"]) <= 1)
    # 5a) Avoid LD immediately before a night; allow SD before night (encouraged in objective separately)
    for p in P:
        for d in D[:-1]:
            model.Add(x[p,d,"LD"] + x[p,d+1,"N"] <= 1)

    # 6) Max 72 hours in any rolling 7-day window
    shift_hours = {"SD":9,"LD":13,"N":12,"CMD":12,"CMN":12,"CPD":9,"TREG":9,"TSHO":9,"TPCCU":9,"IND":9}
    for p in P:
        for start in range(len(D)-6):
            expr = []
            for d in range(start, start+7):
                expr += [x[p,d,s]*shift_hours[s] for s in shift_codes if s in shift_hours]
            model.Add(sum(expr) <= 72)

    # 7) Additional sequence constraints
    # 7a) No singleton nights (min 2 in any contiguous block of nights)
    for p in P:
        for d in D:
            if d > 0 and d < len(D)-1:
                model.Add(x[p,d,"N"] <= x[p,d-1,"N"] + x[p,d+1,"N"]) 

    # 7b) Max 4 consecutive nights
    for p in P:
        for start in range(len(D)-4):
            model.Add(sum(x[p,d,"N"] for d in range(start, start+5)) <= 4)

    # 7b-2) Require at least 5 days between night blocks (no sequences like N N N N, OFF, N N N)
    for p in P:
        for d in D:
            # Window: current block d..d+3 (up to 4 nights), then enforce gap on d+4..d+8
            if d + 4 < len(D):
                block_days = list(range(d, min(d+4, len(D))))
                future_days = list(range(min(d+4, len(D)), min(d+9, len(D))))
                if not future_days:
                    continue
                block_any = model.NewBoolVar(f"night_block_any_p{p}_d{d}")
                # block_any = OR_{dd in block_days} x[p,dd,N]
                model.AddMaxEquality(block_any, [x[p,dd,"N"] for dd in block_days])
                # If any night in block_days, then no nights in future_days
                model.Add(sum(x[p,dd,"N"] for dd in future_days) == 0).OnlyEnforceIf(block_any)

    # 7c) Max 7 consecutive shifts of any kind (non-OFF)
    for p in P:
        for start in range(len(D)-7):
            model.Add(sum(sum(x[p,d,s] for s in shift_codes if s != "OFF") for d in range(start, start+8)) <= 7)

    # 7d) Weekends accounting for 1-in-3 rule (soft in objective via locums by limiting LDs)
    # Count weekends per person and restrict frequency by allowing locum to cover if needed
    # For simplicity, enforce at most ceil(num_weekends/3) worked weekends as hard cap
    weekend_blocks = []
    for i in range(len(days)-1):
        if days[i].weekday() == 5:
            weekend_blocks.append((i, i+1 if days[i+1].weekday()==6 else None))
    import math
    cap = math.ceil(len(weekend_blocks)/3)
    for p in P:
        wknd_work = []
        for sat_idx, sun_idx in weekend_blocks:
            terms = [x[p,sat_idx,"LD"]]
            if sun_idx is not None:
                terms.append(x[p,sun_idx,"LD"])
            b = model.NewBoolVar(f"wknd_p{p}_sat{sat_idx}")
            model.Add(sum(terms) >= 1).OnlyEnforceIf(b)
            model.Add(sum(terms) == 0).OnlyEnforceIf(b.Not())
            wknd_work.append(b)
        model.Add(sum(wknd_work) <= cap)

    # Build preassignment map to gate global auto-assignments
    pid_to_idx = {p.id:i for i,p in enumerate(people)}
    pre_any = set()
    pre_off = set()
    try:
        _pre = getattr(problem, 'preassignments', []) or []
        for item in _pre:
            pid = item.get('person_id')
            date = item.get('date')
            shift = item.get('shift_code')
            if pid in pid_to_idx and shift in ["SD","LD","N","CMD","CMN","CPD","TREG","TSHO","TPCCU","IND","OFF"]:
                d = dt.date.fromisoformat(date)
                if d in day_index:
                    pidx = pid_to_idx[pid]
                    didx = day_index[d]
                    pre_any.add((pidx, didx))
                    if shift == "OFF":
                        pre_off.add((pidx, didx))
    except Exception:
        pass

    # 8) Global auto-assignments (induction/teaching) applied when NOT on mandatory cover (LD/N/COMET).
    # If multiple global events fall on the same day, we apply precedence: IND > (TREG/TSHO) > TPCCU
    g_ind = set(problem.config.global_induction_days or [])
    g_treg = set(problem.config.global_registrar_teaching_days or [])
    g_tsho = set(problem.config.global_sho_teaching_days or [])
    g_unit = set(problem.config.global_unit_teaching_days or [])
    # Explicitly forbid non-registrars from COMET roles
    for p in P:
        if p not in reg_ids:
            for d in D:
                model.Add(x[p,d,"CMD"] == 0)
                model.Add(x[p,d,"CMN"] == 0)
    for p_idx, person in enumerate(people):
        for d_idx, day in enumerate(days):
            is_fdo_day = (
                person.fixed_day_off is not None and person.wte < 1.0 and day.weekday() == person.fixed_day_off
            )
            mand = [x[p_idx,d_idx,s] for s in ["LD","N","CMD","CMN"]]
            on_mand = model.NewBoolVar(f"on_mand_p{p_idx}_d{d_idx}")
            model.Add(sum(mand) >= 1).OnlyEnforceIf(on_mand)
            model.Add(sum(mand) == 0).OnlyEnforceIf(on_mand.Not())

            present: list[str] = []
            if day in g_ind:
                present.append("IND")
            if person.grade == "Registrar" and day in g_treg:
                present.append("TREG")
            if person.grade == "SHO" and day in g_tsho:
                present.append("TSHO")
            if day in g_unit:
                present.append("TPCCU")

            if present and not nights_only:
                # Determine precedence (kept for documentation), but we no longer force assignment
                # precedence: IND > (TREG/TSHO) > TPCCU

                if (p_idx, d_idx) in pre_any:
                    continue
                if is_fdo_day:
                    for code in present:
                        model.Add(x[p_idx,d_idx,code] == 0)
                    continue
                # Do not force attendance at IND/teaching; only forbid when on mandatory cover
                for code in present:
                    model.Add(x[p_idx,d_idx,code] == 0).OnlyEnforceIf(on_mand)

    # Gate special day codes to only their configured dates
    for p_idx, person in enumerate(people):
        for d_idx, day in enumerate(days):
            if day not in g_ind:
                model.Add(x[p_idx,d_idx,"IND"] == 0)
            if not (person.grade == "Registrar" and day in g_treg):
                model.Add(x[p_idx,d_idx,"TREG"] == 0)
            if not (person.grade == "SHO" and day in g_tsho):
                model.Add(x[p_idx,d_idx,"TSHO"] == 0)
            if day not in g_unit:
                model.Add(x[p_idx,d_idx,"TPCCU"] == 0)

    # 9) Preassignments: soft-only preferences (rules always take precedence)
    pre = getattr(problem, 'preassignments', []) or []
    # Map person_id to index
    pid_to_idx = {p.id:i for i,p in enumerate(people)}
    pre_ok_flags = []
    cpd_allowed: set[tuple[int,int]] = set()
    for item in pre:
        try:
            pid = item.get('person_id')
            date = item.get('date')
            shift = item.get('shift_code')
            if pid in pid_to_idx and shift in shift_codes:
                d = dt.date.fromisoformat(date)
                if d in day_index:
                    pidx = pid_to_idx[pid]
                    didx = day_index[d]
                    if shift == 'CPD':
                        cpd_allowed.add((pidx, didx))
                    # Soft preassignment: prefer, but allow violation
                    b = model.NewBoolVar(f"pre_ok_p{pidx}_d{didx}_{shift}")
                    model.Add(x[pidx,didx,shift] == 1).OnlyEnforceIf(b)
                    model.Add(x[pidx,didx,shift] == 0).OnlyEnforceIf(b.Not())
                    pre_ok_flags.append(b)
        except Exception:
            pass

    # CPD gating: only allow CPD when explicitly preassigned
    for p in range(len(people)):
        for d in range(len(days)):
            if (p, d) not in cpd_allowed:
                model.Add(x[p,d,'CPD'] == 0)

    # Prevent teaching for those on nights same 24h (covered by rule 5)

    return x, {
        "loc_ld_reg":loc_ld_reg, "loc_ld_sho":loc_ld_sho, "loc_sd_any":loc_sd_any,
        "loc_n_reg":loc_n_reg, "loc_n_sho":loc_n_sho, "loc_cmd":loc_cmd, "loc_cmn":loc_cmn,
        "fdo_violations": fdo_violations,
        "pre_ok_flags": pre_ok_flags
    }, days, people

def soft_objective(problem: ProblemInput, model: cp_model.CpModel, x, locums, days, people, options: dict | None = None):
    options = options or {}
    nights_only: bool = bool(options.get('nights_only', False))
    # Minimize locums heavily + gentle push towards weekday day target counts
    terms = []
    W = problem.weights

    # Locum penalties
    loc_keys = ["loc_n_reg","loc_n_sho","loc_cmn"] if nights_only else ["loc_ld_reg","loc_ld_sho","loc_sd_any","loc_n_reg","loc_n_sho","loc_cmd","loc_cmn"]
    for k in loc_keys:
        for v in locums[k]:
            terms.append(W.locum * v)

    # FDO is hard now; keep placeholder for compatibility (no-op)
    # For preassignments, penalize when b==0 (violation). We model cost as (1 - b).
    for b in locums.get("pre_ok_flags", []):
        one_minus = model.NewIntVar(0,1, f"pre_viol_cost_{b.Index()}")
        model.Add(one_minus == 1 - b)
        terms.append(W.preassign_violation * one_minus)

    # Weekday day target (aim IDEAL_TOTAL clinicians on weekdays; supernumerary don't count)
    for d_idx, day in enumerate(days):
        if day.weekday() < 5 and day not in problem.config.bank_holidays:
            ideal = 4
            dev_pos = model.NewIntVar(0, 6, f"devpos_d{d_idx}")
            dev_neg = model.NewIntVar(0, 6, f"devneg_d{d_idx}")
            sd_sum = sum(x[p,d_idx,"SD"] for p in range(len(people)) if people[p].grade != "Supernumerary")
            # Base 2 (LD SHO + LD Reg) + 1 if COMET day exists
            comet_week = any((monday == day if is_monday(day) else monday <= day <= monday + dt.timedelta(days=6)) for monday in problem.config.comet_on_weeks)
            base = 3 if comet_week else 2
            if not nights_only:
                model.Add(dev_pos - dev_neg == base + sd_sum - ideal)
                terms.append(problem.weights.weekday_day_target_penalty * (dev_pos + dev_neg))

    # Weekend block preference: penalize Sat-only or Sun-only long days (prefer Sat+Sun blocks)
    # Build weekend blocks (Saturday paired with following Sunday if present)
    weekend_blocks = []
    for i in range(len(days)-1):
        if days[i].weekday() == 5:  # Saturday
            sunday = i+1 if days[i+1].weekday() == 6 else None
            if sunday is not None:
                weekend_blocks.append((i, sunday))
    for p in range(len(people)):
        for sat_idx, sun_idx in weekend_blocks:
            ld_sat = x[p, sat_idx, "LD"]
            ld_sun = x[p, sun_idx, "LD"]
            both = model.NewBoolVar(f"wknd_both_p{p}_s{sat_idx}")
            # both == 1 -> ld_sat=1 and ld_sun=1
            model.AddBoolAnd([ld_sat, ld_sun]).OnlyEnforceIf(both)
            model.Add(both <= ld_sat)
            model.Add(both <= ld_sun)
            split = model.NewBoolVar(f"wknd_split_p{p}_s{sat_idx}")
            # split = ld_sat + ld_sun - 2*both  (0 when both 0 or 1; 1 when exactly one is 1)
            model.Add(split == ld_sat + ld_sun - 2*both)
            terms.append(W.weekend_split_penalty * split)

    # Encourage target weekly hours pro-rata [45..48] scaled by WTE: penalize deficit below 45*WTE and excess above 48*WTE.
    shift_hours = {"SD":9,"LD":13,"N":12,"CMD":12,"CMN":12,"CPD":9,"TREG":9,"TSHO":9,"TPCCU":9,"IND":9}
    days_count = len(days)
    weeks = days_count/7.0 if days_count > 0 else 0.0
    if weeks > 0 and not nights_only:
        for p in range(len(people)):
            total_h = model.NewIntVar(0, int(13*days_count), f"total_h_p{p}")
            model.Add(total_h == sum(x[p,d,s]*int(shift_hours[s]) for d in range(len(days)) for s in shift_hours))
            wte100 = int(round((getattr(people[p], 'wte', 1.0) or 1.0) * 100))
            wte100 = max(20, min(100, wte100))
            min_needed = int(round(45 * weeks * wte100 / 100))
            max_allowed = int(round(48 * weeks * wte100 / 100))
            # deficit
            deficit = model.NewIntVar(0, max(0, min_needed), f"weekly_deficit_p{p}")
            model.Add(deficit >= min_needed - total_h)
            model.Add(deficit >= 0)
            terms.append(W.min_weekly_hours_penalty * deficit)
            # excess
            excess = model.NewIntVar(0, max(0, 13*days_count), f"weekly_excess_p{p}")
            model.Add(excess >= total_h - max_allowed)
            model.Add(excess >= 0)
            terms.append(W.max_weekly_hours_penalty * excess)

    # Night block shaping even in relaxed mode: penalize singleton nights and encourage 2-4 blocks
    for p in range(len(people)):
        for d in range(len(days)):
            if 0 < d < len(days)-1:
                sing = model.NewBoolVar(f"soft_single_n_p{p}_d{d}")
                # sing = N_d & (~N_{d-1}) & (~N_{d+1})
                model.Add(sing <= x[p,d,"N"]) 
                model.Add(sing <= 1 - x[p,d-1,"N"]) 
                model.Add(sing <= 1 - x[p,d+1,"N"]) 
                # If N_d is 1 and both neighbours 0, sing can be 1; otherwise forced 0
                terms.append(W.single_night_penalty * sing)
        # Also gently discourage >4 nights in any 5-day window
        for start in range(len(days)-4):
            over4 = model.NewBoolVar(f"soft_over4_n_p{p}_s{start}")
            window_sum = sum(x[p,d,"N"] for d in range(start, start+5))
            # over4 >= window_sum - 4
            aux = model.NewIntVar(0,5,f"aux_n5_p{p}_s{start}")
            model.Add(aux == window_sum)
            model.Add(over4 >= aux - 4)
            model.Add(over4 >= 0)
            terms.append(W.single_night_penalty * over4)

    # Fairness: discourage clustering by penalizing pairwise differences in shift counts
    # Build grade groups
    def gnorm(g: str | None) -> str:
        return (g or "").strip().lower()
    reg_ids = [i for i,p in enumerate(people) if gnorm(getattr(p, 'grade', None)) == 'registrar']
    sho_ids = [i for i,p in enumerate(people) if gnorm(getattr(p, 'grade', None)) == 'sho']

    # Helper to add pairwise fairness on totals for a given shift code and group, scaled by WTE
    def add_pairwise_fairness(group: list[int], shift_code: str, label: str):
        if len(group) <= 1:
            return
        totals = []
        scales = []
        for p in group:
            t = model.NewIntVar(0, len(days), f"tot_{label}_p{p}")
            model.Add(t == sum(x[p, d, shift_code] for d in range(len(days))))
            totals.append(t)
            # Scale counts by inverse of WTE so LTFT aren't penalized for having fewer shifts
            wte = getattr(people[p], 'wte', 1.0) or 1.0
            # If registrar and LD/N, reduce effective WTE when COMET-eligible so they are expected to do fewer
            if getattr(people[p], 'grade', '') == 'Registrar' and shift_code in ('LD','N'):
                if getattr(people[p], 'comet_eligible', False):
                    wte *= problem.weights.comet_ldn_share_factor
            # Clamp to avoid division by zero and extreme scaling
            wte = max(0.2, min(1.0, float(wte)))
            scale = int(round(100 / wte))  # 100 for 1.0 WTE, 125 for 0.8, 167 for 0.6, etc.
            scales.append(scale)
        # Penalize absolute differences |(totals[i]*scale_i) - (totals[j]*scale_j)|
        for i in range(len(group)):
            for j in range(i+1, len(group)):
                # Upper bound for diff: max scaled total can't exceed len(days)*max(scale)
                max_scale = max(scales[i], scales[j])
                diff = model.NewIntVar(0, len(days)*max_scale, f"fair_{label}_{group[i]}_{group[j]}")
                # diff >= totals[i]*scale_i - totals[j]*scale_j
                model.Add(diff >= totals[i]*scales[i] - totals[j]*scales[j])
                model.Add(diff >= totals[j]*scales[j] - totals[i]*scales[i])
                terms.append(W.fairness_variance * diff)

    # Composite pairwise fairness where multiple shift codes are equivalent (e.g., LD + CMD)
    def add_pairwise_fairness_composite(group: list[int], comp_shifts: list[str], label: str, base_shift: str):
        if len(group) <= 1:
            return
        totals = []
        scales = []
        for p in group:
            t = model.NewIntVar(0, len(days) * len(comp_shifts), f"tot_{label}_p{p}")
            model.Add(t == sum(sum(x[p, d, s] for s in comp_shifts) for d in range(len(days))))
            totals.append(t)
            wte = getattr(people[p], 'wte', 1.0) or 1.0
            if getattr(people[p], 'grade', '') == 'Registrar' and base_shift in ('LD','N'):
                if getattr(people[p], 'comet_eligible', False):
                    wte *= problem.weights.comet_ldn_share_factor
            wte = max(0.2, min(1.0, float(wte)))
            scale = int(round(100 / wte))
            scales.append(scale)
        for i in range(len(group)):
            for j in range(i+1, len(group)):
                max_scale = max(scales[i], scales[j])
                diff = model.NewIntVar(0, len(days)*len(comp_shifts)*max_scale, f"fair_{label}_{group[i]}_{group[j]}")
                model.Add(diff >= totals[i]*scales[i] - totals[j]*scales[j])
                model.Add(diff >= totals[j]*scales[j] - totals[i]*scales[i])
                terms.append(W.fairness_variance * diff)

    # Apply fairness to core cover shifts by grade
    if nights_only:
        add_pairwise_fairness(sho_ids, 'N',  'sho_n')
        add_pairwise_fairness_composite(reg_ids, ['N','CMN'],  'reg_n_equiv', base_shift='N')
    else:
        add_pairwise_fairness(sho_ids, 'LD', 'sho_ld')
        add_pairwise_fairness(sho_ids, 'N',  'sho_n')
        # Registrars: treat CMD as LD and CMN as N for fairness
        add_pairwise_fairness_composite(reg_ids, ['LD','CMD'], 'reg_ld_equiv', base_shift='LD')
        add_pairwise_fairness_composite(reg_ids, ['N','CMN'],  'reg_n_equiv', base_shift='N')


    # Fairness bands: keep each person's LD and N within ±15% of their WTE-proportional share (over active window)
    band = 0.15
    # Determine active day counts per person (from their effective start)
    eff_starts = [getattr(p, 'start_date', None) or problem.config.start_date for p in people]
    # For each group and shift type, compute target and apply band penalties
    def apply_band(group: list[int], shift_code: str, label: str):
        if not group:
            return
        # Build totals and active-day masks
        totals = []
        active_days = []
        for p in group:
            t = model.NewIntVar(0, len(days), f"band_tot_{label}_p{p}")
            # Count only days at/after person's start
            day_terms = []
            for d_idx, d in enumerate(days):
                if d >= eff_starts[p]:
                    day_terms.append(x[p, d_idx, shift_code])
            if day_terms:
                model.Add(t == sum(day_terms))
            else:
                model.Add(t == 0)
            totals.append(t)
            active_cnt = sum(1 for d in days if d >= eff_starts[p])
            active_days.append(active_cnt)

        # Total expected cover for this shift across the horizon
        # For LD: one per day for this grade; for N: one per day for this grade
        total_cover = 0
        for d in days:
            total_cover += 1  # exactly one per day per grade for LD or N

        # Compute each person's WTE-based target share and enforce soft band
        # We approximate WTE scaling with integer math by multiplying by 100
        # Adjust expected share: COMET-eligible registrars should do fewer LD/N, so we scale their weight down
        # Use W.comet_ldn_share_factor for eligible registrars (default 0.8)
        adj = []
        for p in group:
            base = (getattr(people[p], 'wte', 1.0) or 1.0)
            if getattr(people[p], 'grade', '') == 'Registrar' and (shift_code in ('LD','N')):
                if getattr(people[p], 'comet_eligible', False):
                    base *= problem.weights.comet_ldn_share_factor
            adj.append(int(round(base * 100)))
        wtes = adj
        for idx, p in enumerate(group):
            # Expected share proportional to WTE and active days
            # Scale total_cover by ratio of (wte_p * active_days_p) / sum(wte_q * active_days_q)
            numer = wtes[idx] * active_days[idx]
            denom = sum(wtes[j] * active_days[j] for j in range(len(group))) or 1
            # target_scaled = total_cover * numer / denom
            # Use integer bounds with ±15% band, but apply small-number smoothing:
            # if target < 2 shifts, allow an absolute ±1 around target instead of ±15%.
            # To avoid fractional rounding issues, compute target in thousandths
            target_thou = total_cover * numer * 1000 // denom
            if target_thou < 2000:
                lower = max(0, target_thou - 1000)
                upper = target_thou + 1000
            else:
                lower = (target_thou * (1000 - int(band*1000))) // 1000
                upper = (target_thou * (1000 + int(band*1000))) // 1000
            # Create scaled total in thousandths (totals[idx] * 1000)
            scaled_total_thou = model.NewIntVar(0, len(days)*1000, f"band_scaled_{label}_p{p}")
            model.Add(scaled_total_thou == totals[idx] * 1000)
            # Deviations below and above band
            dev_low = model.NewIntVar(0, len(days)*1000, f"band_dev_low_{label}_p{p}")
            dev_high = model.NewIntVar(0, len(days)*1000, f"band_dev_high_{label}_p{p}")
            model.Add(dev_low >= lower - scaled_total_thou)
            model.Add(dev_low >= 0)
            model.Add(dev_high >= scaled_total_thou - upper)
            model.Add(dev_high >= 0)
            # Add to objective with moderate weight
            terms.append(problem.weights.fairness_band_penalty * (dev_low + dev_high))

    if nights_only:
        apply_band(sho_ids, 'N',  'band_sho_n')
    else:
        apply_band(sho_ids, 'LD', 'band_sho_ld')
        apply_band(sho_ids, 'N',  'band_sho_n')
    # Composite banding for registrars: LD-equivalent (LD + CMD), N-equivalent (N + CMN)
    def apply_band_composite(group: list[int], comps: list[str], label: str, base_shift: str):
        if not group:
            return
        totals = []
        active_days = []
        for p in group:
            t = model.NewIntVar(0, len(days) * len(comps), f"band_tot_{label}_p{p}")
            day_terms = []
            for d_idx, d in enumerate(days):
                if d >= eff_starts[p]:
                    day_terms.append(sum(x[p, d_idx, s] for s in comps))
            if day_terms:
                model.Add(t == sum(day_terms))
            else:
                model.Add(t == 0)
            totals.append(t)
            active_cnt = sum(1 for d in days if d >= eff_starts[p])
            active_days.append(active_cnt)
        # Compute total cover across horizon: base one per day for base_shift plus COMET component on COMET weeks
        def is_comet_day(day: dt.date) -> bool:
            for monday in problem.config.comet_on_weeks:
                if (monday == day and day.weekday()==0) or (monday <= day <= monday + dt.timedelta(days=6)):
                    return True
            return False
        comet_days_count = sum(1 for d in days if is_comet_day(d))
        total_cover = len(days)
        if base_shift == 'LD' and 'CMD' in comps:
            total_cover += comet_days_count
        if base_shift == 'N' and 'CMN' in comps:
            total_cover += comet_days_count
        # WTE-based targets with COMET adjustment for eligible registrars
        wtes = []
        for p in group:
            base = (getattr(people[p], 'wte', 1.0) or 1.0)
            if getattr(people[p], 'grade', '') == 'Registrar' and base_shift in ('LD','N'):
                if getattr(people[p], 'comet_eligible', False):
                    base *= problem.weights.comet_ldn_share_factor
            wtes.append(int(round(base * 100)))
        for idx, p in enumerate(group):
            numer = wtes[idx] * active_days[idx]
            denom = sum(wtes[j] * active_days[j] for j in range(len(group))) or 1
            target_thou = total_cover * numer * 1000 // denom
            if target_thou < 2000:
                lower = max(0, target_thou - 1000)
                upper = target_thou + 1000
            else:
                lower = (target_thou * 850) // 1000
                upper = (target_thou * 1150) // 1000
            scaled_total_thou = model.NewIntVar(0, len(days)*len(comps)*1000, f"band_scaled_{label}_p{p}")
            model.Add(scaled_total_thou == totals[idx] * 1000)
            dev_low = model.NewIntVar(0, len(days)*len(comps)*1000, f"band_dev_low_{label}_p{p}")
            dev_high = model.NewIntVar(0, len(days)*len(comps)*1000, f"band_dev_high_{label}_p{p}")
            model.Add(dev_low >= lower - scaled_total_thou)
            model.Add(dev_low >= 0)
            model.Add(dev_high >= scaled_total_thou - upper)
            model.Add(dev_high >= 0)
            terms.append(problem.weights.fairness_band_penalty * (dev_low + dev_high))

    if nights_only:
        apply_band_composite(reg_ids, ['N','CMN'],  'band_reg_n_equiv',  base_shift='N')
    else:
        apply_band_composite(reg_ids, ['LD','CMD'], 'band_reg_ld_equiv', base_shift='LD')
        apply_band_composite(reg_ids, ['N','CMN'],  'band_reg_n_equiv',  base_shift='N')

    # Weekend continuity preference:
    # For each weekend, encourage at least one of the two LD clinicians (Reg/SHO) to also work Fri SD and Mon SD.
    # Implement as a small bonus (negative cost) when continuity holds; otherwise neutral (no penalty).
    # Note: Using negative weight via addition of (0 - bonus * indicator).
    W = problem.weights
    for i in range(len(days)):
        if days[i].weekday() == 5 and i+1 < len(days) and days[i+1].weekday() == 6:
            sat = i
            sun = i + 1
            fri = i-1 if i-1 >= 0 and days[i-1].weekday() == 5-1 else None
            mon = i+2 if i+2 < len(days) and days[i+2].weekday() == 0 else None
            if fri is not None:
                # Continuity if registrar LD Sat/Sun and same registrar has Fri SD
                for p in reg_ids:
                    cont = model.NewBoolVar(f"cont_reg_fri_p{p}_sat{sat}")
                    model.AddMinEquality(cont, [x[p, sat, 'LD'], x[p, fri, 'SD']])
                    terms.append(-W.weekend_continuity_bonus * cont)
                for p in sho_ids:
                    cont = model.NewBoolVar(f"cont_sho_fri_p{p}_sat{sat}")
                    model.AddMinEquality(cont, [x[p, sat, 'LD'], x[p, fri, 'SD']])
                    terms.append(-W.weekend_continuity_bonus * cont)
            if mon is not None:
                for p in reg_ids:
                    cont = model.NewBoolVar(f"cont_reg_mon_p{p}_sat{sat}")
                    model.AddMinEquality(cont, [x[p, sun, 'LD'], x[p, mon, 'SD']])
                    terms.append(-W.weekend_continuity_bonus * cont)
                for p in sho_ids:
                    cont = model.NewBoolVar(f"cont_sho_mon_p{p}_sat{sat}")
                    model.AddMinEquality(cont, [x[p, sun, 'LD'], x[p, mon, 'SD']])
                    terms.append(-W.weekend_continuity_bonus * cont)

    # Nights preference:
    # Prefer a short day before Thu-Mon night runs and some crossover where possible.
    for d in range(len(days)):
        dow = days[d].weekday()
        # If Thursday night (dow=3) starting a run, bonus if same person does Thu SD
        if dow == 4-1 and d+1 < len(days):
            for p in reg_ids + sho_ids:
                b = model.NewBoolVar(f"pref_sd_before_night_p{p}_d{d}")
                model.AddMinEquality(b, [x[p, d, 'SD'], x[p, d+1, 'N']])
                terms.append(-W.nights_pref_sd_before_bonus * b)
        # Encourage crossover: if two different clinicians cover N on Fri/Sat/Sun/Mon, mild bonus for overlapping one SD
        # Approximate by rewarding any SD on the same day by a clinician who is on N the day before/after
        if d > 0:
            for p in reg_ids + sho_ids:
                cross = model.NewBoolVar(f"night_crossover_prev_p{p}_d{d}")
                model.AddMinEquality(cross, [x[p, d-1, 'N'], x[p, d, 'SD']])
                terms.append(-W.nights_crossover_bonus * cross)
        if d+1 < len(days):
            for p in reg_ids + sho_ids:
                cross = model.NewBoolVar(f"night_crossover_next_p{p}_d{d}")
                model.AddMinEquality(cross, [x[p, d+1, 'N'], x[p, d, 'SD']])
                terms.append(-W.nights_crossover_bonus * cross)

    model.Minimize(sum(terms))
