from ortools.sat.python import cp_model
from typing import Dict, Tuple, List
import datetime as dt
from dateutil.rrule import rrule, DAILY
from rostering.models import ProblemInput, ShiftType, SHIFT_DEFINITIONS

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
    """Build day and person indices for the problem."""
    days = list(daterange(problem.config.start_date, problem.config.end_date))
    day_index = {d:i for i,d in enumerate(days)}
    
    # Filter people by start_date
    people = [p for p in problem.people if (p.start_date is None or p.start_date <= problem.config.end_date)]
    person_index = {p.id:i for i,p in enumerate(people)}
    
    return days, day_index, people, person_index

def add_core_constraints(problem: ProblemInput, model: cp_model.CpModel):
    """Add basic constraints and decision variables."""
    
    days, day_index, people, person_index = build_index(problem)
    
    P = range(len(people))
    D = range(len(days))
    
    # All possible shift assignments
    shift_codes = list(ShiftType)
    
    # Decision variables: x[p,d,s] ∈ {0,1} - person p on day d assigned shift s
    x: Dict[Tuple[int,int,ShiftType], Var] = {}
    for p in P:
        for d in D:
            for s in shift_codes:
                x[p,d,s] = model.NewBoolVar(f"x_p{p}_d{d}_{s.value}")
    
    # Locum coverage variables (slack for unmet requirements)
    locum_vars = create_locum_variables(model, D)
    
    # Helper sets by grade
    reg_ids = {i for i,p in enumerate(people) if p.grade == "Registrar"}
    sho_ids = {i for i,p in enumerate(people) if p.grade == "SHO"}
    sup_ids = {i for i,p in enumerate(people) if p.grade == "Supernumerary"}
    comet_eligible = {i for i,p in enumerate(people) if p.comet_eligible}
    
    # BASIC CONSTRAINTS
    
    # 1) Exactly one shift per person per day (including OFF)
    for p in P:
        for d in D:
            model.Add(sum(x[p,d,s] for s in shift_codes) == 1)
    
    # 2) Grade restrictions
    add_grade_restrictions(model, x, P, D, reg_ids, sho_ids, sup_ids, shift_codes)
    
    # 3) Fixed LTFT days
    add_ltft_constraints(model, x, people, days, P, D)
    
    # 4) CoMET eligibility
    add_comet_constraints(model, x, people, days, problem.config, P, D, comet_eligible)
    
    # 5) Training day assignments
    add_training_constraints(model, x, people, days, problem.config, P, D)
    
    # 6) Coverage requirements
    add_coverage_constraints(model, x, locum_vars, days, problem.config, P, D, reg_ids, sho_ids)
    
    return x, locum_vars, days, people

def create_locum_variables(model: cp_model.CpModel, D):
    """Create locum slack variables for coverage requirements."""
    return {
        "long_day_reg": [model.NewIntVar(0, 1, f"locum_ld_reg_d{d}") for d in D],
        "long_day_sho": [model.NewIntVar(0, 1, f"locum_ld_sho_d{d}") for d in D],
        "night_reg": [model.NewIntVar(0, 1, f"locum_n_reg_d{d}") for d in D],
        "night_sho": [model.NewIntVar(0, 1, f"locum_n_sho_d{d}") for d in D],
        "short_day": [model.NewIntVar(0, 5, f"locum_sd_d{d}") for d in D],
        "comet_day": [model.NewIntVar(0, 1, f"locum_cmd_d{d}") for d in D],
        "comet_night": [model.NewIntVar(0, 1, f"locum_cmn_d{d}") for d in D],
    }

def add_grade_restrictions(model, x, P, D, reg_ids, sho_ids, sup_ids, shift_codes):
    """Add constraints based on staff grade restrictions."""
    
    # Supernumerary restrictions (only SHORT_DAY, training, or OFF)
    allowed_for_sup = [ShiftType.SHORT_DAY, ShiftType.CPD, ShiftType.UNIT_TRAINING, 
                      ShiftType.INDUCTION, ShiftType.LEAVE, ShiftType.STUDY_LEAVE, 
                      ShiftType.LTFT, ShiftType.OFF]
    
    for p in sup_ids:
        for d in D:
            for s in shift_codes:
                if s not in allowed_for_sup:
                    model.Add(x[p,d,s] == 0)
    
    # Grade-specific shift restrictions
    for p in P:
        for d in D:
            # Long day registrar only for registrars
            if p not in reg_ids:
                model.Add(x[p,d,ShiftType.LONG_DAY_REG] == 0)
            
            # Long day SHO only for SHOs  
            if p not in sho_ids:
                model.Add(x[p,d,ShiftType.LONG_DAY_SHO] == 0)
                
            # Night registrar only for registrars
            if p not in reg_ids:
                model.Add(x[p,d,ShiftType.NIGHT_REG] == 0)
                
            # Night SHO only for SHOs
            if p not in sho_ids:
                model.Add(x[p,d,ShiftType.NIGHT_SHO] == 0)
                
            # CoMET shifts only for registrars
            if p not in reg_ids:
                model.Add(x[p,d,ShiftType.COMET_DAY] == 0)
                model.Add(x[p,d,ShiftType.COMET_NIGHT] == 0)

