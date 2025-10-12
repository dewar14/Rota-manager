#!/usr/bin/env python3
"""
Test constraint detection with a scenario that SHOULD trigger violations.
"""

from datetime import date
from rostering.constraint_violations import HardConstraintViolationDetector
from rostering.models import Person, ProblemInput, Config

def test_should_have_violations():
    """Test a scenario that should legitimately trigger violations."""
    
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
    
    # Create assignment with REAL violation: night shift immediately followed by day shift
    assignments = {
        "2026-02-10": {"test_dr": "CMN"},  # Monday night
        "2026-02-11": {"test_dr": "LD_REG"},  # Tuesday day - VIOLATION! (< 46h rest)
        "2026-02-12": {"test_dr": "OFF"},
        "2026-02-13": {"test_dr": "OFF"},
        "2026-02-14": {"test_dr": "OFF"},
        "2026-02-15": {"test_dr": "OFF"},
        "2026-02-16": {"test_dr": "OFF"},
    }
    
    # Initialize violation detector
    detector = HardConstraintViolationDetector(problem)
    
    # Check violations
    violations = detector.detect_violations(assignments)
    
    print("=== VIOLATION DETECTION TEST (should find violations) ===")
    print("Test scenario: Night shift Mon, Day shift Tue (< 46h rest)")
    print("Expected: 1 CRITICAL violation")
    print()
    
    critical_violations = [v for v in violations if v.severity == "CRITICAL"]
    print(f"CRITICAL violations detected: {len(critical_violations)}")
    
    if len(critical_violations) == 1:
        print("✅ Test PASSED: Correctly detected violation")
        print(f"   - {critical_violations[0].description}")
    elif len(critical_violations) == 0:
        print("❌ Test FAILED: Should have detected 1 violation but found none")
    else:
        print(f"❌ Test FAILED: Expected 1 violation but found {len(critical_violations)}")
        for v in critical_violations:
            print(f"   - {v.description}")
    
    return len(critical_violations)

if __name__ == "__main__":
    violations_found = test_should_have_violations()
    print(f"\nConstraint detection is {'working correctly' if violations_found == 1 else 'still has issues'}")