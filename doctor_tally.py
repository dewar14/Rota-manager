#!/usr/bin/env python3
"""Generate detailed statistics tally for each doctor from the roster."""

import pandas as pd
import yaml
import datetime as dt
import sys
import os
from collections import defaultdict

# Add the parent directory to the path so we can import rostering
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rostering.models import ShiftType, SHIFT_DEFINITIONS

def analyze_roster(roster_file="out/full_roster.csv", people_file="data/sample_people.csv"):
    """Analyze roster and generate doctor statistics."""
    
    # Load roster
    if not os.path.exists(roster_file):
        print(f"❌ Roster file not found: {roster_file}")
        print("Run the solver first to generate a roster.")
        return
    
    df_roster = pd.read_csv(roster_file, index_col=0)
    
    # Load people data for names and WTE
    df_people = pd.read_csv(people_file)
    people_info = {row['id']: {'name': row['name'], 'wte': row['wte'], 'grade': row['grade']} 
                   for _, row in df_people.iterrows()}
    
    # Calculate statistics for each doctor
    stats = {}
    
    for person_id in df_roster.columns:
        if person_id not in people_info:
            continue
            
        person_info = people_info[person_id]
        shifts = df_roster[person_id].tolist()
        
        # Count different shift types
        night_shifts = shifts.count('N_REG') + shifts.count('N_SHO')
        long_day_shifts = shifts.count('LD_REG') + shifts.count('LD_SHO') 
        comet_nights = shifts.count('CMN')
        comet_days = shifts.count('CMD')
        short_days = shifts.count('SD')
        
        # Calculate total hours worked
        total_hours = 0
        for shift in shifts:
            if shift in ['N_REG', 'N_SHO']:
                total_hours += 13  # Night shifts are 13 hours
            elif shift in ['LD_REG', 'LD_SHO']:
                total_hours += 13  # Long day shifts are 13 hours
            elif shift == 'CMN':
                total_hours += 12  # COMET night is 12 hours
            elif shift == 'CMD':
                total_hours += 12  # COMET day is 12 hours
            elif shift == 'SD':
                total_hours += 9   # Short day is 9 hours
            elif shift in ['CPD', 'TREG', 'TSHO', 'TUNIT', 'IND', 'LEAVE', 'STUDY']:
                total_hours += 9   # Training/leave days are 9 hours
        
        # Calculate average weekly hours
        total_days = len(shifts)
        weeks = total_days / 7
        avg_weekly_hours = total_hours / weeks if weeks > 0 else 0
        
        # Adjust for WTE (part-time workers)
        wte = person_info['wte']
        expected_weekly_hours = 47 * wte  # Assuming 47 hours full time
        
        stats[person_id] = {
            'name': person_info['name'],
            'grade': person_info['grade'],
            'wte': wte,
            'nights': night_shifts,
            'long_days': long_day_shifts,
            'comet_nights': comet_nights,
            'comet_days': comet_days,
            'short_days': short_days,
            'total_hours': total_hours,
            'avg_weekly_hours': avg_weekly_hours,
            'expected_weekly_hours': expected_weekly_hours,
            'hours_variance': avg_weekly_hours - expected_weekly_hours
        }
    
    return stats

