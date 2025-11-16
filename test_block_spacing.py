#!/usr/bin/env python3
"""
Test script to analyze block spacing for individual doctors.
Shows how far apart each doctor's night blocks are distributed.
"""

from datetime import date, timedelta
from rostering.models import Person, Config, ProblemInput
from rostering.sequential_solver import SequentialSolver
from rostering.models import ShiftType

def load_test_data():
    """Create test configuration with 6-month period."""
    # Create people with different WTE values
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
    
    # 6-month configuration with multiple COMET weeks
    config = Config(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 6, 30),
        bank_holidays=[],
        comet_on_weeks=[
            date(2026, 1, 5),   # Week 1
            date(2026, 2, 9),   # Week 6
            date(2026, 3, 16),  # Week 11
            date(2026, 4, 20),  # Week 16
            date(2026, 5, 25),  # Week 21
        ],
        max_day_clinicians=5,
        ideal_weekday_day_clinicians=4,
        min_weekday_day_clinicians=3
    )
    
    problem = ProblemInput(config=config, people=people)
    
    return problem, people

def analyze_block_spacing(roster, days, people):
    """Analyze spacing between blocks for each doctor."""
    night_types = [ShiftType.COMET_NIGHT.value, ShiftType.NIGHT_REG.value, ShiftType.NIGHT_SHO.value]
    
    print("\n" + "="*80)
    print("BLOCK SPACING ANALYSIS - Are blocks evenly distributed over time?")
    print("="*80)
    
    for person in people:
        # Find all blocks for this doctor
        blocks = []
        current_block = []
        
        for day in days:
            day_str = day.isoformat()
            assignment = roster[day_str].get(person.id)
            
            if assignment in night_types:
                current_block.append(day)
            else:
                if current_block and len(current_block) >= 2:  # Only count blocks (2+ nights)
                    blocks.append(current_block)
                current_block = []
        
        # Don't forget last block
        if current_block and len(current_block) >= 2:
            blocks.append(current_block)
        
        if len(blocks) >= 2:
            # Calculate gaps between consecutive blocks
            gaps = []
            for i in range(len(blocks) - 1):
                block_end = blocks[i][-1]
                next_block_start = blocks[i+1][0]
                gap_days = (next_block_start - block_end).days - 1  # Subtract 1 for the day after
                gaps.append(gap_days)
            
            # Calculate statistics
            avg_gap = sum(gaps) / len(gaps) if gaps else 0
            min_gap = min(gaps) if gaps else 0
            max_gap = max(gaps) if gaps else 0
            gap_variance = sum((g - avg_gap) ** 2 for g in gaps) / len(gaps) if gaps else 0
            
            print(f"\n{person.name} ({person.id}):")
            print(f"  Total blocks: {len(blocks)}")
            print(f"  Block dates:")
            for i, block in enumerate(blocks):
                print(f"    Block {i+1}: {block[0].strftime('%Y-%m-%d')} to {block[-1].strftime('%Y-%m-%d')} ({len(block)} nights)")
            print(f"  Gaps between blocks: {gaps} days")
            print(f"  Average gap: {avg_gap:.1f} days")
            print(f"  Min gap: {min_gap} days, Max gap: {max_gap} days")
            print(f"  Gap variance: {gap_variance:.1f} (lower = more evenly spaced)")
            
            # Assess spacing quality
            if gap_variance < 20:
                spacing_quality = "✅ EXCELLENT - Very evenly spaced"
            elif gap_variance < 50:
                spacing_quality = "✓ GOOD - Reasonably even"
            elif gap_variance < 100:
                spacing_quality = "⚠️ MODERATE - Some clustering"
            else:
                spacing_quality = "❌ POOR - Heavily clustered"
            print(f"  Spacing quality: {spacing_quality}")

def main():
    problem, people = load_test_data()
    
    solver = SequentialSolver(problem, people)
    
    # Solve COMET nights and unit nights stages
    result_comet = solver.solve_stage("comet_nights", timeout_seconds=60)
    
    if not result_comet.success:
        print(f"❌ COMET nights stage failed: {result_comet.message}")
        return
    
    print("✅ COMET nights completed, solving unit nights...")
    
    # Try unit nights
    result_nights = solver.solve_stage("nights", timeout_seconds=120)
    
    if not result_nights.success:
        print(f"⚠️ Unit nights failed: {result_nights.message}")
        print("   Analyzing COMET nights only")
    else:
        print("✅ Unit nights completed successfully")
    
    # Analyze spacing (will show COMET blocks at minimum, plus unit nights if they worked)
    analyze_block_spacing(solver.partial_roster, solver.days, people)

if __name__ == "__main__":
    main()
