#!/usr/bin/env python3
"""Script to test the API solver and capture output for analysis."""

import requests
import json
import yaml
import datetime as dt

# Test the local API
API_URL = "http://127.0.0.1:8000"

def test_api_solver():
    """Test the solver API and display results."""
    
    # Load sample data
    with open("data/sample_config.yml") as f:
        cfg = yaml.safe_load(f)
    
    # Build test problem
    problem_data = {
        "people": [
            {"id": "reg1", "name": "Test Registrar 1", "grade": "Registrar", "wte": 1.0, "comet_eligible": True},
            {"id": "reg2", "name": "Test Registrar 2", "grade": "Registrar", "wte": 0.8, "comet_eligible": True},
            {"id": "sho1", "name": "Test SHO 1", "grade": "SHO", "wte": 1.0, "comet_eligible": False}
        ],
        "config": {
            "start_date": "2025-02-05",
            "end_date": "2025-02-18", 
            "comet_on_weeks": ["2025-02-10"],
            "bank_holidays": [],
            "max_day_clinicians": 5,
            "ideal_weekday_day_clinicians": 4,
            "min_weekday_day_clinicians": 3
        }
    }
    
    try:
        print("Testing API solver...")
        response = requests.post(f"{API_URL}/solve", json=problem_data, timeout=60)
        
        if response.status_code == 200:
            result = response.json()
            print("✅ API solver completed successfully!")
            print(f"Message: {result.get('message', 'No message')}")
            
            # Show roster summary
            roster = result.get('roster', {})
            if roster:
                print(f"\nRoster generated for {len(roster)} days")
                for date in sorted(roster.keys())[:5]:  # Show first 5 days
                    assignments = roster[date]
                    print(f"  {date}: {dict(assignments)}")
                if len(roster) > 5:
                    print(f"  ... and {len(roster) - 5} more days")
            
            # Show violations
            breaches = result.get('breaches', {})
            if breaches:
                print(f"\nConstraint violations:")
                for constraint_type, violations in breaches.items():
                    if violations:
                        print(f"  {constraint_type}: {len(violations)} violations")
            else:
                print("\n✅ No constraint violations reported")
                
            # Show summary
            summary = result.get('summary', {})
            if summary:
                print(f"\nSummary:")
                print(f"  Total locum slots: {summary.get('total_locum_slots', 'N/A')}")
                print(f"  Utilization rate: {summary.get('utilization_rate', 'N/A'):.1%}")
                
        else:
            print(f"❌ API request failed: {response.status_code}")
            print(f"Response: {response.text}")
            
    except requests.exceptions.ConnectionError:
        print("❌ Cannot connect to API. Make sure the server is running at http://127.0.0.1:8000")
    except Exception as e:
        print(f"❌ Error testing API: {e}")

if __name__ == "__main__":
    test_api_solver()