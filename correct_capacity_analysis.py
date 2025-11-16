#!/usr/bin/env python3
"""
Correct capacity analysis based on actual hard constraints
"""

def analyze_real_capacity():
    print("🔍 CORRECT CAPACITY ANALYSIS")
    print("=" * 50)
    
    # 26-week period
    total_weeks = 26
    
    doctors = [
        {'name': 'Mei Yi Goh', 'wte': 0.8},
        {'name': 'Ryan White', 'wte': 0.8}, 
        {'name': 'Nikki Francis', 'wte': 0.8},
        {'name': 'Reuben Firth', 'wte': 0.8},
        {'name': 'Abdifatah Mohamud', 'wte': 1.0},
        {'name': 'Hanin El Abbas', 'wte': 0.8},
        {'name': 'Manan Kamboj', 'wte': 1.0},
        {'name': 'Mahmoud', 'wte': 1.0},
        {'name': 'Registrar 11', 'wte': 1.0}
    ]
    
    print("🎯 REAL CONSTRAINTS:")
    print("1. 72h max in any 7-day period")
    print("2. 42-48h × WTE average per week")
    print("3. COMET night = 12 hours")
    print()
    
    total_capacity = 0
    
    for doctor in doctors:
        # Weekly hours constraint is the limiting factor
        min_weekly = 42 * doctor['wte']
        max_weekly = 48 * doctor['wte'] 
        
        # But COMET nights are only PART of total hours
        # Doctor will also work unit nights, long days, short days, etc.
        
        # Conservative estimate: COMET nights could be 25-40% of total hours
        # (rest is unit work, training, leave, etc.)
        comet_percentage_min = 0.25  # 25% of hours from COMET
        comet_percentage_max = 0.40  # 40% of hours from COMET
        
        min_comet_hours_per_week = min_weekly * comet_percentage_min
        max_comet_hours_per_week = max_weekly * comet_percentage_max
        
        min_comet_nights_per_week = min_comet_hours_per_week / 12
        max_comet_nights_per_week = max_comet_hours_per_week / 12
        
        # Over 26 weeks
        min_total_comet = min_comet_nights_per_week * total_weeks
        max_total_comet = max_comet_nights_per_week * total_weeks
        
        print(f"{doctor['name']} (WTE {doctor['wte']}):")
        print(f"  Weekly hours: {min_weekly:.1f}-{max_weekly:.1f}h")
        print(f"  COMET portion: {min_comet_hours_per_week:.1f}-{max_comet_hours_per_week:.1f}h/week")
        print(f"  COMET nights: {min_comet_nights_per_week:.1f}-{max_comet_nights_per_week:.1f}/week")
        print(f"  26-week total: {min_total_comet:.0f}-{max_total_comet:.0f} COMET nights")
        print()
        
        total_capacity += max_total_comet
    
    print(f"🎯 TOTAL COMET CAPACITY: {total_capacity:.0f} nights")
    print(f"🎯 REQUIRED: 91 nights")
    print(f"🎯 SURPLUS/DEFICIT: {total_capacity - 91:.0f} nights")
    
    if total_capacity >= 91:
        print("✅ SUFFICIENT CAPACITY - Problem is elsewhere!")
    else:
        print("❌ INSUFFICIENT CAPACITY - Need more doctors")

if __name__ == "__main__":
    analyze_real_capacity()