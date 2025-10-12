"""
Hard constraints that MUST NOT be breached by the solver.
These have very high penalty weights to ensure they are respected.
"""

from ortools.sat.python import cp_model
from typing import Dict, List
import datetime as dt
from rostering.models import ProblemInput, Person, ShiftType, SHIFT_DEFINITIONS

def add_hard_constraints(problem: ProblemInput, model: cp_model.CpModel, x, days, people):
    """Add all hard constraints that must be respected."""
    
    P = range(len(people))
    D = range(len(days))
    shift_codes = list(ShiftType)
    
    # 1. Max 72 hours worked in any consecutive period of 168 hours (7 days)
    add_72_hour_rule(model, x, days, people, P, D, shift_codes)
    
    # 2. Maximum frequency of 1 in 2 weekends worked (hard constraint version)
    add_weekend_frequency_hard(model, x, days, people, P, D)
    
    # 3. Max shift length of 13 hours (enforced by shift definitions)
    # Already enforced by SHIFT_DEFINITIONS - all shifts ≤ 13h
    
    # 4. 46-hours of rest required after any number of rostered night shifts
    add_night_rest_rule(model, x, days, people, P, D, shift_codes)
    
    # 5. Max 4 consecutive long shifts (>10 hours), 48h rest after 4th
    add_consecutive_long_shifts_rule(model, x, days, people, P, D, shift_codes)
    
    # 6. Max 4 consecutive night shifts, min 2 nights in any block (no singles)
    add_night_block_rules(model, x, days, people, P, D, shift_codes)
    
    # 7. Max 7 consecutive shifts, 48h rest after 7th
    add_consecutive_shifts_rule(model, x, days, people, P, D, shift_codes)
    
    # 8. Fair distribution of shifts accounting for WTE (±25% variance allowed)
    add_fairness_hard_constraint(model, x, days, people, P, D, shift_codes)
    
    # 9. Weekly hours constraints (42-47 hours * WTE average)
    add_weekly_hours_constraint(model, x, days, people, P, D, shift_codes)


def add_72_hour_rule(model, x, days, people, P, D, shift_codes):
    """Max 72 hours worked in any consecutive 168-hour period (7 days)."""
    for p in P:
        for start_day in range(len(D) - 6):  # 7-day windows
            total_hours = []
            for d in range(start_day, start_day + 7):
                for shift in shift_codes:
                    hours = SHIFT_DEFINITIONS[shift]["hours"]
                    if hours > 0:  # Only count shifts that have working hours
                        total_hours.append(x[p, d, shift] * int(hours))
            
            if total_hours:  # Only add constraint if there are working shifts
                model.Add(sum(total_hours) <= 72)


def add_weekend_frequency_hard(model, x, days, people, P, D):
    """Maximum frequency of 1 in 2 weekends worked (hard version)."""
    # Find all weekend pairs (Saturday-Sunday)
    weekends = []
    for d_idx, day in enumerate(days):
        if day.weekday() == 5:  # Saturday
            if d_idx + 1 < len(days) and days[d_idx + 1].weekday() == 6:  # Sunday follows
                weekends.append((d_idx, d_idx + 1))
    
    # For each person, in any 2 consecutive weekends, work at most 1
    working_shifts = [s for s in ShiftType if SHIFT_DEFINITIONS[s]["hours"] > 0 and SHIFT_DEFINITIONS[s]["covers"]]
    
    for p in P:
        for i in range(len(weekends) - 1):  # consecutive weekend pairs
            weekend1_sat, weekend1_sun = weekends[i]
            weekend2_sat, weekend2_sun = weekends[i + 1]
            
            # Count weekends worked (work either Saturday or Sunday = working that weekend)
            weekend1_worked = model.NewBoolVar(f"weekend1_worked_p{p}_w{i}")
            weekend2_worked = model.NewBoolVar(f"weekend2_worked_p{p}_w{i+1}")
            
            # Weekend 1 worked if any working shift on Sat OR Sun
            model.Add(sum(x[p, weekend1_sat, s] for s in working_shifts) +
                     sum(x[p, weekend1_sun, s] for s in working_shifts) >= weekend1_worked)
            model.Add(sum(x[p, weekend1_sat, s] for s in working_shifts) +
                     sum(x[p, weekend1_sun, s] for s in working_shifts) <= 2 * weekend1_worked)
            
            # Weekend 2 worked if any working shift on Sat OR Sun  
            model.Add(sum(x[p, weekend2_sat, s] for s in working_shifts) +
                     sum(x[p, weekend2_sun, s] for s in working_shifts) >= weekend2_worked)
            model.Add(sum(x[p, weekend2_sat, s] for s in working_shifts) +
                     sum(x[p, weekend2_sun, s] for s in working_shifts) <= 2 * weekend2_worked)
            
            # At most 1 weekend worked in this pair
            model.Add(weekend1_worked + weekend2_worked <= 1)


