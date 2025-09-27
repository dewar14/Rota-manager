from ortools.sat.python import cp_model
from typing import Dict, Tuple
import datetime as dt
import math
from dateutil.rrule import rrule, DAILY
from rostering.models import ProblemInput, Shift

ShiftCode = str
Var = cp_model.IntVar

def daterange(start: dt.date, end: dt.date):
    for d in rrule(DAILY, dtstart=start, until=end):
        yield d.date()

def is_weekend(d: dt.date) -> bool:
    return d.weekday() >= 5

def is_monday(d: dt.date) -> bool:
    return d.weekday() == 0

def is_day_in_comet_week(day: dt.date, comet_mondays: list[dt.date]) -> bool:
    """Return True when *day* falls inside one of the configured COMET weeks."""

    for monday in comet_mondays:
        if monday <= day <= monday + dt.timedelta(days=6):
            return True
    return False

def build_index(problem: ProblemInput):
    # Calendar
    days = list(daterange(problem.config.start_date, problem.config.end_date))
    day_index = {d:i for i,d in enumerate(days)}
    # People filtered by effective start_date (default to rota start when missing)
    people = [p for p in problem.people if ((p.start_date or problem.config.start_date) <= problem.config.end_date)]
    person_index = {p.id:i for i,p in enumerate(people)}
    return days, day_index, people, person_index

def basic_shift_catalog() -> dict[str, Shift]:
    """Return the canonical shift catalogue used by the solver.

    The catalogue mirrors the specification shared with rota owners so that
    the solver, admin UI, and downstream reports agree on shift codes, labels,
    working hours, and whether the shift should be counted towards unit cover.
    """

    return {
        "SD": Shift(code="SD", label="Short Day", hours=9.0, count_in_cover=True),
        "LDS": Shift(
            code="LDS",
            label="Long Day SHO",
            hours=13.0,
            count_in_cover=True,
            grade_requirement="SHO",
        ),
        "LDR": Shift(
            code="LDR",
            label="Long Day Registrar",
            hours=13.0,
            count_in_cover=True,
            grade_requirement="Registrar",
        ),
        "NS": Shift(
            code="NS",
            label="Night SHO",
            hours=13.0,
            count_in_cover=True,
            grade_requirement="SHO",
        ),
        "NR": Shift(
            code="NR",
            label="Night Registrar",
            hours=13.0,
            count_in_cover=True,
            grade_requirement="Registrar",
        ),
        "CMD": Shift(
            code="CMD",
            label="CoMET Day",
            hours=12.0,
            count_in_cover=True,
            grade_requirement="Registrar",
        ),
        "CMN": Shift(
            code="CMN",
            label="CoMET Night",
            hours=12.0,
            count_in_cover=True,
            grade_requirement="Registrar",
        ),
        "CPD": Shift(code="CPD", label="CPD", hours=9.0, count_in_cover=False),
        "TREG": Shift(code="TREG", label="Registrar Teaching", hours=9.0, count_in_cover=False),
        "TSHO": Shift(code="TSHO", label="SHO Teaching", hours=9.0, count_in_cover=False),
        "TPCCU": Shift(code="TPCCU", label="Unit Teaching", hours=9.0, count_in_cover=False),
        "IND": Shift(code="IND", label="Induction", hours=9.0, count_in_cover=False),
        "LV": Shift(code="LV", label="Leave", hours=9.0, count_in_cover=False),
        "SLV": Shift(code="SLV", label="Study Leave", hours=9.0, count_in_cover=False),
        "LTFT": Shift(code="LTFT", label="LTFT Day", hours=0.0, count_in_cover=False),
        "OFF": Shift(code="OFF", label="Off", hours=0.0, count_in_cover=False),
        # Locum is a virtual slack variable added at the coverage stage only
        "LOC": Shift(code="LOC", label="Locum", hours=0.0, count_in_cover=True),
    }


SHIFT_LIBRARY: dict[str, Shift] = basic_shift_catalog()

# Person-assignable shift codes exclude the virtual "LOC" slack variables.
PERSON_SHIFT_CODES: list[str] = [code for code in SHIFT_LIBRARY if code != "LOC"]

# Working shift codes count towards hours worked and rest requirements.
WORK_SHIFT_CODES: list[str] = [
    code for code in PERSON_SHIFT_CODES if code not in {"OFF", "LTFT"}
]

NIGHT_SHIFT_CODES: list[str] = ["NS", "NR", "CMN"]
MANDATORY_SHIFT_CODES: list[str] = ["LDS", "LDR", "NS", "NR", "CMD", "CMN"]

# Long shifts are duties longer than 10 hours (used for rest sequencing).
LONG_SHIFT_CODES: list[str] = [
    code for code in WORK_SHIFT_CODES if SHIFT_LIBRARY[code].hours > 10
]

# Hours counted towards weekly totals exclude non-working days and locums.
HOURS_BY_SHIFT: dict[str, int] = {
    code: int(round(shift.hours))
    for code, shift in SHIFT_LIBRARY.items()
    if code not in {"OFF", "LTFT", "LOC"}
}

