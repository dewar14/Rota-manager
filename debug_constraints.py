#!/usr/bin/env python3
"""
Debug constraint violation detection with a simple COMET block scenario.
This tests whether the constraint violation detection is working correctly
for basic COMET night blocks with proper rest periods.
"""

from datetime import date
from rostering.constraint_violations import HardConstraintViolationDetector
from rostering.models import Person, ShiftType, ProblemInput, Config

# Test scenario: Doctor with 4 consecutive COMET nights followed by OFF days
def test_basic_comet_block():
    # Create test doctor
    doctor = Person(
        id="test_dr",
        name="Dr. Test",
        grade="Registrar",
        wte=1.0,
        comet_eligible=True
    )
    
    # Create config
    config = Config(
        start_date=date(2026, 2, 10),
        end_date=date(2026, 2, 16),
        comet_on_weeks=[],
        bank_holidays=[]
    )
    
    # Create problem input
    problem = ProblemInput(people=[doctor], config=config)
    
    # Create assignment: 4 COMET nights (Tue-Fri) followed by OFF days
    # Tuesday 2026-02-10 to Friday 2026-02-13: COMET_NIGHT (4 nights × 12h = 48h)
    # Saturday-Monday: OFF (proper 46h+ rest)
    assignments = {
        "2026-02-10": {"test_dr": "CMN"},  # Tuesday
        "2026-02-11": {"test_dr": "CMN"},  # Wednesday  
        "2026-02-12": {"test_dr": "CMN"},  # Thursday
        "2026-02-13": {"test_dr": "CMN"},  # Friday
        "2026-02-14": {"test_dr": "OFF"},  # Saturday - OFF
        "2026-02-15": {"test_dr": "OFF"},  # Sunday - OFF  
        "2026-02-16": {"test_dr": "OFF"},  # Monday - OFF
    }
    
    # Initialize violation detector
    detector = HardConstraintViolationDetector(problem)
    
    # Check violations
    violations = detector.detect_violations(assignments)
    
    print("=== CONSTRAINT VIOLATION TEST ===")
    print(f"Test scenario: 4 consecutive COMET nights (Tue-Fri) + 3 OFF days")
    print(f"Expected: NO critical violations")
    print(f"- 4 nights × 12h = 48h (within 72h weekly limit)")
    print(f"- Followed by 3 OFF days (>46h rest)")
    print(f"- ≤4 consecutive nights (within limit)")
    print()
    
    # Analyze results
    print(f"Total violations detected: {len(violations)}")
    
    critical_violations = [v for v in violations if v.severity == "CRITICAL"]
    high_violations = [v for v in violations if v.severity == "HIGH"]
    
    print(f"CRITICAL violations: {len(critical_violations)}")
    print(f"HIGH violations: {len(high_violations)}")
    print()
    
    if critical_violations:
        print("❌ CRITICAL VIOLATIONS (should be NONE):")
        for v in critical_violations:
            print(f"  - {v.violation_type}: {v.description}")
            print(f"    Current: {v.current_value}, Limit: {v.limit_value}")
    else:
        print("✅ No critical violations detected (correct)")
    
    if high_violations:
        print("\n⚠️  HIGH VIOLATIONS:")
        for v in high_violations:
            print(f"  - {v.violation_type}: {v.description}")
            print(f"    Current: {v.current_value}, Limit: {v.limit_value}")
    
    return len(critical_violations), len(high_violations)

if __name__ == "__main__":
    critical, high = test_basic_comet_block()
    
    print(f"\n=== SUMMARY ===")
    if critical == 0:
        print("✅ Test PASSED: No incorrect critical violations")
    else:
        print(f"❌ Test FAILED: {critical} incorrect critical violations detected")
        print("This suggests the constraint detection logic has bugs.")