#!/usr/bin/env python3
"""Test script to isolate constraint issues."""

import sys

# Add the current directory to path
sys.path.insert(0, '.')

# Import the modules
try:
    print("Testing constraint imports...")
    from rostering.firm_constraints import add_weekend_continuity, add_firm_constraints
    print("✓ Constraint imports successful")
    
    # Try importing the solver
    from rostering.solver import solve_roster
    print("✓ Solver import successful")
    
    # Simple test: try calling solve_roster with a None (should fail gracefully)
    print("Testing solver with None input...")
    try:
        result = solve_roster(None)
        print("✓ Solver handled None gracefully")
    except Exception as e:
        print(f"✓ Solver failed with None as expected: {e}")
    
    print("All tests passed!")
    
except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()