def print_doctor_tally(stats):
    """Print formatted doctor statistics."""
    
    print("=" * 120)
    print("DOCTOR STATISTICS TALLY")
    print("=" * 120)
    print()
    
    # Header
    print(f"{'Name':<20} {'Grade':<10} {'WTE':<5} {'Nights':<7} {'LDs':<5} {'CMN':<5} {'CMD':<5} {'SDs':<5} {'Total Hrs':<10} {'Avg/Week':<10} {'Expected':<10} {'Variance':<10}")
    print("-" * 120)
    
    # Sort by grade then name
    sorted_stats = sorted(stats.items(), key=lambda x: (x[1]['grade'], x[1]['name']))
    
    total_nights = 0
    total_long_days = 0
    total_comet_nights = 0
    total_comet_days = 0
    total_short_days = 0
    total_hours = 0
    
    for person_id, data in sorted_stats:
        print(f"{data['name']:<20} {data['grade']:<10} {data['wte']:<5.1f} "
              f"{data['nights']:<7} {data['long_days']:<5} {data['comet_nights']:<5} {data['comet_days']:<5} {data['short_days']:<5} "
              f"{data['total_hours']:<10} {data['avg_weekly_hours']:<10.1f} {data['expected_weekly_hours']:<10.1f} "
              f"{data['hours_variance']:+10.1f}")
        
        total_nights += data['nights']
        total_long_days += data['long_days']
        total_comet_nights += data['comet_nights'] 
        total_comet_days += data['comet_days']
        total_short_days += data['short_days']
        total_hours += data['total_hours']
    
    print("-" * 120)
    print(f"{'TOTALS':<20} {'':<10} {'':<5} {total_nights:<7} {total_long_days:<5} {total_comet_nights:<5} {total_comet_days:<5} {total_short_days:<5} {total_hours:<10}")
    print()
    
    # Summary statistics
    print("SUMMARY:")
    print(f"• Total doctors: {len(stats)}")
    print(f"• Total night shifts: {total_nights}")
    print(f"• Total long day shifts: {total_long_days}")
    print(f"• Total COMET nights: {total_comet_nights}")
    print(f"• Total COMET days: {total_comet_days}")
    print(f"• Total short day shifts: {total_short_days}")
    print(f"• Total hours worked: {total_hours}")
    
    # Fairness analysis
    print("\nFAIRNESS ANALYSIS:")
    
    # Group by grade for fairness analysis
    by_grade = defaultdict(list)
    for data in stats.values():
        by_grade[data['grade']].append(data)
    
    for grade, doctors in by_grade.items():
        if not doctors:
            continue
            
        print(f"\n{grade}s:")
        nights = [d['nights'] for d in doctors]
        long_days = [d['long_days'] for d in doctors]
        hours_variance = [d['hours_variance'] for d in doctors]
        
        if nights:
            print(f"  Nights: min={min(nights)}, max={max(nights)}, avg={sum(nights)/len(nights):.1f}")
        if long_days:
            print(f"  Long days: min={min(long_days)}, max={max(long_days)}, avg={sum(long_days)/len(long_days):.1f}")
        if hours_variance:
            print(f"  Hours variance: min={min(hours_variance):+.1f}, max={max(hours_variance):+.1f}, avg={sum(hours_variance)/len(hours_variance):+.1f}")

def save_tally_csv(stats, output_file="out/doctor_tally.csv"):
    """Save tally to CSV file."""
    
    # Convert to DataFrame
    df = pd.DataFrame.from_dict(stats, orient='index')
    df.index.name = 'person_id'
    
    # Reorder columns
    columns = ['name', 'grade', 'wte', 'nights', 'long_days', 'comet_nights', 'comet_days', 
               'short_days', 'total_hours', 'avg_weekly_hours', 'expected_weekly_hours', 'hours_variance']
    df = df[columns]
    
    # Save to CSV
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    df.to_csv(output_file)
    print(f"\n📊 Detailed tally saved to: {output_file}")

if __name__ == "__main__":
    # Check if roster exists
    if not os.path.exists("out/full_roster.csv"):
        print("No roster found. Running solver first...")
        # Import and run the solver
        from rostering.models import ProblemInput, Person, Config, ConstraintWeights
        from rostering.sequential_solver import SequentialSolver
        
        # Load sample data and run solver
        with open("data/sample_config.yml") as f:
            cfg = yaml.safe_load(f)
        config = Config(
            start_date=dt.date.fromisoformat(str(cfg["start_date"])[:10]),
            end_date=dt.date.fromisoformat(str(cfg["end_date"])[:10]),
            bank_holidays=[dt.date.fromisoformat(str(d)[:10]) for d in cfg.get("bank_holidays",[])],
            comet_on_weeks=[dt.date.fromisoformat(str(d)[:10]) for d in cfg.get("comet_on_weeks",[])],
        )
        
        df = pd.read_csv("data/sample_people.csv")
        people = []
        for _,r in df.iterrows():
            people.append(Person(
                id=r["id"], name=r["name"], grade=r["grade"],
                wte=float(r["wte"]), 
                comet_eligible=bool(r["comet_eligible"]) if str(r["comet_eligible"]).lower() not in ["true","false"] else str(r["comet_eligible"]).lower()=="true",
            ))
        
        problem = ProblemInput(people=people, config=config)
        solver = SequentialSolver(problem)
        
        # Run all stages
        stages = ["comet", "nights", "weekend_holidays", "weekday_long_days", "short_days"]
        for stage in stages:
            result = solver.solve_stage(stage, timeout_seconds=60)
            if not result.success:
                print(f"Solver failed at {stage} stage")
                exit(1)
        
        # Save roster
        final_roster = solver.partial_roster
        df_roster = pd.DataFrame(final_roster).T
        df_roster.to_csv("out/full_roster.csv")
        print("Solver completed, roster saved.")
    
    # Analyze the roster
    stats = analyze_roster()
    if stats:
        print_doctor_tally(stats)
        save_tally_csv(stats)