#!/usr/bin/env python3
"""
Test current target calculation logic
"""

def test_current_targets():
    # Current solver logic
    comet_eligible = [
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
    
    total_comet_nights = 91
    fair_share = total_comet_nights / len(comet_eligible)
    
    print("🎯 CURRENT TARGET CALCULATION:")
    print(f"Total COMET nights: {total_comet_nights}")
    print(f"Fair share base: {fair_share:.1f}")
    print()
    
    total_allocated = 0
    for doctor in comet_eligible:
        wte_adjusted_target = fair_share * doctor['wte']
        total_allocated += wte_adjusted_target
        print(f"{doctor['name']}: {wte_adjusted_target:.1f} nights (WTE {doctor['wte']})")
    
    print(f"\nTotal allocated: {total_allocated:.1f}")
    print(f"Unallocated: {total_comet_nights - total_allocated:.1f}")
    
    # Alternative: Equal distribution
    print("\n🎯 ALTERNATIVE - EQUAL DISTRIBUTION:")
    equal_share = total_comet_nights / len(comet_eligible)
    for doctor in comet_eligible:
        weekly_hours_from_comet = (equal_share * 12) / 26  # 12h per night over 26 weeks
        max_weekly_hours = 48 * doctor['wte']
        percentage_of_max = (weekly_hours_from_comet / max_weekly_hours) * 100
        
        print(f"{doctor['name']}: {equal_share:.1f} nights")
        print(f"  Weekly COMET hours: {weekly_hours_from_comet:.1f}h ({percentage_of_max:.1f}% of max {max_weekly_hours:.1f}h)")
    
    print(f"\nTotal allocated: {len(comet_eligible) * equal_share:.1f}")

if __name__ == "__main__":
    test_current_targets()