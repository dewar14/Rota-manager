"""
Firm constraints - may break but must indicate where and why.
These have high but not maximum penalty weights.
"""

from ortools.sat.python import cp_model
from typing import Dict, List
import datetime as dt
from rostering.models import ProblemInput, ShiftType, SHIFT_DEFINITIONS

def add_firm_constraints(problem: ProblemInput, model: cp_model.CpModel, x, days, people, breach_vars):
    """Add firm constraints with breach tracking."""
    
    P = range(len(people))
    D = range(len(days))
    
    # 1. Max frequency 1 in 3 weekends worked (firm constraint)
    add_weekend_frequency_firm(model, x, days, people, P, D, breach_vars)
    
    # 2. No consecutive blocks of nights (night night rest rest night night)
    add_no_consecutive_night_blocks(model, x, days, people, P, D, breach_vars)
    
    # 3. Weekends should be worked as a weekend (both Saturday and Sunday)
    add_weekend_continuity(model, x, days, people, P, D, breach_vars)
    
    # 4. Fair distribution (±15% variance instead of ±25%)
    add_fairness_firm_constraint(model, x, days, people, P, D, breach_vars)
    
    # 5. Training day attendance fairness (±33% variance)
    add_training_fairness(problem, model, x, days, people, P, D, breach_vars)


def add_weekend_frequency_firm(model, x, days, people, P, D, breach_vars):
    """Max frequency 1 in 3 weekends worked (preferred rule)."""
    weekends = []
    for d_idx, day in enumerate(days):
        if day.weekday() == 5 and d_idx + 1 < len(days) and days[d_idx + 1].weekday() == 6:
            weekends.append((d_idx, d_idx + 1))
    
    working_shifts = [s for s in ShiftType if SHIFT_DEFINITIONS[s]["hours"] > 0 and SHIFT_DEFINITIONS[s]["covers"]]
    
    for p in P:
        for i in range(len(weekends) - 2):  # 3 consecutive weekends
            weekend_worked = []
            for j in range(3):  # Check each of the 3 weekends
                weekend_idx = i + j
                sat, sun = weekends[weekend_idx]
                worked = model.NewBoolVar(f"weekend_worked_p{p}_w{weekend_idx}")
                
                # Weekend worked if any working shift on Sat OR Sun
                model.Add(sum(x[p, sat, s] for s in working_shifts) +
                         sum(x[p, sun, s] for s in working_shifts) >= worked)
                model.Add(sum(x[p, sat, s] for s in working_shifts) +
                         sum(x[p, sun, s] for s in working_shifts) <= 2 * worked)
                weekend_worked.append(worked)
            
            # Allow breach with penalty
            breach = model.NewBoolVar(f"weekend_1in3_breach_p{p}_w{i}")
            model.Add(sum(weekend_worked) <= 1 + breach)  # At most 1, or breach
            breach_vars['weekend_1in3'].append(breach)


def add_no_consecutive_night_blocks(model, x, days, people, P, D, breach_vars):
    """No consecutive blocks of nights (night night rest rest night night pattern)."""
    night_shifts = [ShiftType.NIGHT_REG, ShiftType.NIGHT_SHO, ShiftType.COMET_NIGHT]
    
    for p in P:
        for start in range(len(D) - 5):  # 6-day pattern window
            # Detect pattern: night night rest rest night night
            night_days = [start, start+1, start+4, start+5]  # Days with nights
            rest_days = [start+2, start+3]  # Days that should be rest
            
            # Count nights on night days
            nights_in_block1 = sum(x[p, start+i, s] for i in [0, 1] for s in night_shifts)
            nights_in_block2 = sum(x[p, start+i, s] for i in [4, 5] for s in night_shifts)
            
            # Detect if this is consecutive blocks pattern
            consecutive_blocks = model.NewBoolVar(f"consecutive_blocks_p{p}_d{start}")
            
            # If nights in both blocks, it's consecutive blocks (with penalty)
            breach = model.NewBoolVar(f"consecutive_blocks_breach_p{p}_d{start}")
            model.Add(nights_in_block1 + nights_in_block2 <= 2 + 10 * breach)  # Allow with penalty
            breach_vars['consecutive_night_blocks'].append(breach)


