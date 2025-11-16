#!/usr/bin/env python3
"""
Debug script to identify the multiple assignment issue in COMET nights
"""

from rostering.sequential_solver import SequentialSolver
from rostering.models import ProblemInput, ShiftType

def debug_comet_assignments():
    # Simple test case
    data = {
        'people': [
            {'id': 'dr1', 'name': 'Dr. Alice', 'wte': 1.0, 'grade': 'Registrar', 'comet_eligible': True},
            {'id': 'dr2', 'name': 'Dr. Bob', 'wte': 0.8, 'grade': 'Registrar', 'comet_eligible': True},
            {'id': 'dr3', 'name': 'Dr. Charlie', 'wte': 1.0, 'grade': 'SHO', 'comet_eligible': False}
        ],
        'config': {
            'start_date': '2026-01-01',
            'end_date': '2026-01-31',  # Just one month
            'comet_on_weeks': ['2026-01-06', '2026-01-20']  # Two COMET weeks
        }
    }

    print("=== DEBUGGING COMET ASSIGNMENT ISSUE ===")
    problem = ProblemInput.parse_obj(data)
    solver = SequentialSolver(problem)

    # Manually assign one COMET night first to test conflict detection
    print("\n1. Manually assigning dr1 to COMET night on 2026-01-06")
    solver.partial_roster['2026-01-06']['dr1'] = ShiftType.COMET_NIGHT.value
    
    # Check the state
    print(f"State after manual assignment: {solver.partial_roster['2026-01-06']}")
    
    # Now try to run the COMET stage and see if it creates conflicts
    print("\n2. Running COMET nights stage...")
    try:
        result = solver._solve_comet_nights_stage(300)
        print(f"Result: {result.success}, {result.message}")
        
        # Check for conflicts on 2026-01-06
        print(f"\n3. Final state for 2026-01-06: {solver.partial_roster['2026-01-06']}")
        
        # Count how many people have COMET_NIGHT
        comet_assignments = [pid for pid, assignment in solver.partial_roster['2026-01-06'].items() 
                           if assignment == ShiftType.COMET_NIGHT.value]
        print(f"Doctors with COMET_NIGHT on 2026-01-06: {comet_assignments}")
        
        if len(comet_assignments) > 1:
            print("🚨 BUG CONFIRMED: Multiple doctors assigned to same COMET night!")
        else:
            print("✅ No conflict detected")
            
    except Exception as e:
        print(f"Error during COMET stage: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_comet_assignments()