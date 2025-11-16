#!/usr/bin/env python3
"""
Analyze COMET night assignments and constraint violations in detail.
This script will help identify why the solver is struggling with block assignments.
"""

import json
import requests
from datetime import datetime, timedelta

def analyze_solver_output():
    print("🔍 MEDICAL ROTA SOLVER ANALYSIS")
    print("=" * 50)
    
    # Sample payload with correct WTE values
    payload = {
        'people': [
            {'id': 'dr1', 'name': 'Mei Yi Goh', 'grade': 'Registrar', 'wte': 0.8, 'comet_eligible': True},
            {'id': 'dr2', 'name': 'Ryan White', 'grade': 'Registrar', 'wte': 0.8, 'comet_eligible': True}, 
            {'id': 'dr3', 'name': 'Nikki Francis', 'grade': 'Registrar', 'wte': 0.8, 'comet_eligible': True},
            {'id': 'dr4', 'name': 'Reuben Firth', 'grade': 'Registrar', 'wte': 0.8, 'comet_eligible': True},
            {'id': 'dr5', 'name': 'Alexander Yule', 'grade': 'Registrar', 'wte': 0.6, 'comet_eligible': False},
            {'id': 'dr6', 'name': 'Abdifatah Mohamud', 'grade': 'Registrar', 'wte': 1.0, 'comet_eligible': True},
            {'id': 'dr7', 'name': 'Hanin El Abbas', 'grade': 'Registrar', 'wte': 0.8, 'comet_eligible': True},
            {'id': 'dr8', 'name': 'Sarah Hallett', 'grade': 'Registrar', 'wte': 0.6, 'comet_eligible': False},
            {'id': 'dr9', 'name': 'Manan Kamboj', 'grade': 'Registrar', 'wte': 1.0, 'comet_eligible': True},  # Fixed WTE
            {'id': 'dr10', 'name': 'Mahmoud', 'grade': 'Registrar', 'wte': 1.0, 'comet_eligible': True},
            {'id': 'dr11', 'name': 'Registrar 11', 'grade': 'Registrar', 'wte': 1.0, 'comet_eligible': True}
        ],
        'config': {
            'start_date': '2026-02-04',
            'end_date': '2026-08-03', 
            'comet_weeks': [
                '2026-02-09', '2026-02-23', '2026-03-09', '2026-03-23', 
                '2026-04-05', '2026-04-19', '2026-05-03', '2026-05-17',
                '2026-05-31', '2026-06-14', '2026-06-28', '2026-07-12', '2026-07-26'
            ]
        },
        'timeout': 300
    }
    
    print("📊 DOCTOR WTE ANALYSIS:")
    comet_eligible = [p for p in payload['people'] if p['comet_eligible']]
    print(f"Total COMET eligible doctors: {len(comet_eligible)}")
    
    total_wte = sum(p['wte'] for p in comet_eligible)
    print(f"Total WTE: {total_wte}")
    
    for person in comet_eligible:
        print(f"  {person['name']}: WTE {person['wte']}")
    
    # Calculate theoretical targets
    total_comet_nights = len(payload['config']['comet_weeks']) * 7  # 13 weeks × 7 days = 91
    print(f"\nTotal COMET nights needed: {total_comet_nights}")
    
    fair_share = total_comet_nights / len(comet_eligible)
    print(f"Fair share per doctor: {fair_share:.1f}")
    
    print("\n🎯 THEORETICAL WTE-ADJUSTED TARGETS:")
    for person in comet_eligible:
        target = fair_share * person['wte']
        print(f"  {person['name']}: {target:.1f} nights (WTE {person['wte']})")
    
    print(f"\nTotal theoretical assignment: {sum(fair_share * p['wte'] for p in comet_eligible):.1f}")
    
    # Try to run solver and analyze
    try:
        print("\n🚀 Running solver with corrected WTE values...")
        response = requests.post('http://localhost:8000/solve_sequential', json=payload, timeout=310)
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Solver completed: {result.get('success', False)}")
            print(f"Message: {result.get('message', 'No message')}")
            
            # Analyze the partial roster if available
            if 'partial_roster' in result:
                analyze_assignments(result['partial_roster'], comet_eligible, payload['config']['comet_weeks'])
        else:
            print(f"❌ Solver failed: {response.status_code}")
            print(response.text)
            
    except Exception as e:
        print(f"❌ Error running solver: {e}")

def analyze_assignments(roster, doctors, comet_weeks):
    print("\n📋 ASSIGNMENT ANALYSIS:")
    
    # Count assignments per doctor
    doctor_counts = {}
    doctor_blocks = {}
    
    for doctor in doctors:
        doctor_counts[doctor['id']] = 0
        doctor_blocks[doctor['id']] = []
    
    # Parse all dates
    for date_str, assignments in roster.items():
        for doctor_id, shift in assignments.items():
            if shift == 'CMN':
                doctor_counts[doctor_id] += 1
    
    # Analyze block patterns
    for doctor in doctors:
        doctor_id = doctor['id']
        consecutive_nights = []
        current_block = []
        
        # Sort dates and check for consecutive nights
        dates = sorted([datetime.fromisoformat(d) for d in roster.keys()])
        
        for date in dates:
            date_str = date.isoformat()
            if roster[date_str][doctor_id] == 'CMN':
                if not current_block or (date - current_block[-1]).days == 1:
                    current_block.append(date)
                else:
                    if current_block:
                        consecutive_nights.append(len(current_block))
                    current_block = [date]
        
        if current_block:
            consecutive_nights.append(len(current_block))
        
        doctor_blocks[doctor_id] = consecutive_nights
        
        total_nights = doctor_counts[doctor_id]
        blocks = [b for b in consecutive_nights if b > 1]
        singletons = consecutive_nights.count(1)
        
        print(f"  {doctor['name']} (WTE {doctor['wte']}):")
        print(f"    Total nights: {total_nights}")
        print(f"    Block pattern: {consecutive_nights}")
        print(f"    Blocks: {len(blocks)}, Singletons: {singletons}")
        
        if singletons > 0:
            print(f"    ⚠️  {singletons} singleton nights (should be minimal)")

if __name__ == "__main__":
    analyze_solver_output()