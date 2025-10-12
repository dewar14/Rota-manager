#!/usr/bin/env python3
"""Test COMET fairness with detailed WTE analysis."""

from datetime import date, timedelta
from rostering.models import Person, Config, ProblemInput
from rostering.sequential_solver import SequentialSolver

def test_comet_fairness():
    # Create people with different WTE values
    people = [
        Person(id='reg1', name='Mei Yi', grade='Registrar', wte=0.8, comet_eligible=True),
        Person(id='reg2', name='David', grade='Registrar', wte=0.8, comet_eligible=True),
        Person(id='reg3', name='Nikki', grade='Registrar', wte=0.8, comet_eligible=True),
        Person(id='reg4', name='Reuben', grade='Registrar', wte=0.8, comet_eligible=True),
        Person(id='reg5', name='Alexander', grade='Registrar', wte=0.6, comet_eligible=False),  # Not eligible
        Person(id='reg6', name='Abdifatah', grade='Registrar', wte=1.0, comet_eligible=True),
        Person(id='reg7', name='Hanin', grade='Registrar', wte=0.8, comet_eligible=True),
        Person(id='reg8', name='Sarah', grade='Registrar', wte=0.6, comet_eligible=False),    # Not eligible
        Person(id='reg9', name='Manan', grade='Registrar', wte=1.0, comet_eligible=True),
        Person(id='reg10', name='Mahmoud', grade='Registrar', wte=1.0, comet_eligible=True),
        Person(id='reg11', name='Reg11', grade='Registrar', wte=1.0, comet_eligible=True),
    ]
    
    config = Config(
        start_date=date(2025, 2, 10),  # Monday
        end_date=date(2025, 2, 23),    # 14 days
        bank_holidays=[],
        comet_on_weeks=[date(2025, 2, 10)],  # First week is COMET week
        max_day_clinicians=5,
        ideal_weekday_day_clinicians=4,
        min_weekday_day_clinicians=3
    )
    
    # Calculate expected distribution
    eligible_people = [p for p in people if p.comet_eligible]
    total_wte = sum(p.wte for p in eligible_people)
    total_shifts = 7  # 7 days in COMET week
    
    print("WTE-Adjusted Expected Distribution:")
    print(f"Total COMET-eligible WTE: {total_wte}")
    print(f"Total CMD shifts needed: {total_shifts}")
    print(f"Total CMN shifts needed: {total_shifts}")
    print()
    
    for person in eligible_people:
        expected_cmd_float = (person.wte / total_wte) * total_shifts
        expected_cmn_float = (person.wte / total_wte) * total_shifts
        
        # Show both float and adjusted calculation
        expected_cmd = max(1, int(expected_cmd_float)) if expected_cmd_float >= 0.5 else int(expected_cmd_float)
        expected_cmn = max(1, int(expected_cmn_float)) if expected_cmn_float >= 0.5 else int(expected_cmn_float)
        
        print(f"{person.name} (WTE {person.wte}): Float {expected_cmd_float:.2f} → Expected {expected_cmd} CMD, {expected_cmn} CMN")
    
    print()
    
    # Run solver
    problem = ProblemInput(config=config, people=people)
    solver = SequentialSolver(problem)
    result = solver.solve_stage("comet", timeout_seconds=60)
    
    print(f"COMET result: {result.success} - {result.message}")
    
    if result.success:
        # Analyze actual distribution
        print("\nActual Distribution:")
        
        cmd_counts = {p.name: 0 for p in eligible_people}
        cmn_counts = {p.name: 0 for p in eligible_people}
        weekend_counts = {p.name: 0 for p in eligible_people}
        
        current_day = config.start_date
        while current_day <= config.end_date:
            day_str = current_day.isoformat()
            is_weekend = current_day.weekday() >= 5
            
            for person in eligible_people:
                if day_str in result.partial_roster:
                    shift = result.partial_roster[day_str].get(person.id, 'OFF')
                    if shift == 'CMD':
                        cmd_counts[person.name] += 1
                        if is_weekend:
                            weekend_counts[person.name] += 1
                    elif shift == 'CMN':
                        cmn_counts[person.name] += 1
                        if is_weekend:
                            weekend_counts[person.name] += 1
            
            current_day += timedelta(days=1)
        
        for person in eligible_people:
            expected_cmd = int((person.wte / total_wte) * total_shifts)
            expected_cmn = int((person.wte / total_wte) * total_shifts)
            actual_cmd = cmd_counts[person.name]
            actual_cmn = cmn_counts[person.name]
            weekend_work = weekend_counts[person.name]
            
            cmd_diff = actual_cmd - expected_cmd if expected_cmd > 0 else 0
            cmn_diff = actual_cmn - expected_cmn if expected_cmn > 0 else 0
            
            print(f"{person.name}: CMD {actual_cmd} (exp {expected_cmd}, diff {cmd_diff:+d}), "
                  f"CMN {actual_cmn} (exp {expected_cmn}, diff {cmn_diff:+d}), "
                  f"Weekend days: {weekend_work}")
        
        # Check for CMD before CMN violations
        print("\nChecking CMD→CMN violations:")
        violations = []
        
        current_day = config.start_date
        while current_day < config.end_date:
            today_str = current_day.isoformat()
            tomorrow_str = (current_day + timedelta(days=1)).isoformat()
            
            for person in eligible_people:
                today_shift = result.partial_roster.get(today_str, {}).get(person.id, 'OFF')
                tomorrow_shift = result.partial_roster.get(tomorrow_str, {}).get(person.id, 'OFF')
                
                if today_shift == 'CMD' and tomorrow_shift == 'CMN':
                    violations.append(f"{person.name}: CMD on {current_day} → CMN on {current_day + timedelta(days=1)}")
            
            current_day += timedelta(days=1)
        
        if violations:
            print("❌ CMD→CMN violations found:")
            for v in violations:
                print(f"  {v}")
        else:
            print("✅ No CMD→CMN violations")

if __name__ == "__main__":
    test_comet_fairness()