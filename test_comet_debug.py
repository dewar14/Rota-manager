#!/usr/bin/env python3
"""Test COMET constraints with 9 eligible people."""

from datetime import date, timedelta
from rostering.models import Person, Config, ProblemInput
from rostering.sequential_solver import SequentialSolver

def test_comet():
    # Create 9 COMET-eligible people
    people = [
        Person(id='reg1', name='Mei Yi', grade='Registrar', wte=0.8, comet_eligible=True),
        Person(id='reg2', name='David', grade='Registrar', wte=0.8, comet_eligible=True),
        Person(id='reg3', name='Nikki', grade='Registrar', wte=0.8, comet_eligible=True),
        Person(id='reg4', name='Reuben', grade='Registrar', wte=0.8, comet_eligible=True),
        Person(id='reg5', name='Alexander', grade='Registrar', wte=0.6, comet_eligible=False),
        Person(id='reg6', name='Abdifatah', grade='Registrar', wte=1.0, comet_eligible=True),
        Person(id='reg7', name='Hanin', grade='Registrar', wte=0.8, comet_eligible=True),
        Person(id='reg8', name='Sarah', grade='Registrar', wte=0.6, comet_eligible=False),
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
    
    problem = ProblemInput(config=config, people=people)
    solver = SequentialSolver(problem)
    
    eligible_count = sum(1 for p in people if p.comet_eligible)
    print(f"Testing COMET with {len(people)} people ({eligible_count} COMET-eligible)")
    print(f"COMET week: 2025-02-10 to 2025-02-16")
    print(f"Full period: {config.start_date} to {config.end_date}")
    
    result = solver.solve_stage("comet", timeout_seconds=60)
    print(f"COMET result: {result.success} - {result.message}")
    
    if result.success:
        # Show ALL shifts assigned
        comet_week_start = date(2025, 2, 10)
        comet_week_end = date(2025, 2, 16)
        
        print("\nAll COMET assignments:")
        current_day = config.start_date
        while current_day <= config.end_date:
            day_str = current_day.isoformat()
            
            comet_shifts = []
            for person in people:
                if day_str in result.partial_roster:
                    shift = result.partial_roster[day_str].get(person.id, 'OFF')
                    if shift in ['CMD', 'CMN']:  # These are the string values
                        comet_shifts.append(f"{person.name}:{shift}")
            
            if comet_shifts:
                is_comet_week = comet_week_start <= current_day <= comet_week_end
                marker = " [COMET WEEK]" if is_comet_week else ""
                print(f"  {current_day}: {', '.join(comet_shifts)}{marker}")
            
            current_day += timedelta(days=1)

if __name__ == "__main__":
    test_comet()