def add_ltft_constraints(model, x, people, days, P, D):
    """Add Less Than Full Time (LTFT) fixed day off constraints."""
    
    for p_idx, person in enumerate(people):
        if person.fixed_day_off is not None and person.wte < 1.0:
            for d_idx, day in enumerate(days):
                if day.weekday() == person.fixed_day_off:
                    # Must be OFF or LTFT on fixed day off
                    model.Add(x[p_idx, d_idx, ShiftType.LTFT] == 1)

def add_comet_constraints(model, x, people, days, config, P, D, comet_eligible):
    """Add CoMET week constraints."""
    
    for d_idx, day in enumerate(days):
        # Check if this day falls in a CoMET week
        is_comet_week = False
        for comet_monday in config.comet_on_weeks:
            week_start = comet_monday
            week_end = comet_monday + dt.timedelta(days=6)
            if week_start <= day <= week_end:
                is_comet_week = True
                break
        
        if is_comet_week:
            # CoMET shifts only for eligible registrars
            for p in P:
                if p not in comet_eligible:
                    model.Add(x[p, d_idx, ShiftType.COMET_DAY] == 0)
                    model.Add(x[p, d_idx, ShiftType.COMET_NIGHT] == 0)
        else:
            # No CoMET shifts outside CoMET weeks
            for p in P:
                model.Add(x[p, d_idx, ShiftType.COMET_DAY] == 0)
                model.Add(x[p, d_idx, ShiftType.COMET_NIGHT] == 0)

def add_training_constraints(model, x, people, days, config, P, D):
    """Add training day constraints."""
    
    for d_idx, day in enumerate(days):
        # Registrar training days
        if day in config.registrar_training_days:
            for p_idx, person in enumerate(people):
                if person.grade == "Registrar":
                    # Encourage but don't force registrar training attendance
                    # This will be handled in soft constraints
                    pass
        
        # SHO training days
        if day in config.sho_training_days:
            for p_idx, person in enumerate(people):
                if person.grade == "SHO":
                    # Encourage but don't force SHO training attendance
                    pass
        
        # Unit training days (all grades)
        if day in config.unit_training_days:
            # Encourage unit training attendance for all
            pass

def add_coverage_constraints(model, x, locum_vars, days, config, P, D, reg_ids, sho_ids):
    """Add daily coverage requirements."""
    
    for d_idx, day in enumerate(days):
        is_weekend = day.weekday() >= 5
        is_bank_holiday = day in config.bank_holidays
        is_weekend_or_holiday = is_weekend or is_bank_holiday
        
        # DAILY REQUIREMENTS (every day)
        
        # Exactly 1 Long Day Registrar
        model.Add(sum(x[p, d_idx, ShiftType.LONG_DAY_REG] for p in reg_ids) + 
                 locum_vars["long_day_reg"][d_idx] == 1)
        
        # Exactly 1 Long Day SHO  
        model.Add(sum(x[p, d_idx, ShiftType.LONG_DAY_SHO] for p in sho_ids) + 
                 locum_vars["long_day_sho"][d_idx] == 1)
        
        # Exactly 1 Night Registrar
        model.Add(sum(x[p, d_idx, ShiftType.NIGHT_REG] for p in reg_ids) + 
                 locum_vars["night_reg"][d_idx] == 1)
        
        # Exactly 1 Night SHO
        model.Add(sum(x[p, d_idx, ShiftType.NIGHT_SHO] for p in sho_ids) + 
                 locum_vars["night_sho"][d_idx] == 1)
        
        # CoMET REQUIREMENTS (CoMET weeks only)
        is_comet_week = any(monday <= day <= monday + dt.timedelta(days=6) 
                           for monday in config.comet_on_weeks)
        
        if is_comet_week:
            # Exactly 1 CoMET Day Registrar
            model.Add(sum(x[p, d_idx, ShiftType.COMET_DAY] for p in reg_ids) + 
                     locum_vars["comet_day"][d_idx] == 1)
            
            # Exactly 1 CoMET Night Registrar  
            model.Add(sum(x[p, d_idx, ShiftType.COMET_NIGHT] for p in reg_ids) + 
                     locum_vars["comet_night"][d_idx] == 1)
        
        # SHORT DAY REQUIREMENTS (weekdays only)
        if not is_weekend_or_holiday:
            # Minimum 1, target more short day staff
            model.Add(sum(x[p, d_idx, ShiftType.SHORT_DAY] for p in P) + 
                     locum_vars["short_day"][d_idx] >= config.min_weekday_day_clinicians - 2)  # -2 for the LD staff

