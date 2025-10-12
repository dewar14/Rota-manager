#!/usr/bin/env python3
"""Test cumulative COMET fairness with deficit tracking."""

from datetime import date, timedelta
from rostering.models import Person, Config, ProblemInput
from rostering.sequential_solver import SequentialSolver

def test_cumulative_fairness():
    """Test fairness system with historical COMET counts."""
    
    # Create 9 COMET-eligible people
    people = [
        Person(id='reg1', name='Mei Yi', grade='Registrar', wte=0.8, comet_eligible=True),
        Person(id='reg2', name='David', grade='Registrar', wte=0.8, comet_eligible=True),
        Person(id='reg3', name='Nikki', grade='Registrar', wte=0.8, comet_eligible=True),
        Person(id='reg4', name='Reuben', grade='Registrar', wte=0.8, comet_eligible=True),
        Person(id='reg5', name='Alexander', grade='Registrar', wte=0.6, comet_eligible=False),  # Not eligible
        Person(id='reg6', name='Abdifatah', grade='Registrar', wte=1.0, comet_eligible=True),
        Person(id='reg7', name='Hanin', grade='Registrar', wte=0.8, comet_eligible=True),
        Person(id='reg8', name='Sarah', grade='Registrar', wte=0.6, comet_eligible=False),  # Not eligible
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
    
    # Test 1: No historical data (first roster period)
    print("=== Test 1: First roster period (no historical data) ===")
    
    problem = ProblemInput(config=config, people=people)
    solver = SequentialSolver(problem, historical_comet_counts=None)
    
    result = solver.solve_stage("comet", timeout_seconds=60)
    print(f"Result: {result.success} - {result.message}")
    
    if result.success:
        # Count assignments
        comet_week_start = date(2025, 2, 10)
        comet_week_end = date(2025, 2, 16)
        
        assignments = {}
        for person in people:
            if person.comet_eligible:
                assignments[person.name] = {"cmd": 0, "cmn": 0}
        
        print("\nFirst period assignments:")
        current_day = config.start_date
        while current_day <= config.end_date:
            day_str = current_day.isoformat()
            
            comet_shifts = []
            for person in people:
                if day_str in result.partial_roster:
                    shift = result.partial_roster[day_str].get(person.id, 'OFF')
                    if shift == 'CMD':
                        assignments[person.name]["cmd"] += 1
                        comet_shifts.append(f"{person.name}:CMD")
                    elif shift == 'CMN':
                        assignments[person.name]["cmn"] += 1
                        comet_shifts.append(f"{person.name}:CMN")
            
            if comet_shifts:
                is_comet_week = comet_week_start <= current_day <= comet_week_end
                marker = " [COMET WEEK]" if is_comet_week else ""
                print(f"  {current_day}: {', '.join(comet_shifts)}{marker}")
            
            current_day += timedelta(days=1)
        
        print(f"\nSummary after first period:")
        for name, counts in assignments.items():
            total = counts["cmd"] + counts["cmn"]
            print(f"  {name}: {counts['cmd']} CMD + {counts['cmn']} CMN = {total} total")
    
    # Test 2: Second roster period with historical data favoring underworked people
    print("\n=== Test 2: Second roster period (with deficit tracking) ===")
    
    # Simulate historical counts where some people are underworked
    historical_counts = {
        'reg1': {'cmd': 3, 'cmn': 2},   # Mei Yi: already worked a lot
        'reg2': {'cmd': 2, 'cmn': 0},   # David: some work
        'reg3': {'cmd': 0, 'cmn': 2},   # Nikki: some work
        'reg4': {'cmd': 0, 'cmn': 0},   # Reuben: NO WORK - should get priority!
        'reg6': {'cmd': 0, 'cmn': 0},   # Abdifatah: NO WORK - should get priority!
        'reg7': {'cmd': 0, 'cmn': 0},   # Hanin: NO WORK - should get priority!
        'reg9': {'cmd': 0, 'cmn': 0},   # Manan: NO WORK - should get priority!
        'reg10': {'cmd': 0, 'cmn': 0}, # Mahmoud: NO WORK - should get priority!
        'reg11': {'cmd': 2, 'cmn': 3},  # Reg11: already worked some
    }
    
    solver2 = SequentialSolver(problem, historical_comet_counts=historical_counts)
    result2 = solver2.solve_stage("comet", timeout_seconds=60)
    
    print(f"Result: {result2.success} - {result2.message}")
    
    if result2.success:
        assignments2 = {}
        for person in people:
            if person.comet_eligible:
                assignments2[person.name] = {"cmd": 0, "cmn": 0}
        
        print("\nSecond period assignments (should favor underworked doctors):")
        current_day = config.start_date
        while current_day <= config.end_date:
            day_str = current_day.isoformat()
            
            comet_shifts = []
            for person in people:
                if day_str in result2.partial_roster:
                    shift = result2.partial_roster[day_str].get(person.id, 'OFF')
                    if shift == 'CMD':
                        assignments2[person.name]["cmd"] += 1
                        comet_shifts.append(f"{person.name}:CMD")
                    elif shift == 'CMN':
                        assignments2[person.name]["cmn"] += 1
                        comet_shifts.append(f"{person.name}:CMN")
            
            if comet_shifts:
                is_comet_week = comet_week_start <= current_day <= comet_week_end
                marker = " [COMET WEEK]" if is_comet_week else ""
                print(f"  {current_day}: {', '.join(comet_shifts)}{marker}")
            
            current_day += timedelta(days=1)
        
        print(f"\nSummary after second period:")
        print("Expected: Underworked doctors (Reuben, Abdifatah, Hanin, Manan, Mahmoud) should get more shifts")
        
        for name, counts in assignments2.items():
            total = counts["cmd"] + counts["cmn"]
            historical_total = 0
            for person in people:
                if person.name == name and person.id in historical_counts:
                    hist = historical_counts[person.id]
                    historical_total = hist["cmd"] + hist["cmn"]
                    break
            
            print(f"  {name}: {counts['cmd']} CMD + {counts['cmn']} CMN = {total} total (historical: {historical_total})")

if __name__ == "__main__":
    test_cumulative_fairness()