def add_weekend_continuity(model, x, days, people, P, D, breach_vars):
    """Weekends should be worked as a weekend (both Saturday and Sunday)."""
    working_shifts = [s for s in ShiftType if SHIFT_DEFINITIONS[s]["hours"] > 0 and SHIFT_DEFINITIONS[s]["covers"]]
    
    for d_idx, day in enumerate(days):
        if day.weekday() == 5 and d_idx + 1 < len(days) and days[d_idx + 1].weekday() == 6:
            sat, sun = d_idx, d_idx + 1
            
            for p in P:
                # Create boolean variables for working on Saturday/Sunday
                sat_working = model.NewBoolVar(f"sat_working_p{p}_d{sat}")
                sun_working = model.NewBoolVar(f"sun_working_p{p}_d{sun}")
                
                # Link boolean variables to actual work assignments
                sat_work_sum = sum(x[p, sat, s] for s in working_shifts)
                sun_work_sum = sum(x[p, sun, s] for s in working_shifts)
                
                # If working any shift on Saturday -> sat_working = 1
                model.Add(sat_working <= sat_work_sum)
                model.Add(sat_work_sum <= sat_working * len(working_shifts))
                
                # If working any shift on Sunday -> sun_working = 1  
                model.Add(sun_working <= sun_work_sum)
                model.Add(sun_work_sum <= sun_working * len(working_shifts))
                
                # Weekend continuity constraint
                breach_sat_only = model.NewBoolVar(f"weekend_continuity_breach_sat_p{p}_d{sat}")
                breach_sun_only = model.NewBoolVar(f"weekend_continuity_breach_sun_p{p}_d{sat}")
                
                # Weekend continuity: if working one day of weekend, must work both
                # Create negation variables
                not_sat_working = model.NewBoolVar(f"not_sat_working_p{p}_d{sat}")
                not_sun_working = model.NewBoolVar(f"not_sun_working_p{p}_d{sun}")
                
                # Link negation variables
                model.Add(not_sat_working + sat_working == 1)
                model.Add(not_sun_working + sun_working == 1)
                
                # sat_working AND NOT sun_working -> breach_sat_only  
                # sun_working AND NOT sat_working -> breach_sun_only
                
                # Using implication: sat_working => sun_working OR breach_sat_only
                model.AddBoolOr([not_sat_working, sun_working, breach_sat_only])
                # Using implication: sun_working => sat_working OR breach_sun_only  
                model.AddBoolOr([not_sun_working, sat_working, breach_sun_only])
                
                breach_vars['weekend_continuity'].extend([breach_sat_only, breach_sun_only])


def add_fairness_firm_constraint(model, x, days, people, P, D, breach_vars):
    """Fair distribution with ±15% variance (tighter than hard constraint ±25%)."""
    # Complex fairness calculation - placeholder for now
    # Would need to calculate expected shifts per person and constrain variance
    pass


def add_training_fairness(problem, model, x, days, people, P, D, breach_vars):
    """Training day attendance fairness (±33% variance)."""
    training_shifts = [ShiftType.REG_TRAINING, ShiftType.SHO_TRAINING, ShiftType.UNIT_TRAINING]
    
    # Calculate total training opportunities
    total_training_days = 0
    for d_idx, day in enumerate(days):
        # Count training opportunities on this day
        if day in problem.config.registrar_training_days:
            total_training_days += 1
        if day in problem.config.sho_training_days:
            total_training_days += 1  
        if day in problem.config.unit_training_days:
            total_training_days += 1
    
    if total_training_days > 0:
        # Expected training per person (adjusted by WTE)
        for p in P:
            person_wte = people[p].wte
            expected_training = int(total_training_days * person_wte / len(P))
            
            actual_training = sum(x[p, d, s] for d in D for s in training_shifts)
            
            # Allow ±33% variance with breach penalty
            breach_low = model.NewBoolVar(f"training_low_breach_p{p}")
            breach_high = model.NewBoolVar(f"training_high_breach_p{p}")
            
            min_expected = int(expected_training * 0.67)
            max_expected = int(expected_training * 1.33)
            
            model.Add(actual_training >= min_expected - 10 * breach_low)
            model.Add(actual_training <= max_expected + 10 * breach_high)
            
            breach_vars['training_fairness'].extend([breach_low, breach_high])