def add_core_constraints(problem: ProblemInput, model: cp_model.CpModel, options: dict | None = None):
    options = options or {}
    nights_only: bool = bool(options.get('nights_only', False))
    freeze_nights: list[tuple[int,int,str]] = options.get('freeze_nights', []) or []
    days, day_index, people, person_index = build_index(problem)
    # S = basic_shift_catalog()
    P = range(len(people))
    D = range(len(days))
    shift_codes = PERSON_SHIFT_CODES
    # Decision vars: x[p,d,s] ∈ {0,1}
    x: Dict[Tuple[int,int,str], Var] = {}
    for p in P:
        for d in D:
            for s in shift_codes:
                x[p,d,s] = model.NewBoolVar(f"x_p{p}_d{d}_{s}")
    # Apply freeze for nights if provided
    if freeze_nights:
        for (pidx, didx, scode) in freeze_nights:
            if scode in ("NS","NR","CMN") and 0 <= pidx < len(people) and 0 <= didx < len(days):
                model.Add(x[pidx, didx, scode] == 1)
                # Optional: encourage uniqueness by zeroing others for same day/shift
                for q in P:
                    if q != pidx:
                        model.Add(x[q, didx, scode] == 0)
    # Locum coverage slack per day/shift category (for cover counts)
    loc_ld_reg = [model.NewIntVar(0, 1, f"loc_ld_reg_d{d}") for d in D]
    loc_ld_sho = [model.NewIntVar(0, 1, f"loc_ld_sho_d{d}") for d in D]
    loc_sd_any = [model.NewIntVar(0, 3, f"loc_sd_any_d{d}") for d in D]
    loc_n_reg  = [model.NewIntVar(0, 1, f"loc_n_reg_d{d}")  for d in D]
    loc_n_sho  = [model.NewIntVar(0, 1, f"loc_n_sho_d{d}")  for d in D]
    loc_cmd    = [model.NewIntVar(0, 1, f"loc_cmd_d{d}")    for d in D]
    loc_cmn    = [model.NewIntVar(0, 1, f"loc_cmn_d{d}")    for d in D]

    weekend_count_vars: Dict[int, Var] = {}
    weekend_firm_over: Dict[int, Var] = {}
    weekend_firm_caps: Dict[int, int] = {}

    registrar_training_totals: Dict[int, Var] = {}
    sho_training_totals: Dict[int, Var] = {}
    unit_training_totals: Dict[int, Var] = {}

    training_gap_flags: list[Var] = []
    on_mandatory_flags: Dict[Tuple[int, int], Var] = {}

    # Helper sets (normalize grade names defensively)
    def gnorm(g: str | None) -> str:
        return (g or "").strip().lower()
    reg_ids = {i for i,p in enumerate(people) if gnorm(getattr(p, 'grade', None)) == "registrar"}
    sho_ids = {i for i,p in enumerate(people) if gnorm(getattr(p, 'grade', None)) == "sho"}
    sup_ids = {i for i,p in enumerate(people) if gnorm(getattr(p, 'grade', None)) == "supernumerary"}

    # Enforce grade requirements declared in the shift catalogue
    for code, shift in SHIFT_LIBRARY.items():
        if shift.grade_requirement:
            if shift.grade_requirement == "Registrar":
                allowed = reg_ids
            elif shift.grade_requirement == "SHO":
                allowed = sho_ids
            else:
                allowed = set()
            for p in P:
                if p not in allowed:
                    for d in D:
                        model.Add(x[p, d, code] == 0)

    def person_long_day_code(p_idx: int) -> str | None:
        grade = getattr(people[p_idx], "grade", None)
        if grade == "Registrar":
            return "LDR"
        if grade == "SHO":
            return "LDS"
        return None

    def person_night_code(p_idx: int) -> str | None:
        grade = getattr(people[p_idx], "grade", None)
        if grade == "Registrar":
            return "NR"
        if grade == "SHO":
            return "NS"
        return None

    def canonical_shift_code(raw: str, p_idx: int) -> str:
        if raw == "LD":
            return person_long_day_code(p_idx) or raw
        if raw == "N":
            return person_night_code(p_idx) or raw
        return raw

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
    banned_for_sup = ["LDR","LDS","NR","NS","CMD","CMN"]
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
                    model.Add(
                        sum(
                            x[p_idx, d_idx, s]
                            for s in shift_codes
                            if s not in {"OFF", "LTFT"}
                        )
                        == 0
                    )

    # 4) Coverage requirements
    comet_mondays = problem.config.comet_on_weeks or []
    comet_days_mask = [is_day_in_comet_week(day, comet_mondays) for day in days]
    bank_holidays = set(problem.config.bank_holidays or [])
    weekend_mask = [is_weekend(day) for day in days]

    for d_idx, day in enumerate(days):
        wknd = weekend_mask[d_idx] or (day in bank_holidays)
        comet_on = comet_days_mask[d_idx]
        if not nights_only:
            # Long Days
            # SHO LD: always exactly 1 (weekday/weekend alike), with locum slack
            model.Add(sum(x[p,d_idx,"LDS"] for p in sho_ids) + loc_ld_sho[d_idx] == 1)
            # Registrar LD: always exactly 1, with locum slack
            model.Add(sum(x[p,d_idx,"LDR"] for p in reg_ids) + loc_ld_reg[d_idx] == 1)
            # COMET Day: additional registrar on COMET weeks
            if comet_on:
                model.Add(sum(x[p,d_idx,"CMD"] for p in reg_ids) + loc_cmd[d_idx] == 1)
                for p in reg_ids:
                    if not getattr(people[p], 'comet_eligible', False):
                        model.Add(x[p,d_idx,"CMD"] == 0)
            else:
                for p in P:
                    model.Add(x[p,d_idx,"CMD"] == 0)
                model.Add(loc_cmd[d_idx] == 0)

            # Short Day: disable SDs on weekends/bank holidays and on global induction days; otherwise use weekday targets
            induction_day = day in (problem.config.global_induction_days or [])
            if induction_day:
                # Everyone not on cover should attend induction; do not schedule SD and no SD locum expectation
                for p in P:
                    model.Add(x[p,d_idx,"SD"] == 0)
                model.Add(loc_sd_any[d_idx] == 0)
            elif not wknd:
                MIN_SD = 1
                MAX_SD = 3
                sd_sum = sum(x[p,d_idx,"SD"] for p in P if p not in sup_ids)
                model.Add(sd_sum + loc_sd_any[d_idx] >= MIN_SD)
                model.Add(sd_sum <= MAX_SD)
            else:
                for p in P:
                    model.Add(x[p,d_idx,"SD"] == 0)
                model.Add(loc_sd_any[d_idx] == 0)

        # Nights
        # SHO N: always exactly 1, with locum slack
        model.Add(sum(x[p,d_idx,"NS"] for p in sho_ids) + loc_n_sho[d_idx] == 1)
        # Registrar N: always exactly 1, with locum slack
        model.Add(sum(x[p,d_idx,"NR"] for p in reg_ids) + loc_n_reg[d_idx] == 1)
        # COMET Night: additional registrar on COMET weeks
        if comet_on:
            model.Add(sum(x[p,d_idx,"CMN"] for p in reg_ids) + loc_cmn[d_idx] == 1)
            for p in reg_ids:
                if not getattr(people[p], 'comet_eligible', False):
                    model.Add(x[p,d_idx,"CMN"] == 0)
        else:
            for p in P:
                model.Add(x[p,d_idx,"CMN"] == 0)
            model.Add(loc_cmn[d_idx] == 0)

    # Build helper flags for rest/sequence constraints
    night_flag: Dict[Tuple[int, int], Var] = {}
    long_flag: Dict[Tuple[int, int], Var] = {}
    work_flag: Dict[Tuple[int, int], Var] = {}
    for p in P:
        for d in D:
            nf = model.NewBoolVar(f"night_flag_p{p}_d{d}")
            model.Add(nf == sum(x[p, d, s] for s in NIGHT_SHIFT_CODES))
            night_flag[p, d] = nf

            lf = model.NewBoolVar(f"long_flag_p{p}_d{d}")
            model.Add(lf == sum(x[p, d, s] for s in LONG_SHIFT_CODES))
            long_flag[p, d] = lf

            wf = model.NewBoolVar(f"work_flag_p{p}_d{d}")
            model.Add(wf == sum(x[p, d, s] for s in WORK_SHIFT_CODES))
            work_flag[p, d] = wf

    # 5) 46-hour rest after completing a block of nights (two clear calendar days)
    for p in P:
        for d in D:
            if d + 1 >= len(D):
                continue
            end_block = model.NewBoolVar(f"night_block_end_p{p}_d{d}")
            model.Add(end_block <= night_flag[p, d])
            if d + 1 < len(D):
                model.Add(end_block <= 1 - night_flag[p, d + 1])
                model.Add(end_block >= night_flag[p, d] - night_flag[p, d + 1])
            else:
                model.Add(end_block == night_flag[p, d])
            rest_codes = WORK_SHIFT_CODES
            if d + 1 < len(D):
                model.Add(sum(x[p, d + 1, s] for s in rest_codes) == 0).OnlyEnforceIf(end_block)
            if d + 2 < len(D):
                model.Add(sum(x[p, d + 2, s] for s in rest_codes) == 0).OnlyEnforceIf(end_block)

    # 6) Max 72 hours in any rolling 7-day window
    for p in P:
        for start in range(len(D)-6):
            expr = []
            for d in range(start, start+7):
                expr += [x[p,d,s]*HOURS_BY_SHIFT[s] for s in HOURS_BY_SHIFT]
            model.Add(sum(expr) <= 72)

    # 7) Additional sequence constraints
    # 7a) No singleton nights (min 2 in any contiguous block of nights)
    for p in P:
        for d in D:
            if d > 0 and d < len(D)-1:
                model.Add(
                    sum(x[p, d, s] for s in NIGHT_SHIFT_CODES)
                    <= sum(x[p, d - 1, s] for s in NIGHT_SHIFT_CODES)
                    + sum(x[p, d + 1, s] for s in NIGHT_SHIFT_CODES)
                )

    # 7b) Max 4 consecutive nights
    for p in P:
        for start in range(len(D)-4):
            model.Add(
                sum(
                    sum(x[p, d, s] for s in NIGHT_SHIFT_CODES)
                    for d in range(start, start + 5)
                )
                <= 4
            )

    # 7c) Require at least five clear days between night blocks (prevents back-to-back blocks)
    for p in P:
        for d in D:
            if d + 4 >= len(D):
                continue
            block_any = model.NewBoolVar(f"night_block_any_p{p}_d{d}")
            window = []
            for offset in range(4):
                if d + offset >= len(D):
                    continue
                b = model.NewBoolVar(f"night_any_p{p}_d{d}_o{offset}")
                model.Add(b == sum(x[p, d + offset, s] for s in NIGHT_SHIFT_CODES))
                window.append(b)
            if not window:
                model.Add(block_any == 0)
                continue
            model.AddMaxEquality(block_any, window)
            future_terms = []
            for future in range(d + 4, min(d + 9, len(D))):
                future_terms.extend(x[p, future, s] for s in NIGHT_SHIFT_CODES)
            if future_terms:
                model.Add(sum(future_terms) == 0).OnlyEnforceIf(block_any)

    # 7d) Long-shift sequencing: no more than four consecutive long shifts and rest afterwards
    for p in P:
        for start in range(len(D) - 4):
            model.Add(sum(long_flag[p, start + k] for k in range(5)) <= 4)
        for d in range(3, len(D)):
            block4 = model.NewBoolVar(f"long_block4_end_p{p}_d{d}")
            model.Add(block4 <= long_flag[p, d])
            model.Add(block4 <= long_flag[p, d-1])
            model.Add(block4 <= long_flag[p, d-2])
            model.Add(block4 <= long_flag[p, d-3])
            model.Add(block4 >= long_flag[p, d] + long_flag[p, d-1] + long_flag[p, d-2] + long_flag[p, d-3] - 3)
            if d + 1 < len(D):
                model.Add(sum(x[p, d + 1, s] for s in WORK_SHIFT_CODES) == 0).OnlyEnforceIf(block4)
            if d + 2 < len(D):
                model.Add(sum(x[p, d + 2, s] for s in WORK_SHIFT_CODES) == 0).OnlyEnforceIf(block4)

    # 7e) Max 7 consecutive worked days and mandatory rest afterwards
    for p in P:
        for start in range(len(D)-7):
            model.Add(sum(work_flag[p, start + k] for k in range(8)) <= 7)
        for d in range(6, len(D)):
            terms = [work_flag[p, d - k] for k in range(7) if d - k >= 0]
            if len(terms) < 7:
                continue
            block7 = model.NewBoolVar(f"work_block7_end_p{p}_d{d}")
            for t in terms:
                model.Add(block7 <= t)
            model.Add(block7 >= sum(terms) - 6)
            if d + 1 < len(D):
                model.Add(sum(x[p, d + 1, s] for s in WORK_SHIFT_CODES) == 0).OnlyEnforceIf(block7)
            if d + 2 < len(D):
                model.Add(sum(x[p, d + 2, s] for s in WORK_SHIFT_CODES) == 0).OnlyEnforceIf(block7)

    # 7f) Weekend frequency hard cap: at most one weekend in two (scaled by WTE)
    weekend_blocks = []
    for i in range(len(days)-1):
        if days[i].weekday() == 5:
            weekend_blocks.append((i, i + 1 if days[i + 1].weekday() == 6 else None))
    total_weekends = len(weekend_blocks)
    weekend_flags: Dict[int, list[Var]] = {p: [] for p in P}
    for p in P:
        wknd_flags = []
        for idx, (sat_idx, sun_idx) in enumerate(weekend_blocks):
            terms = []
            for s in WORK_SHIFT_CODES:
                terms.append(x[p, sat_idx, s])
                if sun_idx is not None:
                    terms.append(x[p, sun_idx, s])
            if not terms:
                continue
            worked = model.NewBoolVar(f"wknd_work_p{p}_b{idx}")
            model.Add(sum(terms) >= 1).OnlyEnforceIf(worked)
            model.Add(sum(terms) == 0).OnlyEnforceIf(worked.Not())
            wknd_flags.append(worked)
        weekend_flags[p] = wknd_flags
        wte = getattr(people[p], 'wte', 1.0) or 1.0
        wte = max(0.2, min(1.0, float(wte)))
        if wknd_flags and total_weekends > 0:
            cap = math.ceil(total_weekends * wte / 2)
            model.Add(sum(wknd_flags) <= cap)

    # Pre-compute availability fractions for fairness bounds
    horizon_days = len(days)
    comet_day_count = sum(1 for flag in comet_days_mask if flag)
    availability_day_fraction: list[float] = []
    availability_weekend_fraction: list[float] = []
    for p_idx, person in enumerate(people):
        eff_start = person.start_date or problem.config.start_date
        active_days = sum(1 for d in days if d >= eff_start)
        availability_day_fraction.append((active_days / horizon_days) if horizon_days else 0.0)
        if total_weekends:
            active_weekends = 0
            for sat_idx, sun_idx in weekend_blocks:
                sat_day = days[sat_idx]
                sun_day = days[sun_idx] if sun_idx is not None else None
                if sat_day >= eff_start or (sun_day and sun_day >= eff_start):
                    active_weekends += 1
            availability_weekend_fraction.append(active_weekends / total_weekends)
        else:
            availability_weekend_fraction.append(0.0)

    # Aggregate totals for fairness and hours calculations
    registrar_ld_totals: Dict[int, Var] = {}
    registrar_n_totals: Dict[int, Var] = {}
    registrar_weekend_totals: Dict[int, Var] = {}
    sho_ld_totals: Dict[int, Var] = {}
    sho_n_totals: Dict[int, Var] = {}
    sho_weekend_totals: Dict[int, Var] = {}
    total_hours: Dict[int, Var] = {}

    for p in P:
        total_h = model.NewIntVar(0, horizon_days * 13, f"total_hours_p{p}")
        model.Add(
            total_h
            == sum(
                x[p, d, s] * HOURS_BY_SHIFT[s]
                for d in D
                for s in HOURS_BY_SHIFT
            )
        )
        total_hours[p] = total_h

        weekend_count = model.NewIntVar(0, total_weekends, f"weekend_blocks_p{p}")
        flags = weekend_flags.get(p, [])
        if flags:
            model.Add(weekend_count == sum(flags))
        else:
            model.Add(weekend_count == 0)
        weekend_count_vars[p] = weekend_count

        if total_weekends:
            wte = getattr(people[p], 'wte', 1.0) or 1.0
            wte = max(0.2, min(1.0, float(wte)))
            firm_cap = math.ceil(total_weekends * wte / 3)
            weekend_firm_caps[p] = firm_cap
            firm_over = model.NewIntVar(0, total_weekends, f"weekend_firm_over_p{p}")
            model.Add(firm_over >= weekend_count - firm_cap)
            model.Add(firm_over >= 0)
            weekend_firm_over[p] = firm_over
        else:
            weekend_firm_caps[p] = 0

        grade = getattr(people[p], 'grade', None)
        if grade == "Registrar":
            ld_total = model.NewIntVar(0, horizon_days + comet_day_count, f"reg_ld_total_p{p}")
            model.Add(ld_total == sum(x[p, d, 'LDR'] for d in D) + sum(x[p, d, 'CMD'] for d in D))
            registrar_ld_totals[p] = ld_total

            n_total = model.NewIntVar(0, horizon_days + comet_day_count, f"reg_n_total_p{p}")
            model.Add(n_total == sum(x[p, d, 'NR'] for d in D) + sum(x[p, d, 'CMN'] for d in D))
            registrar_n_totals[p] = n_total

            registrar_weekend_totals[p] = weekend_count
        elif grade == "SHO":
            ld_total = model.NewIntVar(0, horizon_days, f"sho_ld_total_p{p}")
            model.Add(ld_total == sum(x[p, d, 'LDS'] for d in D))
            sho_ld_totals[p] = ld_total

            n_total = model.NewIntVar(0, horizon_days, f"sho_n_total_p{p}")
            model.Add(n_total == sum(x[p, d, 'NS'] for d in D))
            sho_n_totals[p] = n_total

            sho_weekend_totals[p] = weekend_count

    # Average weekly hours hard band (42-47 hours per WTE)
    weeks = horizon_days / 7.0 if horizon_days else 0.0
    if weeks > 0:
        for p in P:
            wte = getattr(people[p], 'wte', 1.0) or 1.0
            wte = max(0.2, min(1.0, float(wte)))
            min_hours = math.floor(42 * weeks * wte - 1e-6)
            max_hours = math.ceil(47 * weeks * wte + 1e-6)
            model.Add(total_hours[p] >= min_hours)
            model.Add(total_hours[p] <= max_hours)

    def enforce_wte_band(group: list[int], totals: Dict[int, Var], total_required: int, availability: list[float], label: str):
        if not group or total_required <= 0:
            return
        weights = []
        for p in group:
            wte = getattr(people[p], 'wte', 1.0) or 1.0
            wte = max(0.2, min(1.0, float(wte)))
            weight = wte * availability[p]
            weights.append(weight)
        total_weight = sum(weights)
        if total_weight <= 0:
            return
        for idx, p in enumerate(group):
            weight = weights[idx]
            lower = math.floor(total_required * weight / total_weight * 0.75 - 1e-6)
            upper = math.ceil(total_required * weight / total_weight * 1.25 + 1e-6)
            lower = max(0, lower)
            if upper < lower:
                upper = lower
            model.Add(totals[p] >= lower)
            model.Add(totals[p] <= upper)

    reg_list = sorted(registrar_ld_totals.keys())
    sho_list = sorted(sho_ld_totals.keys())

    enforce_wte_band(reg_list, registrar_ld_totals, horizon_days + comet_day_count, availability_day_fraction, "reg_ld")
    enforce_wte_band(reg_list, registrar_n_totals, horizon_days + comet_day_count, availability_day_fraction, "reg_n")
    enforce_wte_band(sho_list, sho_ld_totals, horizon_days, availability_day_fraction, "sho_ld")
    enforce_wte_band(sho_list, sho_n_totals, horizon_days, availability_day_fraction, "sho_n")
    enforce_wte_band(reg_list, registrar_weekend_totals, total_weekends, availability_weekend_fraction, "reg_weekend")
    enforce_wte_band(sho_list, sho_weekend_totals, total_weekends, availability_weekend_fraction, "sho_weekend")

    # Build preassignment map to gate global auto-assignments
    pid_to_idx = {p.id:i for i,p in enumerate(people)}
    pre_any = set()
    forced_assignments: Dict[Tuple[int, int], str] = {}
    try:
        _pre = getattr(problem, 'preassignments', []) or []
        for item in _pre:
            pid = item.get('person_id')
            date = item.get('date')
            shift = item.get('shift_code')
            if pid in pid_to_idx and shift:
                pidx = pid_to_idx[pid]
                shift_norm = canonical_shift_code(shift, pidx)
                if shift_norm in shift_codes:
                    d = dt.date.fromisoformat(date)
                    if d in day_index:
                        didx = day_index[d]
                        pre_any.add((pidx, didx))
                        if shift_norm in {"LV", "SLV", "LTFT", "CPD", "OFF"}:
                            forced_assignments[(pidx, didx)] = shift_norm
    except Exception:
        pass

    for (pidx, didx), code in forced_assignments.items():
        model.Add(x[pidx, didx, code] == 1)
        for other in shift_codes:
            if other != code:
                model.Add(x[pidx, didx, other] == 0)

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
            mand = [x[p_idx, d_idx, s] for s in MANDATORY_SHIFT_CODES]
            on_mand = model.NewBoolVar(f"on_mand_p{p_idx}_d{d_idx}")
            model.Add(sum(mand) >= 1).OnlyEnforceIf(on_mand)
            model.Add(sum(mand) == 0).OnlyEnforceIf(on_mand.Not())
            on_mandatory_flags[(p_idx, d_idx)] = on_mand

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
                # Track non-attendance when free so we can add a soft penalty and report breaches
                if (p_idx, d_idx) not in forced_assignments:
                    train_sum = sum(x[p_idx, d_idx, code] for code in present)
                    gap = model.NewBoolVar(f"training_gap_p{p_idx}_d{d_idx}")
                    model.Add(gap == 0).OnlyEnforceIf(on_mand)
                    model.Add(gap + train_sum == 1).OnlyEnforceIf(on_mand.Not())
                    training_gap_flags.append(gap)

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

    # Build training attendance totals for fairness tracking
    treg_days = [day_index[d] for d in g_treg if d in day_index]
    tsho_days = [day_index[d] for d in g_tsho if d in day_index]
    unit_days = [day_index[d] for d in g_unit if d in day_index]

    for p_idx in reg_ids:
        limit = len(treg_days)
        treg_total = model.NewIntVar(0, limit, f"treg_total_p{p_idx}")
        if treg_days:
            model.Add(treg_total == sum(x[p_idx, d, 'TREG'] for d in treg_days))
        else:
            model.Add(treg_total == 0)
        registrar_training_totals[p_idx] = treg_total

    for p_idx in sho_ids:
        limit = len(tsho_days)
        tsho_total = model.NewIntVar(0, limit, f"tsho_total_p{p_idx}")
        if tsho_days:
            model.Add(tsho_total == sum(x[p_idx, d, 'TSHO'] for d in tsho_days))
        else:
            model.Add(tsho_total == 0)
        sho_training_totals[p_idx] = tsho_total

    for p_idx in range(len(people)):
        limit = len(unit_days)
        unit_total = model.NewIntVar(0, limit, f"unit_training_total_p{p_idx}")
        if unit_days:
            model.Add(unit_total == sum(x[p_idx, d, 'TPCCU'] for d in unit_days))
        else:
            model.Add(unit_total == 0)
        unit_training_totals[p_idx] = unit_total

    # 9) Preassignments: soft-only preferences (rules always take precedence)
    pre = getattr(problem, 'preassignments', []) or []
    # Map person_id to index
    pid_to_idx = {p.id:i for i,p in enumerate(people)}
    pre_ok_flags = []
    cpd_allowed: set[tuple[int,int]] = set()
    leave_allowed: set[tuple[int,int]] = set()
    study_allowed: set[tuple[int,int]] = set()
    ltft_allowed: set[tuple[int,int]] = set()
    for item in pre:
        try:
            pid = item.get('person_id')
            date = item.get('date')
            shift = item.get('shift_code')
            if pid in pid_to_idx and shift:
                pidx = pid_to_idx[pid]
                shift_norm = canonical_shift_code(shift, pidx)
                if shift_norm in shift_codes:
                    d = dt.date.fromisoformat(date)
                    if d in day_index:
                        didx = day_index[d]
                        if shift_norm == 'CPD':
                            cpd_allowed.add((pidx, didx))
                        elif shift_norm == 'LV':
                            leave_allowed.add((pidx, didx))
                        elif shift_norm == 'SLV':
                            study_allowed.add((pidx, didx))
                        elif shift_norm == 'LTFT':
                            ltft_allowed.add((pidx, didx))
                        if (pidx, didx) in forced_assignments:
                            continue
                        # Soft preassignment: prefer, but allow violation
                        b = model.NewBoolVar(f"pre_ok_p{pidx}_d{didx}_{shift_norm}")
                        model.Add(x[pidx, didx, shift_norm] == 1).OnlyEnforceIf(b)
                        model.Add(x[pidx, didx, shift_norm] == 0).OnlyEnforceIf(b.Not())
                        pre_ok_flags.append(b)
        except Exception:
            pass

    # CPD gating: only allow CPD when explicitly preassigned
    for p in range(len(people)):
        for d in range(len(days)):
            if (p, d) not in cpd_allowed:
                model.Add(x[p,d,'CPD'] == 0)
            if (p, d) not in leave_allowed:
                model.Add(x[p,d,'LV'] == 0)
            if (p, d) not in study_allowed:
                model.Add(x[p,d,'SLV'] == 0)
            if (p, d) not in ltft_allowed:
                model.Add(x[p,d,'LTFT'] == 0)

    # Prevent teaching for those on nights same 24h (covered by rule 5)

    return x, {
        "loc_ld_reg":loc_ld_reg, "loc_ld_sho":loc_ld_sho, "loc_sd_any":loc_sd_any,
        "loc_n_reg":loc_n_reg, "loc_n_sho":loc_n_sho, "loc_cmd":loc_cmd, "loc_cmn":loc_cmn,
        "fdo_violations": fdo_violations,
        "pre_ok_flags": pre_ok_flags,
        "weekend_flags": weekend_flags,
        "registrar_ld_totals": registrar_ld_totals,
        "registrar_n_totals": registrar_n_totals,
        "sho_ld_totals": sho_ld_totals,
        "sho_n_totals": sho_n_totals,
        "registrar_weekend_totals": registrar_weekend_totals,
        "sho_weekend_totals": sho_weekend_totals,
        "weekend_count": weekend_count_vars,
        "weekend_firm_over": weekend_firm_over,
        "weekend_firm_caps": weekend_firm_caps,
        "total_hours": total_hours,
        "availability_day_fraction": availability_day_fraction,
        "availability_weekend_fraction": availability_weekend_fraction,
        "registrar_training_totals": registrar_training_totals,
        "sho_training_totals": sho_training_totals,
        "unit_training_totals": unit_training_totals,
        "training_gap_flags": training_gap_flags,
        "treg_days": treg_days,
        "tsho_days": tsho_days,
        "unit_days": unit_days,
    }, days, people