def soft_objective(problem: ProblemInput, model: cp_model.CpModel, x, locum_vars, days, people, breach_vars=None):
    """Add soft constraints and optimization objective following prioritisation order."""
    
    terms = []
    weights = problem.weights
    P = range(len(people))
    
    # PRIORITY 1: Cover CoMET days and nights (HIGHEST WEIGHT: 10000)
    for locum_type in ["comet_day", "comet_night"]:
        if locum_type in locum_vars:
            for var in locum_vars[locum_type]:
                terms.append(10000 * var)  # Massive penalty for CoMET locums
    
    # PRIORITY 2: Cover night shifts (VERY HIGH WEIGHT: 5000)
    for locum_type in ["night_reg", "night_sho"]:
        if locum_type in locum_vars:
            for var in locum_vars[locum_type]:
                terms.append(5000 * var)  # Very high penalty for night locums
    
    # PRIORITY 3: Cover weekends (HIGH WEIGHT: 2500)
    # Weekend coverage implicit in daily requirements, add fairness bonus
    
    # PRIORITY 4: Cover Bank Holiday days (MEDIUM WEIGHT: 1200)
    # Implicit in daily requirements
    
    # PRIORITY 5: Cover Weekday Long days (MEDIUM WEIGHT: 1000)
    for locum_type in ["long_day_reg", "long_day_sho"]:
        if locum_type in locum_vars:
            for var in locum_vars[locum_type]:
                terms.append(1000 * var)  # Medium penalty for long day locums
    
    # PRIORITY 6: Cover weekdays with 2 doctors per day (WEIGHT: 500)
    for locum_type in ["short_day"]:
        if locum_type in locum_vars:
            for var in locum_vars[locum_type]:
                terms.append(500 * var)  # Lower penalty for short day locums
    
    # PRIORITY 7 & 8: Training assignments and hours balancing (LOWEST WEIGHT: 100)
    # These are handled by firm constraints and preferences
    
    # Weekday staffing targets (Priority 6)
    for d_idx, day in enumerate(days):
        if day.weekday() < 5 and day not in problem.config.bank_holidays:
            # Count total day staff (LD + SD)
            total_day_staff = (
                sum(x[p, d_idx, ShiftType.LONG_DAY_REG] for p in P) +
                sum(x[p, d_idx, ShiftType.LONG_DAY_SHO] for p in P) +
                sum(x[p, d_idx, ShiftType.SHORT_DAY] for p in P) +
                sum(x[p, d_idx, ShiftType.COMET_DAY] for p in P)  # CoMET counts as day staff
            )
            
            # Deviation from ideal staffing (2 doctors per weekday)
            ideal = problem.config.ideal_weekday_day_clinicians
            deviation_pos = model.NewIntVar(0, 10, f"dev_pos_d{d_idx}")
            deviation_neg = model.NewIntVar(0, 10, f"dev_neg_d{d_idx}")
            
            model.Add(deviation_pos - deviation_neg == total_day_staff - ideal)
            terms.append(100 * (deviation_pos + deviation_neg))  # Lower weight
    
    # Breach penalties (Firm constraints)
    if breach_vars:
        for breach_type, var_list in breach_vars.items():
            weight = getattr(weights, f"{breach_type}_violation", 200)
            for var in var_list:
                terms.append(weight * var)
    
    # Basic fairness approximation (Priority 8 - lowest)
    # Minimize variance in total shifts assigned
    
    # Basic fairness approximation (more sophisticated fairness in hard/firm constraints)
    # Minimize variance in total shifts assigned
    if len(people) > 1:
        working_shifts = [s for s in ShiftType if SHIFT_DEFINITIONS[s]["hours"] > 0]
        person_totals = []
        
        for p in P:
            total = sum(x[p, d, s] for d in range(len(days)) for s in working_shifts)
            person_totals.append(total)
        
        # Approximate fairness by minimizing max-min difference
        max_shifts = model.NewIntVar(0, len(days) * 2, "max_shifts")
        min_shifts = model.NewIntVar(0, len(days) * 2, "min_shifts")
        
        for total in person_totals:
            model.Add(total <= max_shifts)
            model.Add(total >= min_shifts)
        
        terms.append(weights.fairness_variance_15pct * (max_shifts - min_shifts))
    
    if terms:
        model.Minimize(sum(terms))
    else:
        # Fallback: minimize total assignments (shouldn't happen)
        model.Minimize(sum(x[p,d,s] for p in P for d in range(len(days)) for s in ShiftType if s != ShiftType.OFF))