def add_night_rest_rule(model, x, days, people, P, D, shift_codes):
    """46-hours of rest required after any number of rostered night shifts."""
    night_shifts = [ShiftType.NIGHT_REG, ShiftType.NIGHT_SHO, ShiftType.COMET_NIGHT]
    working_shifts = [s for s in ShiftType if SHIFT_DEFINITIONS[s]["hours"] > 0]
    
    for p in P:
        for d in range(len(D) - 2):  # Need at least 2 days ahead for 46h rest
            # If working night on day d, then days d+1 and d+2 must be off/non-working
            for night_shift in night_shifts:
                # 46h rest ≈ 2 full days off after night shift
                model.Add(x[p, d, night_shift] + 
                         sum(x[p, d+1, s] for s in working_shifts) +
                         sum(x[p, d+2, s] for s in working_shifts) <= 1)


def add_consecutive_long_shifts_rule(model, x, days, people, P, D, shift_codes):
    """Max 4 consecutive long shifts (>10 hours), 48h rest after 4th."""
    # Long shifts are >10 hours
    long_shifts = [s for s in ShiftType if SHIFT_DEFINITIONS[s]["hours"] > 10]
    working_shifts = [s for s in ShiftType if SHIFT_DEFINITIONS[s]["hours"] > 0]
    
    for p in P:
        for start in range(len(D) - 3):  # 4-day windows
            # If 4 consecutive long shifts, need 2 days rest after
            if start + 5 < len(D):  # Ensure we have days for rest period
                model.Add(
                    sum(x[p, start+i, s] for i in range(4) for s in long_shifts) +
                    sum(x[p, start+4, s] for s in working_shifts) +
                    sum(x[p, start+5, s] for s in working_shifts) <= 4
                )


def add_night_block_rules(model, x, days, people, P, D, shift_codes):
    """Max 4 consecutive nights, minimum 2 nights in any block (no singles)."""
    night_shifts = [ShiftType.NIGHT_REG, ShiftType.NIGHT_SHO, ShiftType.COMET_NIGHT]
    
    for p in P:
        # No more than 4 consecutive nights
        for start in range(len(D) - 4):
            model.Add(sum(x[p, start+i, s] for i in range(5) for s in night_shifts) <= 4)
        
        # No single night shifts - simplified approach
        # If night on day d, then either night on d-1 or d+1 (if not at boundaries)
        for d in range(1, len(D) - 1):  # Skip first and last day
            night_today = sum(x[p, d, s] for s in night_shifts)
            night_before = sum(x[p, d-1, s] for s in night_shifts)  
            night_after = sum(x[p, d+1, s] for s in night_shifts)
            
            # If working night today, must have night before OR after (no isolated nights)
            # This is: night_today <= night_before + night_after
            # Rearranged: night_today - night_before - night_after <= 0
            model.Add(night_today <= night_before + night_after)


def add_consecutive_shifts_rule(model, x, days, people, P, D, shift_codes):
    """Max 7 consecutive shifts, 48h rest after 7th."""
    working_shifts = [s for s in ShiftType if SHIFT_DEFINITIONS[s]["hours"] > 0]
    
    for p in P:
        for start in range(len(D) - 6):  # 7-day windows
            # If 7 consecutive working shifts, need 2 days rest after
            if start + 8 < len(D):  # Ensure we have days for rest period
                model.Add(
                    sum(x[p, start+i, s] for i in range(7) for s in working_shifts) +
                    sum(x[p, start+7, s] for s in working_shifts) +
                    sum(x[p, start+8, s] for s in working_shifts) <= 7
                )


def add_fairness_hard_constraint(model, x, days, people, P, D, shift_codes):
    """Doctors should work same number of shifts (±25% variance) modified by WTE."""
    # This is complex - implement as soft constraint with high penalty for now
    # Full implementation would calculate expected shifts per person based on WTE
    pass


def add_weekly_hours_constraint(model, x, days, people, P, D, shift_codes):
    """Ensure each person works 42-47 hours per week on average over the period (6 months)."""
    total_weeks = len(days) / 7.0
    
    for p in P:
        person = people[p]
        # Average hours per week: 42-47 × WTE
        min_weekly_avg = 42 * person.wte
        max_weekly_avg = 47 * person.wte
        
        # Total hours over entire period
        min_total_hours = int(min_weekly_avg * total_weeks)
        max_total_hours = int(max_weekly_avg * total_weeks)
        
        # Calculate total hours worked over entire 6-month period
        total_hours_terms = []
        for d in D:
            for shift in shift_codes:
                if shift != ShiftType.OFF and shift != ShiftType.LTFT:  # Only working shifts count
                    hours = SHIFT_DEFINITIONS[shift]["hours"]
                    if hours > 0:
                        total_hours_terms.append(x[p, d, shift] * int(hours))
        
        if total_hours_terms:
            total_hours_expr = sum(total_hours_terms)
            model.Add(total_hours_expr >= min_total_hours)
            model.Add(total_hours_expr <= max_total_hours)
    pass  # Implement in constraints.py with high penalty weight