def soft_objective(problem: ProblemInput, model: cp_model.CpModel, x, locums, days, people, options: dict | None = None):
    options = options or {}
    nights_only: bool = bool(options.get('nights_only', False))
    # Assemble objective terms (coverage priorities first, then preferences)
    terms = []
    W = problem.weights

    def long_day_code(p_idx: int) -> str | None:
        grade = getattr(people[p_idx], "grade", None)
        if grade == "Registrar":
            return "LDR"
        if grade == "SHO":
            return "LDS"
        return None

    def night_codes_for_person(p_idx: int) -> list[str]:
        grade = getattr(people[p_idx], "grade", None)
        if grade == "Registrar":
            return ["NR", "CMN"]
        if grade == "SHO":
            return ["NS"]
        return []

    # Coverage priorities: penalise uncovered mandatory posts following the requested ladder.
    comet_mondays = problem.config.comet_on_weeks or []
    bank_holidays = set(problem.config.bank_holidays or [])
    for d_idx, day in enumerate(days):
        comet_week = is_day_in_comet_week(day, comet_mondays)
        is_bank_holiday = day in bank_holidays
        is_weekend_day = is_weekend(day)

        # Nights (registrar, SHO, and COMET registrar when active)
        terms.append(W.cover_priority_night * locums["loc_n_reg"][d_idx])
        terms.append(W.cover_priority_night * locums["loc_n_sho"][d_idx])
        cmn_weight = W.cover_priority_comet if comet_week else W.cover_priority_night
        terms.append(cmn_weight * locums["loc_cmn"][d_idx])

        if nights_only:
            continue

        # CoMET day registrar (only relevant on COMET weeks)
        cmd_weight = W.cover_priority_comet if comet_week else W.cover_priority_weekday_ld
        terms.append(cmd_weight * locums["loc_cmd"][d_idx])

        # Long days split by weekend/bank holiday/weekday priority
        if is_weekend_day:
            ld_weight = W.cover_priority_weekend_ld
        elif is_bank_holiday:
            ld_weight = W.cover_priority_bank_holiday_ld
        else:
            ld_weight = W.cover_priority_weekday_ld
        terms.append(ld_weight * locums["loc_ld_reg"][d_idx])
        terms.append(ld_weight * locums["loc_ld_sho"][d_idx])

        # Weekday short days
        if not is_weekend_day and not is_bank_holiday:
            terms.append(W.cover_priority_weekday_sd * locums["loc_sd_any"][d_idx])

    # FDO is hard now; keep placeholder for compatibility (no-op)
    # For preassignments, penalize when b==0 (violation). We model cost as (1 - b).
    for b in locums.get("pre_ok_flags", []):
        one_minus = model.NewIntVar(0,1, f"pre_viol_cost_{b.Index()}")
        model.Add(one_minus == 1 - b)
        terms.append(W.preassign_violation * one_minus)

    for over in locums.get("weekend_firm_over", {}).values():
        terms.append(W.weekend_firm_penalty * over)

    for gap in locums.get("training_gap_flags", []):
        terms.append(W.training_nonattendance_penalty * gap)

    # Weekday short-day preference: stay within 2-3 additional clinicians when possible.
    if not nights_only:
        for d_idx, day in enumerate(days):
            if day.weekday() < 5 and day not in (problem.config.bank_holidays or []):
                sd_sum = sum(
                    x[p, d_idx, "SD"]
                    for p in range(len(people))
                    if people[p].grade != "Supernumerary"
                )
                under = model.NewIntVar(0, 2, f"sd_under_d{d_idx}")
                over = model.NewIntVar(0, 3, f"sd_over_d{d_idx}")
                model.Add(under >= 2 - sd_sum)
                model.Add(under >= 0)
                model.Add(over >= sd_sum - 3)
                model.Add(over >= 0)
                terms.append(problem.weights.weekday_day_target_penalty * (under + over))

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
            ld_code = long_day_code(p)
            if ld_code is None or sun_idx is None:
                continue
            ld_sat = x[p, sat_idx, ld_code]
            ld_sun = x[p, sun_idx, ld_code]
            both = model.NewBoolVar(f"wknd_both_p{p}_s{sat_idx}")
            # both == 1 -> ld_sat=1 and ld_sun=1
            model.AddBoolAnd([ld_sat, ld_sun]).OnlyEnforceIf(both)
            model.Add(both <= ld_sat)
            model.Add(both <= ld_sun)
            split = model.NewBoolVar(f"wknd_split_p{p}_s{sat_idx}")
            # split = ld_sat + ld_sun - 2*both  (0 when both 0 or 1; 1 when exactly one is 1)
            model.Add(split == ld_sat + ld_sun - 2*both)
            terms.append(W.weekend_pair_penalty * split)

    # Encourage target weekly hours pro-rata [45..48] scaled by WTE: penalize deficit below 45*WTE and excess above 48*WTE.
    days_count = len(days)
    weeks = days_count/7.0 if days_count > 0 else 0.0
    total_hours_map = locums.get("total_hours", {})
    if weeks > 0 and not nights_only:
        for p in range(len(people)):
            if p in total_hours_map:
                total_h = total_hours_map[p]
            else:
                total_h = model.NewIntVar(0, int(13*days_count), f"total_h_obj_p{p}")
                model.Add(
                    total_h
                    == sum(
                        x[p, d, s] * int(HOURS_BY_SHIFT[s])
                        for d in range(len(days))
                        for s in HOURS_BY_SHIFT
                    )
                )
            wte100 = int(round((getattr(people[p], 'wte', 1.0) or 1.0) * 100))
            wte100 = max(20, min(100, wte100))
            min_needed = int(round(42 * weeks * wte100 / 100))
            max_allowed = int(round(47 * weeks * wte100 / 100))
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
                night_today = sum(x[p, d, s] for s in NIGHT_SHIFT_CODES)
                night_prev = sum(x[p, d-1, s] for s in NIGHT_SHIFT_CODES)
                night_next = sum(x[p, d+1, s] for s in NIGHT_SHIFT_CODES)
                model.Add(sing <= night_today)
                model.Add(sing <= 1 - night_prev)
                model.Add(sing <= 1 - night_next)
                # If N_d is 1 and both neighbours 0, sing can be 1; otherwise forced 0
                terms.append(W.single_night_penalty * sing)
        # Also gently discourage >4 nights in any 5-day window
        for start in range(len(days)-4):
            over4 = model.NewBoolVar(f"soft_over4_n_p{p}_s{start}")
            window_sum = sum(
                sum(x[p, d, s] for s in NIGHT_SHIFT_CODES)
                for d in range(start, start + 5)
            )
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
            if getattr(people[p], 'grade', '') == 'Registrar' and shift_code in ('LDR','NR'):
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
            if getattr(people[p], 'grade', '') == 'Registrar' and base_shift in ('LDR','NR'):
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
        add_pairwise_fairness(sho_ids, 'NS',  'sho_n')
        add_pairwise_fairness_composite(reg_ids, ['NR','CMN'],  'reg_n_equiv', base_shift='NR')
    else:
        add_pairwise_fairness(sho_ids, 'LDS', 'sho_ld')
        add_pairwise_fairness(sho_ids, 'NS',  'sho_n')
        # Registrars: treat CMD as LD and CMN as N for fairness
        add_pairwise_fairness_composite(reg_ids, ['LDR','CMD'], 'reg_ld_equiv', base_shift='LDR')
        add_pairwise_fairness_composite(reg_ids, ['NR','CMN'],  'reg_n_equiv', base_shift='NR')


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
            if getattr(people[p], 'grade', '') == 'Registrar' and (shift_code in ('LDR','NR')):
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
        apply_band(sho_ids, 'NS',  'band_sho_n')
    else:
        apply_band(sho_ids, 'LDS', 'band_sho_ld')
        apply_band(sho_ids, 'NS',  'band_sho_n')
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
        if base_shift == 'LDR' and 'CMD' in comps:
            total_cover += comet_days_count
        if base_shift == 'NR' and 'CMN' in comps:
            total_cover += comet_days_count
        # WTE-based targets with COMET adjustment for eligible registrars
        wtes = []
        for p in group:
            base = (getattr(people[p], 'wte', 1.0) or 1.0)
            if getattr(people[p], 'grade', '') == 'Registrar' and base_shift in ('LDR','NR'):
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
        apply_band_composite(reg_ids, ['NR','CMN'],  'band_reg_n_equiv',  base_shift='NR')
    else:
        apply_band_composite(reg_ids, ['LDR','CMD'], 'band_reg_ld_equiv', base_shift='LDR')
        apply_band_composite(reg_ids, ['NR','CMN'],  'band_reg_n_equiv',  base_shift='NR')

    def apply_training_band(group: list[int], totals_map: Dict[int, Var], event_indices: list[int], label: str):
        if not group or not event_indices:
            return
        band = 0.33
        for p in group:
            total_var = totals_map.get(p)
            if total_var is None:
                continue
            eff_start = getattr(people[p], 'start_date', None) or problem.config.start_date
            active_sessions = sum(1 for idx in event_indices if days[idx] >= eff_start)
            if active_sessions == 0:
                continue
            wte = getattr(people[p], 'wte', 1.0) or 1.0
            wte = max(0.2, min(1.0, float(wte)))
            target = active_sessions * wte
            target_thou = int(round(target * 1000))
            if target_thou < 1000:
                lower = max(0, target_thou - 1000)
                upper = target_thou + 1000
            else:
                lower = (target_thou * 670) // 1000
                upper = (target_thou * 1330) // 1000
            scaled_total = model.NewIntVar(0, active_sessions * 1000, f"train_scaled_{label}_p{p}")
            model.Add(scaled_total == total_var * 1000)
            dev_low = model.NewIntVar(0, active_sessions * 1000, f"train_dev_low_{label}_p{p}")
            dev_high = model.NewIntVar(0, active_sessions * 1000, f"train_dev_high_{label}_p{p}")
            model.Add(dev_low >= lower - scaled_total)
            model.Add(dev_low >= 0)
            model.Add(dev_high >= scaled_total - upper)
            model.Add(dev_high >= 0)
            terms.append(problem.weights.training_band_penalty * (dev_low + dev_high))

    if not nights_only:
        apply_training_band(reg_ids, locums.get('registrar_training_totals', {}), locums.get('treg_days', []), 'treg')
        apply_training_band(sho_ids, locums.get('sho_training_totals', {}), locums.get('tsho_days', []), 'tsho')
        combined_group = sorted(set(reg_ids + sho_ids))
        apply_training_band(combined_group, locums.get('unit_training_totals', {}), locums.get('unit_days', []), 'unit')

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
                    model.AddMinEquality(cont, [x[p, sat, 'LDR'], x[p, fri, 'SD']])
                    terms.append(-W.weekend_continuity_bonus * cont)
                for p in sho_ids:
                    cont = model.NewBoolVar(f"cont_sho_fri_p{p}_sat{sat}")
                    model.AddMinEquality(cont, [x[p, sat, 'LDS'], x[p, fri, 'SD']])
                    terms.append(-W.weekend_continuity_bonus * cont)
            if mon is not None:
                for p in reg_ids:
                    cont = model.NewBoolVar(f"cont_reg_mon_p{p}_sat{sat}")
                    model.AddMinEquality(cont, [x[p, sun, 'LDR'], x[p, mon, 'SD']])
                    terms.append(-W.weekend_continuity_bonus * cont)
                for p in sho_ids:
                    cont = model.NewBoolVar(f"cont_sho_mon_p{p}_sat{sat}")
                    model.AddMinEquality(cont, [x[p, sun, 'LDS'], x[p, mon, 'SD']])
                    terms.append(-W.weekend_continuity_bonus * cont)

    # Nights preference:
    # Prefer a short day before Thu-Mon night runs and some crossover where possible.
    for d in range(len(days)):
        dow = days[d].weekday()
        # If Thursday night (dow=3) starting a run, bonus if same person does Thu SD
        if dow == 4-1 and d+1 < len(days):
            for p in reg_ids + sho_ids:
                night_list = night_codes_for_person(p)
                primary_night = night_list[0] if night_list else None
                if not primary_night:
                    continue
                b = model.NewBoolVar(f"pref_sd_before_night_p{p}_d{d}")
                model.AddMinEquality(b, [x[p, d, 'SD'], x[p, d+1, primary_night]])
                terms.append(-W.nights_pref_sd_before_bonus * b)
        # Encourage crossover: if two different clinicians cover N on Fri/Sat/Sun/Mon, mild bonus for overlapping one SD
        # Approximate by rewarding any SD on the same day by a clinician who is on N the day before/after
        if d > 0:
            for p in reg_ids + sho_ids:
                night_list = night_codes_for_person(p)
                primary_night = night_list[0] if night_list else None
                if not primary_night:
                    continue
                cross = model.NewBoolVar(f"night_crossover_prev_p{p}_d{d}")
                model.AddMinEquality(cross, [x[p, d-1, primary_night], x[p, d, 'SD']])
                terms.append(-W.nights_crossover_bonus * cross)
        if d+1 < len(days):
            for p in reg_ids + sho_ids:
                night_list = night_codes_for_person(p)
                primary_night = night_list[0] if night_list else None
                if not primary_night:
                    continue
                cross = model.NewBoolVar(f"night_crossover_next_p{p}_d{d}")
                model.AddMinEquality(cross, [x[p, d+1, primary_night], x[p, d, 'SD']])
                terms.append(-W.nights_crossover_bonus * cross)

    model.Minimize(sum(terms))
