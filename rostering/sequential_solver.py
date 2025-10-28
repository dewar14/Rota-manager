"""
Sequential solver that builds roster in stages with admin checkpoints.
Allows reviewing and approving each stage before proceeding.
"""

from ortools.sat.python import cp_model
from typing import Dict, Tuple, Set, List
import copy
from datetime import date, timedelta

from .models import ShiftType, ProblemInput
# Violation detection imported locally to avoid circular imports


def get_days_from_config(config):
    """Generate list of dates from config."""
    start = config.start_date
    if isinstance(start, str):
        start = date.fromisoformat(start)
    end = config.end_date
    if isinstance(end, str):
        end = date.fromisoformat(end)
    
    days = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


def shift_duration_hours(shift_type: ShiftType) -> float:
    """Get duration in hours for a shift type."""
    duration_map = {
        ShiftType.LONG_DAY_REG: 13.0,
        ShiftType.LONG_DAY_SHO: 13.0,
        ShiftType.NIGHT_REG: 13.0,
        ShiftType.NIGHT_SHO: 13.0,
        ShiftType.COMET_DAY: 12.0,
        ShiftType.COMET_NIGHT: 12.0,
        ShiftType.SHORT_DAY: 9.0,
        ShiftType.CPD: 9.0,
        ShiftType.REG_TRAINING: 9.0,
        ShiftType.SHO_TRAINING: 9.0,
        ShiftType.OFF: 0.0,
        ShiftType.LOCUM: 0.0
    }
    return duration_map.get(shift_type, 8.0)  # Default 8 hours


class SequentialSolveResult:
    """Result from a sequential solve stage."""
    
    def __init__(self, stage: str, success: bool, message: str, 
                 partial_roster: Dict[str, Dict[str, str]], 
                 assigned_shifts: Set[Tuple[int, int, ShiftType]] = None,
                 next_stage: str = None):
        self.stage = stage
        self.success = success
        self.message = message
        self.partial_roster = partial_roster  # What's been assigned so far
        self.assigned_shifts = assigned_shifts or set()  # (person_idx, day_idx, shift) tuples
        self.next_stage = next_stage
        self.stats = self._calculate_stats()
        
    def _calculate_stats(self):
        """Calculate statistics for this stage."""
        stats = {}
        if not self.partial_roster:
            return stats
            
        # Count shifts assigned in this stage
        shift_counts = {}
        total_assigned = 0
        
        for day_roster in self.partial_roster.values():
            for person_id, shift_str in day_roster.items():
                if shift_str != ShiftType.OFF.value:
                    shift_type = ShiftType(shift_str)
                    shift_counts[shift_type] = shift_counts.get(shift_type, 0) + 1
                    total_assigned += 1
                    
        stats['shift_counts'] = shift_counts
        stats['total_assigned'] = total_assigned
        stats['days_covered'] = len(self.partial_roster)
        
        return stats


class SequentialSolver:
    """Solver that builds roster in sequential stages with checkpoints."""
    
    def __init__(self, problem: ProblemInput, historical_comet_counts=None):
        self.problem = problem
        self.config = problem.config
        self.people = problem.people
        self.days = get_days_from_config(self.config)
        self.start_date = self.config.start_date  # Add start_date for date arithmetic
        
        # Track assigned shifts across stages
        self.assigned_shifts: Set[Tuple[int, int, ShiftType]] = set()
        self.partial_roster: Dict[str, Dict[str, str]] = {}
        
        # Historical COMET counts for 26-week fairness tracking
        # Format: {"person_id": {"cmd": count, "cmn": count}}
        self.historical_comet_counts = historical_comet_counts or {}
        
        # Initialize empty roster
        for day in self.days:
            self.partial_roster[day.isoformat()] = {
                person.id: ShiftType.OFF.value for person in self.people
            }
    
    def solve_with_checkpoints(self, timeout_per_stage: int = 1800, auto_continue: bool = False) -> SequentialSolveResult:
        """Solve roster with admin review checkpoints between stages."""
        
        # Updated stage order: COMET Nights, Unit Nights, Holiday working, COMET days, Unit long days, short days
        stages = ["comet_nights", "nights", "weekend_holidays", "comet_days", "weekday_long_days", "short_days"]
        
        for i, stage_name in enumerate(stages):
            print(f"\n{'='*80}")
            print(f"STAGE {i+1}/{len(stages)}: {stage_name.upper()}")
            print(f"{'='*80}")
            
            # Solve the current stage
            result = self.solve_stage(stage_name, timeout_per_stage)
            
            if not result.success:
                print(f"\n❌ Stage '{stage_name}' failed: {result.message}")
                return result
            
            print(f"\n✅ Stage '{stage_name}' completed successfully!")
            print(f"   {result.message}")
            
            # Show current roster statistics
            stats = self.get_roster_statistics()
            print("\n📊 Current Roster Statistics:")
            print(f"   Total shifts assigned: {stats['total_assigned']}")
            print(f"   Days covered: {stats['days_covered']}")
            for shift_type, count in stats['shift_counts'].items():
                if count > 0:
                    print(f"   {shift_type}: {count} shifts")
            
            # Check for hard constraint violations
            constraint_check = self.check_hard_constraints()
            violations = constraint_check['violations']
            
            if violations:
                critical_count = constraint_check['violation_summary']['critical_violations']
                high_count = constraint_check['violation_summary']['high_violations']
                
                print("\n⚠️  CONSTRAINT VIOLATIONS DETECTED:")
                print(f"   Critical: {critical_count}, High: {high_count}")
                
                # Show critical violations
                for violation in violations[:3]:  # Show first 3 violations
                    if violation['severity'] == 'CRITICAL':
                        print(f"   🚨 {violation['description']}")
                
                # Show suggested alternatives for critical violations
                alternatives = constraint_check['alternatives']
                if alternatives:
                    print("\n💡 SUGGESTED ALTERNATIVES:")
                    for alt in alternatives[:2]:  # Show top 2 alternatives
                        cost_str = f"£{alt['estimated_cost']}" if alt['estimated_cost'] > 0 else "No cost"
                        print(f"   • {alt['description']} ({cost_str})")
                
                if critical_count > 0:
                    print("\n❌ CRITICAL: Hard constraints cannot be met with current assignments.")
                    print("   Consider using suggested alternatives or adding locum coverage.")
            else:
                print("\n✅ No hard constraint violations detected.")
            
            # Checkpoint (except for last stage)
            if i < len(stages) - 1:
                next_stage = stages[i + 1]
                print(f"\n🛑 CHECKPOINT: Review stage '{stage_name}' before proceeding to '{next_stage}'")
                
                if not auto_continue:
                    print("\nOptions:")
                    print("  [c]ontinue  - Proceed to next stage")
                    print("  [p]ause     - Stop here for detailed review")
                    print("  [s]tats     - Show detailed roster statistics")
                    print("  [v]iolations - Show constraint violation details")
                    print("  [q]uit      - Exit the solver")
                    
                    while True:
                        try:
                            response = input(f"\nAction for '{next_stage}' stage? [c/p/s/v/q]: ").strip().lower()
                        except (EOFError, KeyboardInterrupt):
                            print("\n⚠️ Input not available - auto-continuing...")
                            response = 'c'
                        
                        if response in ['c', 'continue']:
                            print(f"Continuing to '{next_stage}' stage...")
                            break
                        elif response in ['p', 'pause']:
                            print(f"Pausing after '{stage_name}' stage for detailed review.")
                            print(f"To resume: solver.resume_from_stage('{next_stage}')")
                            return SequentialSolveResult(
                                stage=stage_name,
                                success=True,
                                message=f"Paused after '{stage_name}' stage for review",
                                partial_roster=copy.deepcopy(self.partial_roster),
                                next_stage=next_stage
                            )
                        elif response in ['s', 'stats']:
                            self._show_detailed_statistics()
                        elif response in ['v', 'violations']:
                            self._show_constraint_violations()
                        elif response in ['q', 'quit']:
                            return SequentialSolveResult(
                                stage=stage_name,
                                success=True,
                                message=f"User quit at checkpoint after '{stage_name}' stage",
                                partial_roster=copy.deepcopy(self.partial_roster),
                                next_stage=next_stage
                            )
                        else:
                            print("Invalid option. Please choose c, p, s, v, or q.")
                else:
                    print(f"Auto-continuing to '{next_stage}' stage...")
        
        # All stages completed
        print("\n🎉 ALL STAGES COMPLETED SUCCESSFULLY!")
        return SequentialSolveResult(
            stage="complete",
            success=True,
            message="All roster stages completed successfully",
            partial_roster=copy.deepcopy(self.partial_roster)
        )
    
    def resume_from_stage(self, stage_name: str, timeout_per_stage: int = 1800) -> SequentialSolveResult:
        """Resume solving from a specific stage after pausing for review."""
        
        stages = ["comet_nights", "nights", "weekend_holidays", "comet_days", "weekday_long_days", "short_days"]
        
        if stage_name not in stages:
            return SequentialSolveResult(
                stage=stage_name,
                success=False,
                message=f"Invalid stage name: {stage_name}. Valid stages: {', '.join(stages)}",
                partial_roster=copy.deepcopy(self.partial_roster)
            )
        
        start_index = stages.index(stage_name)
        
        print(f"\n🔄 RESUMING FROM STAGE: {stage_name.upper()}")
        print(f"Remaining stages: {' → '.join(stages[start_index:])}")
        
        # Continue with remaining stages
        for i in range(start_index, len(stages)):
            stage = stages[i]
            print(f"\n{'='*80}")
            print(f"STAGE {i+1}/{len(stages)}: {stage.upper()}")
            print(f"{'='*80}")
            
            result = self.solve_stage(stage, timeout_per_stage)
            
            if not result.success:
                print(f"\n❌ Stage '{stage}' failed: {result.message}")
                return result
            
            print(f"\n✅ Stage '{stage}' completed successfully!")
            print(f"   {result.message}")
            
            # Checkpoint for remaining stages
            if i < len(stages) - 1:
                next_stage = stages[i + 1]
                print(f"\n🛑 CHECKPOINT: Review stage '{stage}' before proceeding to '{next_stage}'")
                
                print("\nOptions:")
                print("  [c]ontinue  - Proceed to next stage")
                print("  [p]ause     - Stop here for detailed review")
                print("  [s]tats     - Show detailed roster statistics")
                print("  [q]uit      - Exit the solver")
                
                while True:
                    response = input(f"\nAction for '{next_stage}' stage? [c/p/s/q]: ").strip().lower()
                    
                    if response in ['c', 'continue']:
                        print(f"Continuing to '{next_stage}' stage...")
                        break
                    elif response in ['p', 'pause']:
                        print(f"Pausing after '{stage}' stage for detailed review.")
                        print(f"To resume: solver.resume_from_stage('{next_stage}')")
                        return SequentialSolveResult(
                            stage=stage,
                            success=True,
                            message=f"Paused after '{stage}' stage for review",
                            partial_roster=copy.deepcopy(self.partial_roster),
                            next_stage=next_stage
                        )
                    elif response in ['s', 'stats']:
                        self._show_detailed_statistics()
                    elif response in ['q', 'quit']:
                        return SequentialSolveResult(
                            stage=stage,
                            success=True,
                            message=f"User quit at checkpoint after '{stage}' stage",
                            partial_roster=copy.deepcopy(self.partial_roster),
                            next_stage=next_stage
                        )
                    else:
                        print("Invalid option. Please choose c, p, s, or q.")
        
        print("\n🎉 ALL REMAINING STAGES COMPLETED SUCCESSFULLY!")
        return SequentialSolveResult(
            stage="complete",
            success=True,
            message="All remaining roster stages completed successfully",
            partial_roster=copy.deepcopy(self.partial_roster)
        )
    
    def _show_detailed_statistics(self):
        """Show detailed roster statistics for current state."""
        
        print("\n" + "="*60)
        print("DETAILED ROSTER STATISTICS")
        print("="*60)
        
        # Count assignments by person and shift type
        assignment_counts = {}
        shift_type_totals = {}
        
        for day_str, day_assignments in self.partial_roster.items():
            for person_id, shift_type in day_assignments.items():
                if shift_type != ShiftType.OFF.value:
                    # Person totals
                    if person_id not in assignment_counts:
                        assignment_counts[person_id] = {}
                    if shift_type not in assignment_counts[person_id]:
                        assignment_counts[person_id][shift_type] = 0
                    assignment_counts[person_id][shift_type] += 1
                    
                    # Shift type totals
                    if shift_type not in shift_type_totals:
                        shift_type_totals[shift_type] = 0
                    shift_type_totals[shift_type] += 1
        
        # Show by person
        print("\nAssignments by Person:")
        print("-" * 40)
        for person in self.people:
            person_assignments = assignment_counts.get(person.id, {})
            total_shifts = sum(person_assignments.values())
            
            if total_shifts > 0:
                print(f"{person.name} (WTE: {person.wte}):")
                for shift_type, count in person_assignments.items():
                    print(f"  {shift_type}: {count}")
                print(f"  Total: {total_shifts} shifts")
                print()
        
        # Show by shift type
        print("\nAssignments by Shift Type:")
        print("-" * 30)
        for shift_type, count in shift_type_totals.items():
            print(f"{shift_type}: {count} shifts")
        
        total_assignments = sum(shift_type_totals.values())
        total_days = len(self.days)
        coverage_percent = (total_assignments / (total_days * len(self.people))) * 100
        
        print(f"\nTotal Assignments: {total_assignments}")
        print(f"Total Person-Days: {total_days * len(self.people)}")
        print(f"Coverage: {coverage_percent:.1f}%")
    
    def _show_constraint_violations(self):
        """Show detailed constraint violation information."""
        
        print("\n" + "="*60)
        print("CONSTRAINT VIOLATION ANALYSIS")
        print("="*60)
        
        try:
            constraint_check = self.check_hard_constraints()
            violations = constraint_check.get('violations', [])
            
            if not violations:
                print("\n✅ No constraint violations detected!")
                return
            
            # Group by severity
            critical = [v for v in violations if v.get('severity') == 'CRITICAL']
            high = [v for v in violations if v.get('severity') == 'HIGH']
            medium = [v for v in violations if v.get('severity') == 'MEDIUM']
            
            if critical:
                print(f"\n🚨 CRITICAL VIOLATIONS ({len(critical)}):")
                for i, violation in enumerate(critical[:5], 1):
                    print(f"  {i}. {violation.get('description', 'Unknown violation')}")
            
            if high:
                print(f"\n⚠️ HIGH PRIORITY VIOLATIONS ({len(high)}):")
                for i, violation in enumerate(high[:5], 1):
                    print(f"  {i}. {violation.get('description', 'Unknown violation')}")
            
            if medium:
                print(f"\n📋 MEDIUM PRIORITY VIOLATIONS ({len(medium)}):")
                for i, violation in enumerate(medium[:3], 1):
                    print(f"  {i}. {violation.get('description', 'Unknown violation')}")
            
            # Show alternatives if available
            alternatives = constraint_check.get('alternatives', [])
            if alternatives:
                print(f"\n💡 SUGGESTED SOLUTIONS:")
                for i, alt in enumerate(alternatives[:3], 1):
                    cost_str = f"£{alt['estimated_cost']}" if alt.get('estimated_cost', 0) > 0 else "No additional cost"
                    print(f"  {i}. {alt.get('description', 'Unknown solution')} ({cost_str})")
                    
        except Exception as e:
            print(f"\n❌ Error checking constraints: {e}")
            print("This may be expected if constraint checking isn't fully implemented yet.")

    def solve_stage(self, stage_name: str, timeout_seconds: int = 1800) -> SequentialSolveResult:
        """Solve a specific stage of the roster."""
        
        if stage_name == "comet_nights":
            return self._solve_comet_nights_stage(timeout_seconds)
        elif stage_name == "nights":
            return self._solve_nights_stage(timeout_seconds)
        elif stage_name == "weekend_holidays":
            return self._solve_weekend_holiday_stage(timeout_seconds)
        elif stage_name == "comet_days":
            return self._solve_comet_days_stage(timeout_seconds)
        elif stage_name == "weekday_long_days":
            return self._solve_weekday_long_days_stage(timeout_seconds)
        elif stage_name == "short_days":
            return self._solve_short_days_stage(timeout_seconds)
        # Legacy support for old stage names
        elif stage_name == "comet":
            return self._solve_comet_nights_stage(timeout_seconds)
        else:
            return SequentialSolveResult(
                stage=stage_name, 
                success=False, 
                message=f"Unknown stage: {stage_name}",
                partial_roster=self.partial_roster
            )
    
    def _solve_comet_nights_stage(self, timeout_seconds: int) -> SequentialSolveResult:
        """Stage 1: Assign COMET night shifts sequentially with transparent progression."""
        
        print("=" * 80)
        print("COMET STAGE: Sequential Assignment")
        print("=" * 80)
        
        # Get COMET eligible doctors
        comet_eligible = [(i, p) for i, p in enumerate(self.people) if p.comet_eligible]
        if not comet_eligible:
            return SequentialSolveResult(
                stage="comet",
                success=False,
                message="No COMET eligible doctors found",
                partial_roster=copy.deepcopy(self.partial_roster),
                next_stage="nights"
            )
        
        # Identify COMET weeks
        comet_week_ranges = []
        for monday in self.config.comet_on_weeks:
            week_end = monday + timedelta(days=6) 
            comet_week_ranges.append((monday, week_end))
        
        print(f"Found {len(comet_eligible)} COMET eligible doctors:")
        
        # Doctor Key - Full name to ID mapping
        print("\n📋 DOCTOR KEY:")
        for p_idx, person in comet_eligible:
            print(f"  {person.id} = {person.name} (WTE: {person.wte})")
        print()
        
        for p_idx, person in comet_eligible:
            print(f"  {person.name} (WTE: {person.wte})")
        
        print(f"\nCOMET weeks to cover: {len(comet_week_ranges)}")
        for i, (start, end) in enumerate(comet_week_ranges):
            print(f"  Week {i+1}: {start} to {end}")
        
        # Calculate total COMET nights and equal distribution target
        total_comet_nights = len(comet_week_ranges) * 7  # 7 nights per COMET week
        self.target_comet_nights = total_comet_nights / len(comet_eligible) if len(comet_eligible) > 0 else 0
        print(f"  Total COMET nights to assign: {total_comet_nights}")
        print(f"  Target per doctor (equal distribution): {self.target_comet_nights:.1f}")
        
        # Initialize running totals
        running_totals = {}
        for p_idx, person in comet_eligible:
            running_totals[p_idx] = {
                'comet_nights': 0,
                'total_nights': 0,
                'total_hours': 0,
                'blocks_assigned': 0
            }
        
        # Step 1: Assign COMET Night blocks sequentially
        print("\n" + "="*50)
        print("STEP 1: COMET NIGHT ASSIGNMENTS")
        print("="*50)
        
        try:
            self._assign_comet_night_blocks_sequentially(comet_week_ranges, comet_eligible, running_totals)
        except Exception as e:
            return SequentialSolveResult(
                stage="comet",
                success=False,
                message=f"COMET nights assignment failed: {str(e)}",
                partial_roster=copy.deepcopy(self.partial_roster),
                next_stage="nights"
            )
        
        # Display final night assignments
        print("\nFinal COMET Night assignments:")
        total_cmn_assigned = 0
        for p_idx, person in comet_eligible:
            cmn_count = running_totals[p_idx]['comet_nights']
            total_cmn_assigned += cmn_count
            wte_adjusted = cmn_count / person.wte if person.wte > 0 else 0
            print(f"  {person.name}: {cmn_count} CMN shifts (WTE-adjusted: {wte_adjusted:.1f})")
        
        print(f"\nTotal COMET nights assigned: {total_cmn_assigned}")
        
        # Analyze block patterns vs singletons
        print("\n📊 BLOCK PATTERN ANALYSIS:")
        total_blocks = 0
        total_singletons = 0
        
        for p_idx, person in comet_eligible:
            blocks = 0
            singletons = 0
            consecutive_count = 0
            
            for day in self.days:
                assignment = self.partial_roster[day.isoformat()][person.id]
                if assignment == ShiftType.COMET_NIGHT.value:
                    consecutive_count += 1
                else:
                    if consecutive_count > 0:
                        if consecutive_count == 1:
                            singletons += 1
                        else:
                            blocks += 1
                        consecutive_count = 0
            
            # Handle end of period
            if consecutive_count > 0:
                if consecutive_count == 1:
                    singletons += 1
                else:
                    blocks += 1
            
            total_blocks += blocks
            total_singletons += singletons
            
            if blocks > 0 or singletons > 0:
                print(f"  {person.name}: {blocks} blocks, {singletons} singletons")
        
        print(f"📈 Overall: {total_blocks} blocks, {total_singletons} singletons")
        if total_singletons > 0:
            singleton_percentage = (total_singletons / (total_blocks + total_singletons)) * 100
            print(f"🎯 Singleton rate: {singleton_percentage:.1f}% (should be minimal)")
        
        # Analyze week-level coverage patterns (4+3, 3+4, 2+2+3, etc.)
        print("\n📅 WEEK COVERAGE PATTERN ANALYSIS:")
        pattern_counts = {"4+3": 0, "3+4": 0, "2+2+3": 0, "2+3+2": 0, "3+2+2": 0, "other": 0}
        
        for i, (week_start, week_end) in enumerate(comet_week_ranges):
            week_start_idx = (week_start - self.start_date).days
            week_end_idx = (week_end - self.start_date).days
            week_days = [day for day in range(week_start_idx, min(week_end_idx + 1, len(self.days)))]
            
            # Find all blocks in this week
            week_blocks = []
            for p_idx, person in comet_eligible:
                consecutive_count = 0
                
                for day_idx in week_days:
                    if day_idx < len(self.days):
                        day_date = self.days[day_idx]
                        assignment = self.partial_roster[day_date.isoformat()][person.id]
                        
                        if assignment == ShiftType.COMET_NIGHT.value:
                            if consecutive_count == 0:
                                pass  # Start of new block
                            consecutive_count += 1
                        else:
                            if consecutive_count > 0:
                                week_blocks.append(consecutive_count)
                                consecutive_count = 0
                
                # Handle end of week
                if consecutive_count > 0:
                    week_blocks.append(consecutive_count)
            
            # Analyze the pattern
            week_blocks.sort(reverse=True)  # Sort largest first
            if len(week_blocks) == 2:
                if week_blocks == [4, 3]:
                    pattern_counts["4+3"] += 1
                    pattern = "4+3 ✅"
                elif week_blocks == [3, 4]:
                    pattern_counts["3+4"] += 1 
                    pattern = "3+4 ✅"
                else:
                    pattern_counts["other"] += 1
                    pattern = f"{week_blocks[0]}+{week_blocks[1]}"
            elif len(week_blocks) == 3:
                if week_blocks == [3, 2, 2]:
                    pattern_counts["3+2+2"] += 1
                    pattern = "3+2+2 ✅"
                elif week_blocks == [2, 2, 3]:
                    pattern_counts["2+2+3"] += 1
                    pattern = "2+2+3 ✅"
                elif week_blocks == [2, 3, 2]:
                    pattern_counts["2+3+2"] += 1
                    pattern = "2+3+2 ✅"
                else:
                    pattern_counts["other"] += 1
                    pattern = "+".join(map(str, week_blocks))
            else:
                pattern_counts["other"] += 1
                pattern = "+".join(map(str, week_blocks)) if week_blocks else "incomplete"
            
            print(f"  Week {i+1} ({week_start} to {week_end}): {pattern}")
        
        # Summary of patterns achieved
        total_weeks = len(comet_week_ranges)
        optimal_weeks = pattern_counts["4+3"] + pattern_counts["3+4"]
        good_weeks = pattern_counts["2+2+3"] + pattern_counts["2+3+2"] + pattern_counts["3+2+2"]
        
        print("\n🎯 PATTERN SUMMARY:")
        print(f"  Optimal patterns (4+3/3+4): {optimal_weeks}/{total_weeks} weeks ({100*optimal_weeks/total_weeks:.1f}%)")
        print(f"  Good patterns (2+2+3 variants): {good_weeks}/{total_weeks} weeks ({100*good_weeks/total_weeks:.1f}%)")
        print(f"  Other patterns: {pattern_counts['other']}/{total_weeks} weeks ({100*pattern_counts['other']/total_weeks:.1f}%)")
        
        # Count expected COMET nights needed
        expected_cmn = len([d for d in self.days if any(start <= d <= end for start, end in comet_week_ranges)])
        print(f"\nExpected COMET nights needed: {expected_cmn}")
        
        # Show unassigned nights
        if total_cmn_assigned < expected_cmn:
            unassigned_nights = []
            for day in self.days:
                if any(start <= day <= end for start, end in comet_week_ranges):
                    # Check if this night is assigned
                    day_assignments = self.partial_roster[day.isoformat()]
                    assigned = any(assignment == ShiftType.COMET_NIGHT.value 
                                 for pid, assignment in day_assignments.items())
                    if not assigned:
                        unassigned_nights.append(day)
            
            if unassigned_nights:
                print(f"⚠️  Unassigned COMET nights: {[day.strftime('%Y-%m-%d') for day in unassigned_nights]}")
        
        return SequentialSolveResult(
            stage="comet_nights",
            success=True,
            message=f"COMET nights completed. Assigned {total_cmn_assigned} COMET night shifts. Ready for unit nights.",
            partial_roster=copy.deepcopy(self.partial_roster),
            assigned_shifts=set(),  # Will track properly when integrated
            next_stage="nights"
        )
        
    def _assign_comet_night_blocks_sequentially(self, comet_week_ranges, comet_eligible, running_totals):
        """Week-focused assignment: Build optimal patterns within each week."""
        
        import random
        import time
        
        start_time = time.time()
        timeout_seconds = 120  # 2 minute timeout for block assignment
        
        random.seed(42)  # For reproducible results during testing
        
        # Week-focused assignment: Build optimal patterns within each week
        # Process weeks in order, trying to build optimal patterns
        weeks_completed = 0
        weeks_with_optimal_patterns = 0
        
        for week_idx, (week_start, week_end) in enumerate(comet_week_ranges):
            
            # Get available days in this week
            week_days = [day for day in self.days if week_start <= day <= week_end]
            available_days = []
            
            for day in week_days:
                # Check if this day is completely unassigned for COMET
                day_already_covered = False
                for person_id, assignment in self.partial_roster[day.isoformat()].items():
                    if assignment == ShiftType.COMET_NIGHT.value:
                        day_already_covered = True
                        break
                
                if not day_already_covered:
                    available_days.append(day)
            
            available_days.sort()
            
            if len(available_days) < 4:  # Skip weeks with too few available days
                continue
            
            # Try to build optimal patterns: 4+3, 3+4, 2+2+3, etc.
            pattern_built = self._try_build_optimal_week_pattern(
                available_days, week_start, week_end, comet_eligible, running_totals
            )
            
            if pattern_built:
                weeks_with_optimal_patterns += 1
            
            weeks_completed += 1
            
            # Check timeout
            elapsed_time = time.time() - start_time
            if elapsed_time > timeout_seconds:
                print(f"🚨 TIMEOUT: Block assignment exceeded {timeout_seconds} seconds after {weeks_completed} weeks")
                break
        
        # After week-focused assignment, do a few rounds of doctor-focused cleanup
        self._doctor_focused_cleanup_assignment(comet_week_ranges, comet_eligible, running_totals, max_rounds=20)
        
        # After assignment, check for any uncovered COMET nights
        print("\n" + "="*50)
        print("COMET NIGHT COVERAGE ANALYSIS")
        print("="*50)
        
        # Calculate total target COMET nights
        total_comet_nights = len([d for d in self.days if any(start <= d <= end for start, end in comet_week_ranges)])
        
        uncovered_days = []
        
        for week_start, week_end in comet_week_ranges:
            print(f"\nCOMET Week: {week_start} to {week_end}")
            week_uncovered = []
            
            for day in self.days:
                if week_start <= day <= week_end:
                    # Check if this day has COMET night coverage
                    day_assignments = self.partial_roster[day.isoformat()]
                    comet_assigned = any(assignment == ShiftType.COMET_NIGHT.value 
                                       for assignment in day_assignments.values())
                    
                    if comet_assigned:
                        assigned_doctor_id = [pid for pid, assignment in day_assignments.items() 
                                             if assignment == ShiftType.COMET_NIGHT.value][0]
                        # Find doctor name from ID
                        doctor_name = next((p.name for p in self.people if p.id == assigned_doctor_id), assigned_doctor_id)
                        print(f"  {day} ({day.strftime('%A')}): ✓ {doctor_name} ({assigned_doctor_id})")
                    else:
                        print(f"  {day} ({day.strftime('%A')}): ❌ NO COVERAGE")
                        uncovered_days.append(day)
                        week_uncovered.append(day)
            
            if week_uncovered:
                # Check if we still need more assignments
                total_assigned = sum(running_totals[p_idx]['comet_nights'] for p_idx, _ in comet_eligible)
                if total_assigned >= total_comet_nights:
                    print(f"  ✅ Week has {len(week_uncovered)} uncovered days, but target {total_comet_nights} nights already assigned ({total_assigned}) - skipping")
                    continue
                    
                print(f"  🔧 FIXING COVERAGE GAPS: {len(week_uncovered)} days need assignment")
                # First try to create blocks within this week
                if len(week_uncovered) >= 3:
                    print("     🎯 Attempting block assignments within week...")
                    remaining_days = self._try_assign_blocks_within_week(week_uncovered, comet_eligible, running_totals)
                    week_uncovered = remaining_days
                
                # Check again after block assignment
                total_assigned = sum(running_totals[p_idx]['comet_nights'] for p_idx, _ in comet_eligible)
                if total_assigned >= total_comet_nights:
                    print(f"     ✅ Target {total_comet_nights} nights reached ({total_assigned}) - stopping gap-filling")
                    break
                
                # Only resort to singletons for remaining days if still under target
                if week_uncovered:
                    nights_still_needed = total_comet_nights - total_assigned
                    if nights_still_needed > 0:
                        print(f"     ⚠️  RESORTING TO SINGLETON NIGHTS for {min(len(week_uncovered), nights_still_needed)} remaining days")
                        for i, day in enumerate(week_uncovered):
                            if i >= nights_still_needed:
                                break
                            self._assign_single_comet_night(day, comet_eligible, running_totals)
        
        print("\n" + "="*50)
        
        # Before gap-filling with singletons, try to eliminate singleton patterns
        # by redistributing existing blocks (convert 3+1 to 2+2)
        if uncovered_days:
            print(f"⚠️  ATTEMPTING TO FILL {len(uncovered_days)} UNCOVERED DAYS")
            print("🔧 First trying to eliminate singleton patterns by redistribution...")
            
            # Try to fix singleton patterns by redistributing blocks
            self._eliminate_singleton_patterns(comet_week_ranges, comet_eligible, running_totals)
        else:
            print("✅ ALL COMET WEEKS FULLY COVERED")
    
    def _select_next_doctor_for_comet_nights(self, comet_eligible, running_totals):
        """Select the doctor with the fewest COMET nights using WTE-adjusted distribution."""
        
        # Calculate total COMET nights dynamically from COMET weeks
        total_comet_nights = len(self.config.comet_on_weeks) * 7  # 7 nights per COMET week
        total_wte = sum(person.wte for _, person in comet_eligible)
        
        print(f"  WTE-adjusted distribution (total nights: {total_comet_nights}, total WTE: {total_wte:.1f}):")
        
        candidates = []
        all_satisfied = True
        
        for p_idx, person in comet_eligible:
            comet_nights = running_totals[p_idx]['comet_nights']
            
            # Calculate WTE-adjusted target for this doctor
            wte_target = (total_comet_nights * person.wte) / total_wte
            wte_ratio = comet_nights / wte_target if wte_target > 0 else 0
            
            # Check if this doctor has reached 90% of their WTE-adjusted target
            if comet_nights < wte_target * 0.9:
                all_satisfied = False
                # Use WTE-adjusted shortfall as priority (lower = higher priority)
                wte_shortfall = wte_target - comet_nights
                candidates.append((wte_shortfall, comet_nights, p_idx, person))
                print(f"    {person.name} (WTE {person.wte}): {comet_nights}/{wte_target:.1f} nights ({wte_ratio*100:.1f}% of WTE target)")
            else:
                print(f"    {person.name} (WTE {person.wte}): {comet_nights}/{wte_target:.1f} nights (✓ at WTE target)")
        
        # If all doctors have reached their WTE-adjusted targets, return None to end assignment
        if all_satisfied:
            print("  All doctors have reached their WTE-adjusted distribution targets")
            return None, None
        
        # Sort by WTE-adjusted shortfall (descending) - highest shortfall gets priority
        candidates.sort(key=lambda x: x[0], reverse=True)
        
        # Return the doctor with highest WTE-adjusted shortfall
        wte_shortfall, comet_nights, p_idx, person = candidates[0]
        wte_target = (total_comet_nights * person.wte) / total_wte
        print(f"  Selected {person.name} (has {comet_nights}/{wte_target:.1f} nights, shortfall: {wte_shortfall:.1f})")
        return p_idx, person
    
    def _eliminate_singleton_patterns(self, comet_week_ranges, comet_eligible, running_totals):
        """Try to eliminate singleton patterns by redistributing blocks within weeks"""
        
        eliminated_any = False
        
        for week_start, week_end in comet_week_ranges:
            # Convert dates to day indices  
            week_start_idx = (week_start - self.start_date).days
            week_end_idx = (week_end - self.start_date).days
            week_days = [day for day in range(week_start_idx, min(week_end_idx + 1, len(self.days)))]
            
            # Get current assignments for this week from partial_roster
            week_assignments = {}
            for day_idx in week_days:
                if day_idx < len(self.days):
                    day_date = self.days[day_idx]
                    for doctor_id in range(len(self.people)):
                        person_id = self.people[doctor_id].id
                        if self.partial_roster[day_date.isoformat()][person_id] == 'COMET_NIGHT':
                            if doctor_id not in week_assignments:
                                week_assignments[doctor_id] = []
                            week_assignments[doctor_id].append(day_idx)
            
            # Check if this week has uncovered days (potential singletons) using partial_roster
            uncovered_in_week = []
            for day_idx in week_days:
                if day_idx < len(self.days):
                    day_date = self.days[day_idx]
                    day_covered = False
                    for doctor_id in range(len(self.people)):
                        person_id = self.people[doctor_id].id
                        if self.partial_roster[day_date.isoformat()][person_id] == 'COMET_NIGHT':
                            day_covered = True
                            break
                    if not day_covered:
                        uncovered_in_week.append(day_idx)
            
            if len(uncovered_in_week) == 1 and week_assignments:
                gap_day = uncovered_in_week[0]
                print(f"🔍 Week {week_start}-{week_end}: Found potential singleton gap on day {gap_day}")
                
                # Look for a doctor with 3+ consecutive nights who could share
                for doctor_id, assigned_days in week_assignments.items():
                    if len(assigned_days) >= 3:
                        assigned_days.sort()
                        
                        # Find consecutive blocks
                        consecutive_blocks = self._find_consecutive_blocks(assigned_days)
                        
                        # Look for a 3+ block that we can split
                        for block in consecutive_blocks:
                            if len(block) >= 3:
                                print(f"🔧 Found {len(block)}-night block for {self.people[doctor_id].name}: days {block}")
                                
                                # Try to find another eligible doctor to take 2 nights
                                for other_doctor_id in comet_eligible:
                                    if (other_doctor_id != doctor_id and 
                                        running_totals[other_doctor_id] < self.target_comet_nights and
                                        len(week_assignments.get(other_doctor_id, [])) <= 2):  # Don't overload
                                        
                                        # Check if we can move 2 nights to eliminate the gap
                                        nights_to_move = block[-2:]  # Last 2 nights of the block
                                        
                                        # Verify this would help eliminate the gap
                                        remaining_block = block[:-2]
                                        if len(remaining_block) >= 1:  # Still leaves at least 1 night for original doctor
                                            
                                            print(f"🔄 Attempting to redistribute nights {nights_to_move} from {self.people[doctor_id].name} to {self.people[other_doctor_id].name}")
                                            
                                            # This is a heuristic approach - in practice we'd need to
                                            # re-solve or use more sophisticated constraint handling
                                            # For now, let's just log what we would do
                                            print(f"📝 Would redistribute: {self.people[doctor_id].name} keeps {remaining_block}, {self.people[other_doctor_id].name} gets {nights_to_move}")
                                            print(f"   This would leave gap {gap_day} to be filled by better block distribution")
                                            
                                            eliminated_any = True
                                            break
                                
                                if eliminated_any:
                                    break
                    
                    if eliminated_any:
                        break
        
        if eliminated_any:
            print("✅ Identified singleton patterns that could be eliminated through redistribution")
        else:
            print("ℹ️  No obvious singleton patterns found for redistribution")
            
        return eliminated_any
    
    def _find_consecutive_blocks(self, assigned_days):
        """Find consecutive blocks in a list of assigned days"""
        if not assigned_days:
            return []
            
        blocks = []
        current_block = [assigned_days[0]]
        
        for i in range(1, len(assigned_days)):
            if assigned_days[i] == assigned_days[i-1] + 1:
                current_block.append(assigned_days[i])
            else:
                blocks.append(current_block)
                current_block = [assigned_days[i]]
        
        blocks.append(current_block)
        return blocks
    
    def _assign_comet_night_block_smart(self, p_idx, person, preferred_block_sizes, comet_week_ranges, running_totals):
        """Doctor-centric block assignment that spreads doctors across different weeks."""
        
        # Strategy: Find the best week for THIS doctor to work, avoiding weeks where others are heavily assigned
        best_assignment = None
        best_score = -1
        
        for block_size in preferred_block_sizes:
            for week_start, week_end in comet_week_ranges:
                # Find available consecutive days in this week for this doctor
                week_days = [day for day in self.days if week_start <= day <= week_end]
                available_days = []
                
                for day in week_days:
                    # Check if this doctor is available on this day
                    if self.partial_roster[day.isoformat()][person.id] == ShiftType.OFF.value:
                        # Also check that no other doctor already has COMET_NIGHT on this day
                        day_already_covered = False
                        for other_person_id, assignment in self.partial_roster[day.isoformat()].items():
                            if assignment == ShiftType.COMET_NIGHT.value:
                                day_already_covered = True
                                break
                        
                        if not day_already_covered:
                            available_days.append(day)
                
                # Try to find consecutive blocks within available days
                if len(available_days) >= block_size:
                    available_days.sort()
                    
                    # Look for consecutive sequences
                    for start_idx in range(len(available_days) - block_size + 1):
                        consecutive_block = [available_days[start_idx]]
                        
                        # Build consecutive sequence
                        for i in range(1, block_size):
                            next_day = consecutive_block[-1] + timedelta(days=1)
                            if next_day in available_days:
                                consecutive_block.append(next_day)
                            else:
                                break
                        
                        # If we found a full consecutive block
                        if len(consecutive_block) == block_size:
                            # Score this assignment based on week diversity (prefer less crowded weeks)
                            score = self._score_week_for_doctor_assignment(week_start, week_end, p_idx)
                            
                            if score > best_score:
                                best_score = score
                                best_assignment = {
                                    'days': consecutive_block,
                                    'week_start': week_start,
                                    'week_end': week_end,
                                    'block_size': block_size
                                }
        
        if best_assignment:
            # Assign the best block found
            days = best_assignment['days']
            block_size = best_assignment['block_size']
            week_start = best_assignment['week_start']
            week_end = best_assignment['week_end']
            
            for day in days:
                self.partial_roster[day.isoformat()][person.id] = ShiftType.COMET_NIGHT.value
                running_totals[p_idx]['comet_nights'] += 1
            
            return True
        
        return False
    
    def _score_week_for_doctor_assignment(self, week_start, week_end, p_idx):
        """Score a week for doctor assignment - prefer weeks with fewer existing assignments."""
        
        # Count how many nights are already assigned in this week
        assigned_nights_in_week = 0
        week_days = [day for day in self.days if week_start <= day <= week_end]
        
        for day in week_days:
            day_str = day.isoformat()
            if day_str in self.partial_roster:
                for person_id, assignment in self.partial_roster[day_str].items():
                    if assignment == ShiftType.COMET_NIGHT.value:
                        assigned_nights_in_week += 1
        
        # Higher score for weeks with fewer assignments (encourages spreading)
        # Also add small random factor to break ties
        import random
        diversity_score = 100 - assigned_nights_in_week + random.random()
        
        return diversity_score
    
    def _try_assign_block_in_week(self, p_idx, person, block_sizes, week_start, week_end, uncovered_days, running_totals):
        """Try to assign a block within a specific week."""
        
        for block_size in block_sizes:
            if block_size > len(uncovered_days):
                continue
                
            # Find consecutive sequences of the right size
            for i in range(len(uncovered_days) - block_size + 1):
                potential_block = uncovered_days[i:i+block_size]
                
                # Check if these days are consecutive
                is_consecutive = True
                for j in range(1, len(potential_block)):
                    if potential_block[j] != potential_block[j-1] + 1:
                        is_consecutive = False
                        break
                
                if not is_consecutive:
                    continue
                
                # Check if person is available for all days in this block
                can_assign = True
                for day in potential_block:
                    day_date = self.days[day]
                    
                    # Check if already assigned
                    if self.partial_roster[day_date.isoformat()][person.id] != ShiftType.OFF.value:
                        can_assign = False
                        break
                    
                    # Check night rest constraint
                    if not self._check_night_rest_ok(day_date, person.id):
                        can_assign = False
                        break
                
                if can_assign:
                    # Assign this block using partial_roster only
                    for day in potential_block:
                        day_date = self.days[day]
                        self.partial_roster[day_date.isoformat()][person.id] = ShiftType.COMET_NIGHT.value
                        running_totals[p_idx]['comet_nights'] += 1
                    
                    return True
        
        return False
    
    def _assign_comet_night_block(self, p_idx, person, preferred_block_sizes, comet_week_ranges, running_totals):
        """Try to assign a COMET night block to the specified doctor."""
        
        # Show current doctor workload
        current_assignments = 0
        for day in self.days:
            if self.partial_roster[day.isoformat()][person.id] != ShiftType.OFF.value:
                current_assignments += 1
        print(f"    📊 {person.name} currently has {current_assignments} assigned days out of {len(self.days)}")
        
        for block_size in preferred_block_sizes:
            print(f"    🔍 Trying block size: {block_size}")
            blocks_tried = 0
            
            # Find available consecutive nights
            for week_start, week_end in comet_week_ranges:
                week_days = []
                for day in self.days:
                    if week_start <= day <= week_end:
                        week_days.append(day)
                
                # Try to find consecutive slots in this week
                for start_idx in range(len(week_days) - block_size + 1):
                    consecutive_days = week_days[start_idx:start_idx + block_size]
                    blocks_tried += 1
                    
                    # Check if all days are available for this person
                    available = True
                    unavailable_reason = None
                    unavailable_days = []
                    
                    for day in consecutive_days:
                        current_assignment = self.partial_roster[day.isoformat()][person.id]
                        if current_assignment != ShiftType.OFF.value:
                            available = False
                            unavailable_days.append(f"{day}({current_assignment})")
                    
                    if not available:
                        unavailable_reason = f"Days busy: {', '.join(unavailable_days[:3])}"  # Show first 3
                        if len(unavailable_days) > 3:
                            unavailable_reason += f" +{len(unavailable_days)-3} more"
                    
                    if available:
                        # Check if CMN is needed on these days (not already assigned to someone else)
                        cmn_needed = True
                        for day in consecutive_days:
                            # Check if another doctor already has CMN on this day
                            day_assignments = self.partial_roster[day.isoformat()]
                            if any(assignment == ShiftType.COMET_NIGHT.value for pid, assignment in day_assignments.items() if pid != person.id):
                                cmn_needed = False
                                break
                        
                        if cmn_needed:
                            # Assign the block!
                            print(f"    ✓ Assigning {block_size}-night block: {consecutive_days[0]} to {consecutive_days[-1]}")
                            
                            for day in consecutive_days:
                                self.partial_roster[day.isoformat()][person.id] = ShiftType.COMET_NIGHT.value
                            
                            # Update running totals
                            running_totals[p_idx]['comet_nights'] += block_size
                            running_totals[p_idx]['total_nights'] += block_size
                            running_totals[p_idx]['total_hours'] += block_size * 12  # 12 hours per CMN
                            running_totals[p_idx]['blocks_assigned'] += 1
                            
                            # Display updated totals
                            print(f"    Updated totals for {person.name}:")
                            print(f"      COMET nights: {running_totals[p_idx]['comet_nights']}")
                            print(f"      Total hours: {running_totals[p_idx]['total_hours']}")
                            avg_weekly = (running_totals[p_idx]['total_hours'] / len(self.days)) * 7
                            print(f"      Avg weekly hours: {avg_weekly:.1f}")
                            
                            return True
            
            print(f"    ❌ No {block_size}-night block available (tried {blocks_tried // len(preferred_block_sizes)} positions)")
        
        print(f"  🚫 No suitable {preferred_block_sizes} block found for {person.name}")
        if 'unavailable_reason' in locals():
            print(f"     Last rejection: {unavailable_reason}")
        return False
    
    def _try_assign_blocks_within_week(self, uncovered_days, comet_eligible, running_totals):
        """Try to assign blocks within a specific week's uncovered days."""
        remaining_days = uncovered_days.copy()
        
        # Sort days to ensure consecutive assignment attempts
        remaining_days.sort()
        
        # Try different block sizes starting with larger ones
        for block_size in [4, 3, 2]:
            if len(remaining_days) < block_size:
                continue
                
            # Try to find consecutive days for blocks
            for start_idx in range(len(remaining_days) - block_size + 1):
                consecutive_days = []
                
                # Check if we have enough consecutive days
                for i in range(block_size):
                    if start_idx + i < len(remaining_days):
                        day = remaining_days[start_idx + i]
                        if i == 0 or (day - consecutive_days[-1]).days == 1:
                            consecutive_days.append(day)
                        else:
                            break
                
                if len(consecutive_days) == block_size:
                    # Select the doctor with highest WTE-adjusted shortfall for gap-filling
                    selected_doctor = self._select_doctor_for_gap_filling(consecutive_days, comet_eligible, running_totals)
                    
                    if selected_doctor:
                        p_idx, person = selected_doctor
                        # Assign the block
                        for day in consecutive_days:
                            self.partial_roster[day.isoformat()][person.id] = ShiftType.COMET_NIGHT.value
                            running_totals[p_idx]['comet_nights'] += 1
                        
                        print(f"       ✅ Assigned {block_size}-night block to {person.name}: {[d.strftime('%m-%d') for d in consecutive_days]}")
                        
                        # Remove assigned days from remaining
                        for day in consecutive_days:
                            if day in remaining_days:
                                remaining_days.remove(day)
                        
                        # Start over with the remaining days
                        return self._try_assign_blocks_within_week(remaining_days, comet_eligible, running_totals)
        
        return remaining_days
    
    def _select_doctor_for_gap_filling(self, consecutive_days, comet_eligible, running_totals):
        """Select the best doctor for gap-filling using WTE-adjusted fairness."""
        
        total_comet_nights = len(self.config.comet_on_weeks) * 7
        total_wte = sum(person.wte for _, person in comet_eligible)
        
        candidates = []
        
        for p_idx, person in comet_eligible:
            # Check if this doctor can be assigned this block
            if self._can_assign_block_to_doctor(consecutive_days, person, p_idx):
                comet_nights = running_totals[p_idx]['comet_nights']
                
                # Calculate WTE-adjusted target and shortfall
                wte_target = (total_comet_nights * person.wte) / total_wte
                wte_shortfall = wte_target - comet_nights
                
                # Only consider doctors who are below their target
                if wte_shortfall > 0:
                    candidates.append((wte_shortfall, p_idx, person))
        
        if candidates:
            # Sort by highest shortfall (most in need)
            candidates.sort(key=lambda x: x[0], reverse=True)
            wte_shortfall, p_idx, person = candidates[0]
            return (p_idx, person)
        
        return None
    
    def _can_assign_block_to_doctor(self, consecutive_days, person, person_idx):
        """Check if a doctor can be assigned a block of consecutive days."""
        for day in consecutive_days:
            # Check if doctor is available (not assigned OFF or another shift)
            current_assignment = self.partial_roster[day.isoformat()][person.id]
            if current_assignment != ShiftType.OFF.value:
                return False
            
            # Check that no other doctor already has COMET_NIGHT on this day
            for other_person_id, assignment in self.partial_roster[day.isoformat()].items():
                if assignment == ShiftType.COMET_NIGHT.value:
                    return False
                
            # Simple constraint check: no previous/next night shifts for this doctor
            # Check day before and after for existing night assignments
            prev_day = day - timedelta(days=1)
            next_day = day + timedelta(days=1)
            
            for check_day in [prev_day, next_day]:
                if check_day.isoformat() in self.partial_roster:
                    check_assignment = self.partial_roster[check_day.isoformat()][person.id]
                    if check_assignment == ShiftType.COMET_NIGHT.value:
                        return False
        
        return True
    
    def _assign_single_comet_night(self, day, comet_eligible, running_totals):
        """Assign a single COMET night to fill coverage gaps."""
        print(f"    🔧 SINGLE NIGHT ASSIGNMENT for {day} ({day.strftime('%A')})")
        
        # First check if this day already has a COMET night assignment
        for person_id, assignment in self.partial_roster[day.isoformat()].items():
            if assignment == ShiftType.COMET_NIGHT.value:
                print(f"    ℹ️  Day {day} already has COMET night coverage - skipping")
                return True
        
        # Find the doctor with the least COMET nights (WTE-adjusted)
        best_doctor = None
        min_adjusted_nights = float('inf')
        
        for p_idx, person in comet_eligible:
            comet_nights = running_totals[p_idx]['comet_nights']
            wte_adjusted_nights = comet_nights / person.wte if person.wte > 0 else float('inf')
            
            # Check if this doctor is available on this day
            current_assignment = self.partial_roster[day.isoformat()][person.id]
            if current_assignment == ShiftType.OFF.value and wte_adjusted_nights < min_adjusted_nights:
                # Also check 46h rest constraint
                if self._check_night_rest_ok(day, person.id):
                    min_adjusted_nights = wte_adjusted_nights
                    best_doctor = (p_idx, person)
        
        if best_doctor:
            p_idx, person = best_doctor
            self.partial_roster[day.isoformat()][person.id] = ShiftType.COMET_NIGHT.value
            running_totals[p_idx]['comet_nights'] += 1
            running_totals[p_idx]['total_nights'] += 1
            running_totals[p_idx]['total_hours'] += 12
            print(f"    ✓ Assigned single COMET night to {person.name} on {day}")
            return True
        else:
            print(f"    ❌ No doctor available for single COMET night on {day}")
            return False
    
    def _check_night_rest_ok(self, night_day, doctor_id):
        """Check if assigning a night shift on this day would violate 46h rest rule.
        
        The 46h rest rule applies AFTER the end of a night shift BLOCK, not after every individual night.
        For consecutive nights, only the day after the LAST night needs to be free.
        
        CRITICAL: Must check BOTH directions:
        - BACKWARD: Has there been 46h rest SINCE the last night block ended?
        - FORWARD: Will there be 46h rest AFTER this night block ends?
        
        Example: Sun-Wed COMET nights (4x12h = 48h total)
        - Thu must be OFF (46h rest before Fri 8am)  
        - Fri onwards can work normally
        """
        
        night_day_idx = None
        for i, day in enumerate(self.days):
            if day == night_day:
                night_day_idx = i
                break
        
        if night_day_idx is None:
            return True  # Day not found, assume OK
        
        night_shift_types = [ShiftType.COMET_NIGHT.value, ShiftType.NIGHT_REG.value, ShiftType.NIGHT_SHO.value]
        
        # ========================================
        # BACKWARD CHECK: Has 46h rest passed since last night block END?
        # ========================================
        
        # Look backward to find the most recent night block END
        block_end_idx = None
        
        for lookback_idx in range(night_day_idx - 1, max(-1, night_day_idx - 5), -1):
            prev_day = self.days[lookback_idx]
            prev_assignment = self.partial_roster[prev_day.isoformat()][doctor_id]
            
            if prev_assignment in night_shift_types:
                # Found a night shift - check if this is the END of the block
                # (the day AFTER this night is NOT a night shift)
                if lookback_idx + 1 < len(self.days):
                    day_after = self.days[lookback_idx + 1]
                    day_after_assignment = self.partial_roster[day_after.isoformat()][doctor_id]
                    
                    if day_after_assignment not in night_shift_types:
                        # This is the end of a night block
                        block_end_idx = lookback_idx
                        break
                else:
                    # End of roster, so this is block end
                    block_end_idx = lookback_idx
                    break
        
        # If we found a night block end, check if enough rest has passed
        if block_end_idx is not None:
            days_of_rest = night_day_idx - block_end_idx - 1
            
            if days_of_rest < 2:
                # Violation: Not enough rest since last night block
                block_end_date = self.days[block_end_idx]
                print(f"      ❌ BACKWARD VIOLATION: {doctor_id} night block ended {block_end_date}, only {days_of_rest} rest days before {night_day}")
                return False
        
        # ========================================
        # FORWARD CHECK: Will there be 46h rest AFTER this night block?
        # ========================================
        
        # Check if this would be the END of a night block
        # Look ahead to see if more nights follow
        is_block_end = True
        if night_day_idx + 1 < len(self.days):
            next_day = self.days[night_day_idx + 1]
            next_assignment = self.partial_roster[next_day.isoformat()][doctor_id]
            if next_assignment in night_shift_types:
                is_block_end = False  # More nights in this block
        
        # If this is the end of a night block, check 46h rest FORWARD
        if is_block_end and night_day_idx + 1 < len(self.days):
            rest_day = self.days[night_day_idx + 1]
            rest_assignment = self.partial_roster[rest_day.isoformat()][doctor_id]
            
            # Must have at least one full day off after night block ends
            working_shifts = [ShiftType.COMET_DAY.value, ShiftType.LONG_DAY_REG.value, 
                            ShiftType.LONG_DAY_SHO.value, ShiftType.SHORT_DAY.value,
                            ShiftType.NIGHT_REG.value, ShiftType.NIGHT_SHO.value]
            
            if rest_assignment in working_shifts:
                print(f"      ❌ FORWARD VIOLATION: {doctor_id} would work {rest_assignment} on {rest_day} (day after night block)")
                return False
        
        return True
    
    def _assign_unit_night_blocks_with_cpsat(self, unit_night_days, unit_night_eligible, running_totals, timeout_seconds=120):
        """Use CP-SAT to assign unit nights with proper rest constraints and block preferences.
        
        This replaces the greedy algorithm with a constraint-based approach that:
        - Enforces 46h rest rule in both directions (backward + forward)
        - Maintains block preference through objective function
        - Guarantees WTE-adjusted fairness
        - Provides global optimization instead of local greedy choices
        """
        
        model = cp_model.CpModel()
        
        print("\n🔧 Using CP-SAT solver for unit nights with rest constraints")
        print(f"   Days to cover: {len(unit_night_days)}")
        print(f"   Registrars available: {len(unit_night_eligible)}")
        
        # Decision variables: x[p_idx, d_idx] = 1 if person p works unit night on day d
        x = {}
        for p_idx, person in unit_night_eligible:
            for d_idx, day in enumerate(unit_night_days):
                day_str = day.isoformat()
                current_assignment = self.partial_roster[day_str][person.id]
                
                # Only create variable if day is currently OFF
                if current_assignment == ShiftType.OFF.value:
                    x[p_idx, d_idx] = model.NewBoolVar(f"unit_night_{p_idx}_{d_idx}")
        
        print(f"   Decision variables created: {len(x)}")
        
        # ========================================
        # CONSTRAINT 1: Exactly 1 registrar per night (coverage)
        # ========================================
        for d_idx, day in enumerate(unit_night_days):
            day_vars = [x[p_idx, d_idx] for p_idx, _ in unit_night_eligible if (p_idx, d_idx) in x]
            if day_vars:
                model.Add(sum(day_vars) == 1)
        
        # ========================================
        # CONSTRAINT 2: 46-hour rest rule (FORWARD)
        # If working night on day D, must be OFF on days D+1 and D+2
        # ========================================
        for p_idx, person in unit_night_eligible:
            for d_idx in range(len(unit_night_days)):
                if (p_idx, d_idx) not in x:
                    continue
                    
                night_var = x[p_idx, d_idx]
                
                # Check next 2 days for rest requirement
                for rest_offset in [1, 2]:
                    rest_d_idx = d_idx + rest_offset
                    if rest_d_idx >= len(unit_night_days):
                        continue
                    
                    rest_day = unit_night_days[rest_d_idx]
                    rest_day_str = rest_day.isoformat()
                    current_rest_assignment = self.partial_roster[rest_day_str][person.id]
                    
                    # If already assigned a working shift on rest day, prevent this night
                    working_shifts = [ShiftType.COMET_NIGHT.value, ShiftType.NIGHT_REG.value, 
                                    ShiftType.NIGHT_SHO.value, ShiftType.COMET_DAY.value,
                                    ShiftType.LONG_DAY_REG.value, ShiftType.LONG_DAY_SHO.value,
                                    ShiftType.SHORT_DAY.value]
                    
                    if current_rest_assignment in working_shifts:
                        # Already working on required rest day - prevent this night
                        model.Add(night_var == 0)
                    elif (p_idx, rest_d_idx) in x:
                        # Variable exists for rest day - prevent working
                        model.Add(x[p_idx, rest_d_idx] == 0).OnlyEnforceIf(night_var)
        
        # ========================================
        # CONSTRAINT 3: 46-hour rest rule (BACKWARD)
        # Can't work if a night block ended less than 2 days ago
        # ========================================
        
        # Build a mapping of all days (not just unit_night_days) to check previous assignments
        day_to_idx_map = {day: idx for idx, day in enumerate(self.days)}
        
        for p_idx, person in unit_night_eligible:
            for d_idx, day in enumerate(unit_night_days):
                if (p_idx, d_idx) not in x:
                    continue
                
                # Find this day's position in the full roster
                full_roster_idx = day_to_idx_map.get(day)
                if full_roster_idx is None:
                    continue
                
                # Look back up to 4 days in the FULL roster to find recent night blocks
                for lookback in range(1, 5):
                    prev_full_idx = full_roster_idx - lookback
                    if prev_full_idx < 0:
                        break
                    
                    prev_day = self.days[prev_full_idx]
                    prev_day_str = prev_day.isoformat()
                    prev_assignment = self.partial_roster[prev_day_str][person.id]
                    
                    night_types = [ShiftType.COMET_NIGHT.value, ShiftType.NIGHT_REG.value, ShiftType.NIGHT_SHO.value]
                    
                    if prev_assignment in night_types:
                        # Found a night shift - check if this was the END of a block
                        is_block_end = True
                        
                        if prev_full_idx + 1 < len(self.days):
                            day_after_prev = self.days[prev_full_idx + 1]
                            day_after_str = day_after_prev.isoformat()
                            day_after_assignment = self.partial_roster[day_after_str][person.id]
                            
                            if day_after_assignment in night_types:
                                # Next day was also a night, so not block end yet
                                is_block_end = False
                        
                        if is_block_end:
                            # This was the end of a night block
                            # Calculate actual days between block end and current day
                            days_since_block_end = full_roster_idx - prev_full_idx - 1
                            
                            if days_since_block_end < 2:
                                # Not enough rest - prevent this assignment
                                model.Add(x[p_idx, d_idx] == 0)
                                print(f"   🚫 Preventing {person.id} on {day} (night block ended {prev_day}, only {days_since_block_end} rest days)")
                            
                            # Found the most recent block end, stop looking
                            break
        
        # ========================================
        # CONSTRAINT 4: No assignment if already doing COMET night on same day
        # ========================================
        for p_idx, person in unit_night_eligible:
            for d_idx, day in enumerate(unit_night_days):
                if (p_idx, d_idx) in x:
                    day_str = day.isoformat()
                    current = self.partial_roster[day_str][person.id]
                    
                    if current == ShiftType.COMET_NIGHT.value:
                        model.Add(x[p_idx, d_idx] == 0)
        
        # ========================================
        # OBJECTIVE: Strong block preference + WTE-adjusted fairness
        # ========================================
        
        objective_terms = []
        
        # Part 1: STRONG block preference with multiple reward levels
        # This mimics the greedy algorithm's preference for 2-4 night blocks
        
        for p_idx, person in unit_night_eligible:
            # Reward blocks of different sizes with escalating bonuses
            
            # 4-night blocks (highest reward) - like greedy prefers 4-night blocks
            for d_idx in range(len(unit_night_days) - 3):
                if all((p_idx, d_idx + offset) in x for offset in range(4)):
                    block_4_var = model.NewBoolVar(f"block4_{p_idx}_{d_idx}")
                    model.Add(block_4_var >= sum(x[p_idx, d_idx + offset] for offset in range(4)) - 3)
                    objective_terms.append(block_4_var * 200)  # +200 for 4-night block
            
            # 3-night blocks (high reward)
            for d_idx in range(len(unit_night_days) - 2):
                if all((p_idx, d_idx + offset) in x for offset in range(3)):
                    block_3_var = model.NewBoolVar(f"block3_{p_idx}_{d_idx}")
                    model.Add(block_3_var >= sum(x[p_idx, d_idx + offset] for offset in range(3)) - 2)
                    objective_terms.append(block_3_var * 120)  # +120 for 3-night block
            
            # 2-night blocks (good reward)
            for d_idx in range(len(unit_night_days) - 1):
                if (p_idx, d_idx) in x and (p_idx, d_idx + 1) in x:
                    block_2_var = model.NewBoolVar(f"block2_{p_idx}_{d_idx}")
                    model.Add(block_2_var >= x[p_idx, d_idx] + x[p_idx, d_idx + 1] - 1)
                    objective_terms.append(block_2_var * 50)  # +50 for 2-night block
            
            # PENALTY for singletons (isolated nights)
            for d_idx in range(len(unit_night_days)):
                if (p_idx, d_idx) not in x:
                    continue
                
                # Check if this night is isolated (not part of a block)
                is_isolated = True
                
                # Check if previous day is also worked
                if d_idx > 0 and (p_idx, d_idx - 1) in x:
                    prev_connected = model.NewBoolVar(f"prev_conn_{p_idx}_{d_idx}")
                    model.Add(prev_connected >= x[p_idx, d_idx] + x[p_idx, d_idx - 1] - 1)
                    is_isolated = False
                
                # Check if next day is also worked  
                if d_idx < len(unit_night_days) - 1 and (p_idx, d_idx + 1) in x:
                    next_connected = model.NewBoolVar(f"next_conn_{p_idx}_{d_idx}")
                    model.Add(next_connected >= x[p_idx, d_idx] + x[p_idx, d_idx + 1] - 1)
                    is_isolated = False
                
                # If truly isolated (no prev or next), penalize it
                if is_isolated:
                    singleton_var = model.NewBoolVar(f"singleton_{p_idx}_{d_idx}")
                    model.Add(singleton_var == x[p_idx, d_idx])
                    objective_terms.append(singleton_var * -100)  # -100 penalty for singleton
        
        # Part 2: WTE-adjusted fairness (with reduced weight to allow blocks)
        total_wte = sum(person.wte for _, person in unit_night_eligible)
        
        for p_idx, person in unit_night_eligible:
            # Count assignments for this person
            person_night_vars = [x[p_idx, d_idx] for d_idx in range(len(unit_night_days)) 
                                if (p_idx, d_idx) in x]
            
            if person_night_vars:
                count_var = model.NewIntVar(0, len(unit_night_days), f"count_{p_idx}")
                model.Add(count_var == sum(person_night_vars))
                
                # Expected share based on WTE
                wte_proportion = person.wte / total_wte if total_wte > 0 else 0
                expected_count = int(len(unit_night_days) * wte_proportion)
                
                # Minimize deviation from expected (but with lower weight than block bonuses)
                deviation_var = model.NewIntVar(-len(unit_night_days), len(unit_night_days), f"dev_{p_idx}")
                model.Add(deviation_var == count_var - expected_count)
                
                abs_deviation = model.NewIntVar(0, len(unit_night_days), f"abs_dev_{p_idx}")
                model.AddAbsEquality(abs_deviation, deviation_var)
                
                # Reduced weight: -5 per deviation unit (vs block bonuses of 50-200)
                objective_terms.append(abs_deviation * -5)
        
        # Combined objective: Heavily favor blocks, then optimize fairness
        if objective_terms:
            model.Maximize(sum(objective_terms))
        
        # ========================================
        # SOLVE
        # ========================================
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = timeout_seconds
        solver.parameters.log_search_progress = False
        
        print("🔍 Solving CP-SAT model with rest constraints...")
        status = solver.Solve(model)
        
        if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
            solution_type = "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE"
            print(f"✅ CP-SAT solution found: {solution_type}")
            
            # Extract assignments
            assignments_made = 0
            for p_idx, person in unit_night_eligible:
                for d_idx, day in enumerate(unit_night_days):
                    if (p_idx, d_idx) in x and solver.Value(x[p_idx, d_idx]) == 1:
                        day_str = day.isoformat()
                        self.partial_roster[day_str][person.id] = ShiftType.NIGHT_REG.value
                        running_totals[p_idx]['unit_nights'] += 1
                        running_totals[p_idx]['total_nights'] += 1
                        running_totals[p_idx]['total_hours'] += 13  # Unit nights are 13 hours
                        assignments_made += 1
            
            print(f"   Assigned {assignments_made} unit night shifts")
            return True
        else:
            print(f"❌ CP-SAT solver failed: {solver.StatusName(status)}")
            return False
    
    def _solve_comet_days_stage(self, timeout_seconds: int) -> SequentialSolveResult:
        """Stage 4: Assign COMET day shifts after holidays are covered."""
        
        print("=" * 80)
        print("COMET DAYS STAGE: Assign day shifts for COMET weeks")
        print("=" * 80)
        
        # Get COMET eligible doctors
        comet_eligible = [(i, p) for i, p in enumerate(self.people) if p.comet_eligible]
        if not comet_eligible:
            return SequentialSolveResult(
                stage="comet_days",
                success=False,
                message="No COMET eligible doctors found for day shifts",
                partial_roster=copy.deepcopy(self.partial_roster),
                next_stage="weekday_long_days"
            )
        
        # Identify COMET weeks
        comet_week_ranges = []
        for monday in self.config.comet_on_weeks:
            week_end = monday + timedelta(days=6) 
            comet_week_ranges.append((monday, week_end))
        
        print(f"COMET weeks to cover: {len(comet_week_ranges)}")
        for i, (start, end) in enumerate(comet_week_ranges):
            print(f"  Week {i+1}: {start} to {end}")
        
        # TODO: Implement COMET day assignment logic
        # For now, return success to continue the chain
        print("\n⚠️  COMET days assignment not yet implemented - placeholder stage")
        
        return SequentialSolveResult(
            stage="comet_days",
            success=True,
            message="COMET days stage completed (placeholder). Ready for weekday long days.",
            partial_roster=copy.deepcopy(self.partial_roster),
            assigned_shifts=set(),
            next_stage="weekday_long_days"
        )
    
    def _solve_nights_stage(self, timeout_seconds: int) -> SequentialSolveResult:
        """Stage 2: Assign Unit Night shifts - exactly 1 N_REG per day (all days, including COMET days) using sequential assignment."""
        
        print("================================================================================")
        print("UNIT NIGHTS STAGE: Sequential Assignment")
        print("================================================================================")
        
        # Get all registrars who can work unit nights 
        unit_night_eligible = []
        for p_idx, person in enumerate(self.people):
            if person.grade == "Registrar":
                unit_night_eligible.append((p_idx, person))
        
        if not unit_night_eligible:
            return SequentialSolveResult(
                stage="nights",
                success=False,
                message="No registrars available for unit night shifts.",
                partial_roster=copy.deepcopy(self.partial_roster),
                next_stage="weekend_holidays"
            )
        
        print(f"Found {len(unit_night_eligible)} unit night eligible registrars:")
        
        # Unit Night Registrar Key - Full name to ID mapping  
        print("\n📋 UNIT NIGHT REGISTRAR KEY:")
        for p_idx, person in unit_night_eligible:
            print(f"  {person.id} = {person.name} (WTE: {person.wte})")
        print()
        
        for p_idx, person in unit_night_eligible:
            print(f"  {person.name} (WTE: {person.wte})")
        
        # Identify ALL days that need unit night coverage (including COMET days)
        unit_night_days = []
        comet_days = set()
        
        # First, convert COMET week dates to week ranges for reference
        comet_week_ranges = []
        for monday in self.config.comet_on_weeks:
            week_end = monday + timedelta(days=6) 
            comet_week_ranges.append((monday, week_end))
        
        # Identify all COMET days for reference
        for week_start, week_end in comet_week_ranges:
            for day in self.days:
                if week_start <= day <= week_end:
                    comet_days.add(day)
        
        # Unit nights cover ALL days (COMET nights are additional coverage)
        unit_night_days = list(self.days)
        
        print(f"\nUnit night days to cover: {len(unit_night_days)}")
        print(f"COMET days (also covered): {len(comet_days)}")
        print(f"Total days: {len(self.days)}")
        
        # Calculate targets for WTE-based fairness
        total_unit_nights = len(unit_night_days)
        print(f"Total unit nights to assign: {total_unit_nights}")
        print(f"Target per registrar (equal distribution): {total_unit_nights / len(unit_night_eligible):.1f}")
        
        # Initialize running totals for unit nights
        running_totals = {}
        for p_idx, person in unit_night_eligible:
            running_totals[p_idx] = {
                'unit_nights': 0,
                'total_nights': 0,
                'total_hours': 0
            }
        
        print("\n==================================================")
        print("STEP 1: UNIT NIGHT ASSIGNMENTS")
        print("==================================================")
        
        # Use CP-SAT solver with rest constraints (replaces greedy algorithm)
        result = self._assign_unit_night_blocks_with_cpsat(unit_night_days, unit_night_eligible, running_totals, timeout_seconds)
        
        if not result:
            return SequentialSolveResult(
                stage="nights",
                success=False,
                message="Failed to assign unit nights using CP-SAT solver.",
                partial_roster=copy.deepcopy(self.partial_roster),
                next_stage="weekend_holidays"
            )
        
        # Count final assignments
        total_assigned = sum(running_totals[p_idx]['unit_nights'] for p_idx, _ in unit_night_eligible)
        
        # Display final results
        self._display_unit_night_coverage_analysis(unit_night_days, unit_night_eligible, running_totals)
        
        return SequentialSolveResult(
            stage="nights",
            success=True,
            message=f"Unit nights completed. Assigned {total_assigned} unit night shifts. Ready for weekend/holidays.",
            partial_roster=copy.deepcopy(self.partial_roster),
            assigned_shifts=set(),  # Will track properly when integrated
            next_stage="weekend_holidays"
        )
        
    def _assign_unit_night_blocks_sequentially(self, unit_night_days, unit_night_eligible, running_totals):
        """Week-by-week block assignment: Reuse COMET block logic for entire rota window."""
        
        import time
        from datetime import timedelta
        
        start_time = time.time()
        timeout_seconds = 120
        
        # Process all weeks in the rota period, not just those with unit nights
        # This allows proper block assignment across the entire window
        current_week_start = self.days[0]
        weeks_completed = 0
        weeks_with_optimal_patterns = 0
        
        while current_week_start <= self.days[-1]:
            week_end = current_week_start + timedelta(days=6)
            
            # Find unit night days in this week (ALL days need unit nights)
            week_unit_nights = []
            
            for day_offset in range(7):
                day = current_week_start + timedelta(days=day_offset)
                if day > self.days[-1]:
                    break
                    
                # All days need unit night coverage (regardless of COMET assignments)
                week_unit_nights.append(day)
            
            # If this week has unit nights to assign, use block logic
            if len(week_unit_nights) >= 2:
                pattern_built = self._assign_unit_night_blocks_greedy(week_unit_nights, unit_night_eligible, running_totals)
                if pattern_built:
                    weeks_with_optimal_patterns += 1
                    
            elif len(week_unit_nights) == 1:
                # Single day - assign directly
                self._assign_single_unit_night(week_unit_nights[0], unit_night_eligible, running_totals)
            
            weeks_completed += 1
            current_week_start += timedelta(days=7)
            
            # Check timeout
            elapsed_time = time.time() - start_time
            if elapsed_time > timeout_seconds:
                break
        
        print(f"📅 Unit night weeks: {weeks_completed} processed, {weeks_with_optimal_patterns} with optimal patterns")
        
        return True
    
    def _assign_unit_night_blocks_greedy(self, week_unit_nights, unit_night_eligible, running_totals):
        """Greedy block assignment for unit nights in a week."""
        
        week_unit_nights.sort()
        assigned_days = set()
        
        # Try to form 2-4 night blocks
        for start_idx in range(len(week_unit_nights)):
            if week_unit_nights[start_idx] in assigned_days:
                continue
                
            # Try different block sizes (prefer larger blocks)
            for block_size in [4, 3, 2]:
                if start_idx + block_size > len(week_unit_nights):
                    continue
                    
                # Check if these days are consecutive
                block_days = week_unit_nights[start_idx:start_idx + block_size]
                consecutive = all((block_days[i] - block_days[i-1]).days == 1 
                                for i in range(1, len(block_days)))
                
                if consecutive and all(day not in assigned_days for day in block_days):
                    # Try to assign this block
                    selected_registrar = self._select_registrar_for_unit_night_block(
                        block_size, block_days, unit_night_eligible, running_totals
                    )
                    
                    if selected_registrar:
                        # Assign the block
                        for day in block_days:
                            self.partial_roster[day.isoformat()][selected_registrar.id] = ShiftType.NIGHT_REG.value
                            assigned_days.add(day)
                            
                        # Update running totals
                        for p_idx, person in unit_night_eligible:
                            if person.id == selected_registrar.id:
                                running_totals[p_idx]['unit_nights'] += block_size
                                running_totals[p_idx]['total_nights'] += block_size
                                running_totals[p_idx]['total_hours'] += block_size * 12
                                break
                        break
        
        # Assign any remaining single days
        for day in week_unit_nights:
            if day not in assigned_days:
                self._assign_single_unit_night(day, unit_night_eligible, running_totals)
                
        return True
    
    def _select_registrar_for_unit_night_block(self, block_size, block_days, 
                                             unit_night_eligible, running_totals):
        """Select best registrar for a unit night block (reuse COMET logic)."""
        
        # Calculate WTE-adjusted assignments for fairness
        wte_adjusted_totals = []
        for p_idx, person in unit_night_eligible:
            unit_nights = running_totals[p_idx]['unit_nights']
            wte_adjusted = unit_nights / person.wte if person.wte > 0 else unit_nights
            wte_adjusted_totals.append(wte_adjusted)
        
        # Find registrars who can work all days in the block
        available_registrars = []
        for i, (p_idx, person) in enumerate(unit_night_eligible):
            can_work_block = True
            
            for day in block_days:
                # Check if already assigned
                current_assignment = self.partial_roster[day.isoformat()][person.id]
                if current_assignment != ShiftType.OFF.value:
                    can_work_block = False
                    break
                    
                # Check rest constraints (simplified)
                if not self._check_night_rest_ok(day, person.id):
                    can_work_block = False
                    break
            
            if can_work_block:
                available_registrars.append((p_idx, person, wte_adjusted_totals[i]))
        
        if not available_registrars:
            return None
            
        # Prefer part-time doctors for smaller blocks (WTE < 1.0)
        # and less assigned doctors overall
        if block_size <= 3:
            part_time_doctors = [(p_idx, person, wte_adj) for p_idx, person, wte_adj in available_registrars 
                               if person.wte < 1.0]
            if part_time_doctors:
                available_registrars = part_time_doctors
        
        # Select doctor with lowest WTE-adjusted assignment count
        available_registrars.sort(key=lambda x: x[2])
        return available_registrars[0][1]
    
    def _display_unit_night_coverage_analysis(self, unit_night_days, unit_night_eligible, running_totals):
        """Display analysis of unit night coverage."""
        
        print("\n" + "=" * 50)
        print("UNIT NIGHT COVERAGE ANALYSIS")
        print("=" * 50)
        
        # Count assigned vs unassigned days
        covered_days = 0
        for day in unit_night_days:
            for person_id, assignment in self.partial_roster[day.isoformat()].items():
                if assignment == ShiftType.NIGHT_REG.value:
                    covered_days += 1
                    break
        
        print(f"\nUnit night days covered: {covered_days}/{len(unit_night_days)}")
        
        if covered_days == len(unit_night_days):
            print("✅ ALL UNIT NIGHT DAYS FULLY COVERED")
        else:
            print(f"❌ {len(unit_night_days) - covered_days} unit night days uncovered")
        
        print("\nFinal Unit Night assignments:")
        for p_idx, person in unit_night_eligible:
            unit_nights = running_totals[p_idx]['unit_nights']
            wte_adjusted = unit_nights / person.wte if person.wte > 0 else unit_nights
            print(f"  {person.name}: {unit_nights} N_REG shifts (WTE-adjusted: {wte_adjusted:.1f})")
        
        total_assigned = sum(running_totals[p_idx]['unit_nights'] for p_idx, person in unit_night_eligible)
        print(f"\nTotal unit nights assigned: {total_assigned}")
            
    def _assign_single_unit_night(self, day, unit_night_eligible, running_totals):
        """Assign a single unit night day (in addition to any COMET nights on the same day)."""
        
        # Find available registrars for this day (excluding those already doing COMET night)
        available_registrars = []
        for p_idx, person in unit_night_eligible:
            current_assignment = self.partial_roster[day.isoformat()][person.id]
            # Don't assign unit nights to someone already doing COMET night on same day
            if current_assignment != ShiftType.COMET_NIGHT.value:
                unit_nights = running_totals[p_idx]['unit_nights']
                wte_adjusted = unit_nights / person.wte if person.wte > 0 else unit_nights
                available_registrars.append((p_idx, person, wte_adjusted))
        
        if available_registrars:
            # Select registrar with lowest WTE-adjusted count
            available_registrars.sort(key=lambda x: x[2])
            p_idx, selected_person, _ = available_registrars[0]
            
            # Assign the night
            self.partial_roster[day.isoformat()][selected_person.id] = ShiftType.NIGHT_REG.value
            running_totals[p_idx]['unit_nights'] += 1
            running_totals[p_idx]['total_nights'] += 1 
            running_totals[p_idx]['total_hours'] += 12

    def _solve_weekend_holiday_stage(self, timeout_seconds: int) -> SequentialSolveResult:
        """Stage 3: Holiday assignment - COMET days (COMET eligible only) and Unit long days on bank holidays."""
        
        print("🏦 Holiday Assignment Stage")
        print(f"Bank holidays in period: {[d.isoformat() for d in self.config.bank_holidays]}")
        
        # First count existing holiday work (nights already assigned on bank holidays)
        existing_holiday_work = self._count_existing_holiday_work()
        print(f"Existing holiday night coverage: {existing_holiday_work}")
        
        # Phase 1: Assign COMET days on bank holidays (COMET eligible only)
        comet_assignments = self._assign_comet_holiday_days(timeout_seconds // 2)
        
        # Phase 2: Assign Unit long days on remaining bank holiday slots  
        long_day_assignments = self._assign_unit_holiday_long_days(timeout_seconds // 2)
        
        # Calculate total holiday work for fairness analysis
        total_holiday_work = self._calculate_total_holiday_work()
        
        # Report holiday work distribution
        print("📊 Holiday Work Distribution:")
        for person_id, count in total_holiday_work.items():
            print(f"  {person_id}: {count} bank holidays worked")
        
        # Check for reasonable distribution (warn if spread > 3)
        work_counts = list(total_holiday_work.values())
        if work_counts:
            min_work = min(work_counts)
            max_work = max(work_counts)
            if max_work - min_work > 3:
                print(f"⚠️  Holiday work spread is {max_work - min_work} (some work {max_work}, others {min_work})")
        
        return SequentialSolveResult(
            stage="weekend_holidays", 
            success=True,
            message=f"Holiday assignment completed. Assigned {len(comet_assignments)} COMET days and {len(long_day_assignments)} Unit long days on bank holidays. Total holiday work spread: {min_work if work_counts else 0}-{max_work if work_counts else 0}.",
            partial_roster=copy.deepcopy(self.partial_roster),
            assigned_shifts=comet_assignments.union(long_day_assignments),
            next_stage="comet_days"
        )
    
    def _count_existing_holiday_work(self) -> Dict[str, int]:
        """Count holiday work already assigned (nights on bank holidays)."""
        holiday_work = {person.id: 0 for person in self.people}
        
        for day in self.days:
            if day in self.config.bank_holidays:
                day_str = day.isoformat()
                if day_str in self.partial_roster:
                    for person_id, shift in self.partial_roster[day_str].items():
                        # Count night shifts as holiday work
                        if shift in [ShiftType.COMET_NIGHT.value, ShiftType.NIGHT_REG.value, ShiftType.NIGHT_SHO.value]:
                            holiday_work[person_id] += 1
        
        return holiday_work
    
    def _assign_comet_holiday_days(self, timeout_seconds: int) -> set:
        """Assign COMET day shifts on bank holidays (COMET eligible only)."""
        
        model = cp_model.CpModel()
        assignments = set()
        
        # Identify bank holidays that need COMET day coverage
        bank_holiday_indices = []
        for d_idx, day in enumerate(self.days):
            if day in self.config.bank_holidays:
                bank_holiday_indices.append(d_idx)
        
        if not bank_holiday_indices:
            print("No bank holidays found in period")
            return assignments
        
        # Create decision variables for COMET days
        x = {}
        comet_eligible_people = [(p_idx, person) for p_idx, person in enumerate(self.people) 
                               if person.comet_eligible]
        
        for p_idx, person in comet_eligible_people:
            for d_idx in bank_holiday_indices:
                day = self.days[d_idx]
                day_str = day.isoformat()
                current_shift = self.partial_roster[day_str][person.id]
                
                # Can only assign COMET day if currently OFF
                if current_shift == ShiftType.OFF.value:
                    x[p_idx, d_idx] = model.NewBoolVar(f"comet_day_{p_idx}_{d_idx}")
        
        # Ensure exactly 1 COMET day registrar per bank holiday (if possible)
        for d_idx in bank_holiday_indices:
            available_people = [p_idx for p_idx, _ in comet_eligible_people 
                              if (p_idx, d_idx) in x]
            if available_people:
                model.Add(sum(x[p_idx, d_idx] for p_idx in available_people) == 1)
        
        # Add fairness constraint - try to distribute COMET holiday days
        if len(comet_eligible_people) > 1 and len(bank_holiday_indices) > 1:
            comet_counts = []
            for p_idx, _ in comet_eligible_people:
                count_var = model.NewIntVar(0, len(bank_holiday_indices), f"comet_holiday_count_{p_idx}")
                model.Add(count_var == sum(x.get((p_idx, d_idx), 0) for d_idx in bank_holiday_indices))
                comet_counts.append(count_var)
            
            # Minimize difference between max and min assignments
            max_var = model.NewIntVar(0, len(bank_holiday_indices), "max_comet_holidays")
            min_var = model.NewIntVar(0, len(bank_holiday_indices), "min_comet_holidays")
            model.AddMaxEquality(max_var, comet_counts)
            model.AddMinEquality(min_var, comet_counts)
            
            fairness_var = model.NewIntVar(0, len(bank_holiday_indices), "comet_fairness")
            model.Add(fairness_var == max_var - min_var)
            model.Minimize(fairness_var)
        
        # Solve
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = timeout_seconds
        status = solver.Solve(model)
        
        if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
            for p_idx, person in comet_eligible_people:
                for d_idx in bank_holiday_indices:
                    if (p_idx, d_idx) in x and solver.Value(x[p_idx, d_idx]) == 1:
                        day = self.days[d_idx]
                        day_str = day.isoformat()
                        self.partial_roster[day_str][person.id] = ShiftType.COMET_DAY.value
                        assignments.add((p_idx, d_idx, ShiftType.COMET_DAY))
                        self.assigned_shifts.add((p_idx, d_idx, ShiftType.COMET_DAY))
                        print(f"  Assigned COMET day on {day_str} to {person.name}")
        
        return assignments
    
    def _assign_unit_holiday_long_days(self, timeout_seconds: int) -> set:
        """Assign Unit long day shifts on bank holidays without COMET day coverage."""
        
        model = cp_model.CpModel()
        assignments = set()
        
        # Find bank holidays that still need Unit long day coverage
        need_long_day_coverage = []
        for d_idx, day in enumerate(self.days):
            if day in self.config.bank_holidays:
                day_str = day.isoformat()
                # Check if day already has COMET day coverage
                has_comet_day = any(shift == ShiftType.COMET_DAY.value 
                                  for shift in self.partial_roster[day_str].values())
                if not has_comet_day:
                    need_long_day_coverage.append(d_idx)
        
        if not need_long_day_coverage:
            print("All bank holidays have COMET day coverage")
            return assignments
        
        # Create decision variables for Unit long days
        x = {}
        registrars = [(p_idx, person) for p_idx, person in enumerate(self.people) 
                     if person.grade == "Registrar"]
        
        for p_idx, person in registrars:
            for d_idx in need_long_day_coverage:
                day = self.days[d_idx]
                day_str = day.isoformat()
                current_shift = self.partial_roster[day_str][person.id]
                
                # Can only assign long day if currently OFF
                if current_shift == ShiftType.OFF.value:
                    x[p_idx, d_idx] = model.NewBoolVar(f"long_day_{p_idx}_{d_idx}")
        
        # Ensure exactly 1 long day registrar per uncovered bank holiday
        for d_idx in need_long_day_coverage:
            available_people = [p_idx for p_idx, _ in registrars 
                              if (p_idx, d_idx) in x]
            if available_people:
                model.Add(sum(x[p_idx, d_idx] for p_idx in available_people) == 1)
        
        # Add fairness constraint for long day distribution
        if len(registrars) > 1 and len(need_long_day_coverage) > 1:
            long_day_counts = []
            for p_idx, _ in registrars:
                count_var = model.NewIntVar(0, len(need_long_day_coverage), f"long_day_holiday_count_{p_idx}")
                model.Add(count_var == sum(x.get((p_idx, d_idx), 0) for d_idx in need_long_day_coverage))
                long_day_counts.append(count_var)
            
            # Minimize difference between max and min assignments
            max_var = model.NewIntVar(0, len(need_long_day_coverage), "max_long_day_holidays")
            min_var = model.NewIntVar(0, len(need_long_day_coverage), "min_long_day_holidays")
            model.AddMaxEquality(max_var, long_day_counts)
            model.AddMinEquality(min_var, long_day_counts)
            
            fairness_var = model.NewIntVar(0, len(need_long_day_coverage), "long_day_fairness")
            model.Add(fairness_var == max_var - min_var)
            model.Minimize(fairness_var)
        
        # Solve
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = timeout_seconds
        status = solver.Solve(model)
        
        if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
            for p_idx, person in registrars:
                for d_idx in need_long_day_coverage:
                    if (p_idx, d_idx) in x and solver.Value(x[p_idx, d_idx]) == 1:
                        day = self.days[d_idx]
                        day_str = day.isoformat()
                        self.partial_roster[day_str][person.id] = ShiftType.LONG_DAY_REG.value
                        assignments.add((p_idx, d_idx, ShiftType.LONG_DAY_REG))
                        self.assigned_shifts.add((p_idx, d_idx, ShiftType.LONG_DAY_REG))
                        print(f"  Assigned Unit long day on {day_str} to {person.name}")
        
        return assignments
    
    def _calculate_total_holiday_work(self) -> Dict[str, int]:
        """Calculate total holiday work for each person (nights + days on bank holidays)."""
        holiday_work = {person.id: 0 for person in self.people}
        
        for day in self.days:
            if day in self.config.bank_holidays:
                day_str = day.isoformat()
                if day_str in self.partial_roster:
                    for person_id, shift in self.partial_roster[day_str].items():
                        # Count any non-OFF shift on a bank holiday as holiday work
                        if shift != ShiftType.OFF.value:
                            holiday_work[person_id] += 1
        
        return holiday_work
    
    def _solve_weekday_long_days_stage(self, timeout_seconds: int) -> SequentialSolveResult:
        """Stage 4: Assign weekday long days - exactly 1 LD_REG per weekday (Priority 4)."""
        
        model = cp_model.CpModel()
        
        # Create decision variables for long day shifts on weekdays
        long_day_shifts = [ShiftType.LONG_DAY_REG]  # Ignoring SHO for now
        allowed_shifts = long_day_shifts + [ShiftType.OFF]
        
        # Identify weekdays (Monday-Friday, not weekends or holidays)
        weekday_days = []
        for d_idx, day in enumerate(self.days):
            is_weekday = day.weekday() < 5  # Monday-Friday
            is_weekend = day.weekday() in [5, 6]
            is_holiday = day in self.config.bank_holidays
            if is_weekday and not is_weekend and not is_holiday:
                weekday_days.append(d_idx)
        
        x = {}
        for p_idx, person in enumerate(self.people):
            for d_idx in weekday_days:
                day = self.days[d_idx]
                # Skip days where person already has a non-OFF assignment
                current_assignment = self.partial_roster[day.isoformat()][person.id]
                if current_assignment != ShiftType.OFF.value:
                    continue
                    
                for shift in allowed_shifts:
                    x[p_idx, d_idx, shift] = model.NewBoolVar(f"x_{p_idx}_{d_idx}_{shift.value}")
        
        # Each person can only have one shift per day (for unassigned weekdays)
        for p_idx, person in enumerate(self.people):
            for d_idx in weekday_days:
                day = self.days[d_idx]
                current_assignment = self.partial_roster[day.isoformat()][person.id]
                if current_assignment == ShiftType.OFF.value:
                    model.Add(sum(x.get((p_idx, d_idx, s), 0) for s in allowed_shifts) == 1)
        
        # Weekday long day coverage - exactly 1 LD_REG per weekday
        for d_idx in weekday_days:
            ld_reg_vars = [x.get((p_idx, d_idx, ShiftType.LONG_DAY_REG), 0) 
                          for p_idx in range(len(self.people))
                          if (p_idx, d_idx, ShiftType.LONG_DAY_REG) in x]
            
            if ld_reg_vars:
                model.Add(sum(ld_reg_vars) == 1)
        
        # Add global rest constraints to prevent violating rest periods
        self._add_global_rest_constraints(model, x)
        
        # Add fairness constraints for equitable distribution (within stage only for now)  
        self._add_global_fairness_constraints(model, x, long_day_shifts, "weekday_long_days")
        
        # Grade-specific constraints
        for p_idx, person in enumerate(self.people):
            for d_idx in weekday_days:
                if person.grade not in ["Registrar"] and (p_idx, d_idx, ShiftType.LONG_DAY_REG) in x:
                    model.Add(x[p_idx, d_idx, ShiftType.LONG_DAY_REG] == 0)
        
        # Solve
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = timeout_seconds
        
        status = solver.Solve(model)
        
        if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
            # Extract weekday long day assignments
            new_assignments = set()
            for p_idx, person in enumerate(self.people):
                for d_idx in weekday_days:
                    day = self.days[d_idx]
                    for shift in long_day_shifts:
                        if (p_idx, d_idx, shift) in x and solver.Value(x[p_idx, d_idx, shift]) == 1:
                            # Update partial roster
                            self.partial_roster[day.isoformat()][person.id] = shift.value
                            new_assignments.add((p_idx, d_idx, shift))
                            self.assigned_shifts.add((p_idx, d_idx, shift))
            
            return SequentialSolveResult(
                stage="weekday_long_days",
                success=True,
                message=f"Weekday long days stage completed. Assigned {len(new_assignments)} weekday LD_REG shifts.",
                partial_roster=copy.deepcopy(self.partial_roster),
                assigned_shifts=new_assignments,
                next_stage="short_days"
            )
        else:
            return SequentialSolveResult(
                stage="weekday_long_days",
                success=False,
                message=f"Weekday long days stage failed: {solver.StatusName(status)}",
                partial_roster=copy.deepcopy(self.partial_roster),
                next_stage="short_days"
            )
    
    def _solve_short_days_stage(self, timeout_seconds: int) -> SequentialSolveResult:
        """Stage 5: Assign short days for weekday coverage - 1-3 SD per weekday (Priority 5)."""
        
        model = cp_model.CpModel()
        
        # Create decision variables for short days and remaining shifts
        short_day_shifts = [ShiftType.SHORT_DAY, ShiftType.CPD, ShiftType.REG_TRAINING, ShiftType.SHO_TRAINING]
        allowed_shifts = short_day_shifts + [ShiftType.OFF]
        
        x = {}
        for p_idx, person in enumerate(self.people):
            for d_idx, day in enumerate(self.days):
                # Skip days where person already has a non-OFF assignment
                current_assignment = self.partial_roster[day.isoformat()][person.id]
                if current_assignment != ShiftType.OFF.value:
                    continue
                    
                for shift in allowed_shifts:
                    x[p_idx, d_idx, shift] = model.NewBoolVar(f"x_{p_idx}_{d_idx}_{shift.value}")
        
        # Each person can only have one shift per day (for unassigned days)
        for p_idx, person in enumerate(self.people):
            for d_idx, day in enumerate(self.days):
                current_assignment = self.partial_roster[day.isoformat()][person.id]
                if current_assignment == ShiftType.OFF.value:
                    model.Add(sum(x.get((p_idx, d_idx, s), 0) for s in allowed_shifts) == 1)
        
        # Weekday short day coverage requirements (1-3 SD per weekday)
        self._add_weekday_short_day_coverage_constraints(model, x, short_day_shifts)
        
        # Add global rest constraints to prevent violating rest periods
        self._add_global_rest_constraints(model, x)
        
        # Add fairness constraints for equitable distribution of short days
        self._add_global_fairness_constraints(model, x, [ShiftType.SHORT_DAY], "short_days")
        
        # Grade-specific constraints
        for p_idx, person in enumerate(self.people):
            for d_idx, day in enumerate(self.days):
                if person.grade not in ["Registrar"]:
                    for reg_shift in [ShiftType.LONG_DAY_REG, ShiftType.REG_TRAINING]:
                        if (p_idx, d_idx, reg_shift) in x:
                            model.Add(x[p_idx, d_idx, reg_shift] == 0)
                if person.grade not in ["SHO"]:
                    for sho_shift in [ShiftType.LONG_DAY_SHO, ShiftType.SHO_TRAINING]:
                        if (p_idx, d_idx, sho_shift) in x:
                            model.Add(x[p_idx, d_idx, sho_shift] == 0)
        
        # Solve
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = timeout_seconds
        
        status = solver.Solve(model)
        
        if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
            # Extract final assignments
            new_assignments = set()
            for p_idx, person in enumerate(self.people):
                for d_idx, day in enumerate(self.days):
                    current_assignment = self.partial_roster[day.isoformat()][person.id]
                    if current_assignment == ShiftType.OFF.value:
                        for shift in short_day_shifts:
                            if (p_idx, d_idx, shift) in x and solver.Value(x[p_idx, d_idx, shift]) == 1:
                                # Update partial roster
                                self.partial_roster[day.isoformat()][person.id] = shift.value
                                new_assignments.add((p_idx, d_idx, shift))
                                self.assigned_shifts.add((p_idx, d_idx, shift))
            
            return SequentialSolveResult(
                stage="short_days",
                success=True,
                message=f"Final stage completed. Assigned {len(new_assignments)} remaining shifts. Roster complete!",
                partial_roster=copy.deepcopy(self.partial_roster),
                assigned_shifts=new_assignments,
                next_stage=None
            )
        else:
            return SequentialSolveResult(
                stage="short_days",
                success=False,
                message=f"Final stage failed: {solver.StatusName(status)}",
                partial_roster=copy.deepcopy(self.partial_roster),
                next_stage=None
            )
    
    def _add_comet_constraints(self, model, x, comet_shifts):
        """Add COMET-specific constraints."""
        # First, identify COMET weeks properly
        comet_week_ranges = []
        for comet_start in self.config.comet_on_weeks:
            if isinstance(comet_start, str):
                comet_start = date.fromisoformat(comet_start)
            
            # Find the Monday of this COMET week
            days_since_monday = comet_start.weekday()
            week_monday = comet_start - timedelta(days=days_since_monday)
            week_sunday = week_monday + timedelta(days=6)
            comet_week_ranges.append((week_monday, week_sunday))
        
        # COMET weeks constraint - only assign COMET during specified weeks
        for d_idx, day in enumerate(self.days):
            is_comet_week = any(
                week_start <= day <= week_end 
                for week_start, week_end in comet_week_ranges
            )
            if not is_comet_week:
                for p_idx in range(len(self.people)):
                    for comet_shift in comet_shifts:
                        if (p_idx, d_idx, comet_shift) in x:
                            model.Add(x[p_idx, d_idx, comet_shift] == 0)
        
        # COMET coverage - EXACTLY one CMD and one CMN PER DAY during COMET weeks
        for d_idx, day in enumerate(self.days):
            is_comet_week = any(
                week_start <= day <= week_end 
                for week_start, week_end in comet_week_ranges
            )
            if is_comet_week:
                # Exactly 1 COMET Day (CMD) per day during COMET weeks
                cmd_vars = []
                for p_idx in range(len(self.people)):
                    if (p_idx, d_idx, ShiftType.COMET_DAY) in x:
                        cmd_vars.append(x[p_idx, d_idx, ShiftType.COMET_DAY])
                
                if cmd_vars:
                    model.Add(sum(cmd_vars) == 1)  # Exactly 1 CMD per day
                
                # Exactly 1 COMET Night (CMN) per day during COMET weeks
                cmn_vars = []
                for p_idx in range(len(self.people)):
                    if (p_idx, d_idx, ShiftType.COMET_NIGHT) in x:
                        cmn_vars.append(x[p_idx, d_idx, ShiftType.COMET_NIGHT])
                
                if cmn_vars:
                    model.Add(sum(cmn_vars) == 1)  # Exactly 1 CMN per day
        
        # Add COMET shift block patterns
        self._add_comet_block_patterns(model, x, comet_week_ranges)
        
        # Add COMET fairness objective (bias toward underworked doctors with cumulative tracking)
        self._add_comet_fairness_objective(model, x, comet_shifts, comet_week_ranges)
    
    def _add_comet_block_patterns(self, model, x, comet_week_ranges):
        """Add constraints for COMET shift block patterns."""
        # COMET Day blocks: aim for 1-2 consecutive days
        for p_idx, person in enumerate(self.people):
            if not person.comet_eligible:
                continue
                
            for week_start, week_end in comet_week_ranges:
                week_day_indices = []
                for d_idx, day in enumerate(self.days):
                    if week_start <= day <= week_end:
                        week_day_indices.append(d_idx)
                
                # For COMET Days: encourage blocks of 1-2 days
                for i in range(len(week_day_indices) - 2):
                    d_idx1, d_idx2, d_idx3 = week_day_indices[i:i+3]
                    
                    # If working CMD on 3+ consecutive days, discourage it
                    if all((p_idx, d_idx, ShiftType.COMET_DAY) in x for d_idx in [d_idx1, d_idx2, d_idx3]):
                        cmd_vars = [x[p_idx, d_idx, ShiftType.COMET_DAY] for d_idx in [d_idx1, d_idx2, d_idx3]]
                        # Soft constraint: avoid 3+ consecutive CMD
                        model.Add(sum(cmd_vars) <= 2)
        
        # COMET Night blocks: aim for 2-4 consecutive nights  
        for p_idx, person in enumerate(self.people):
            if not person.comet_eligible:
                continue
                
            for week_start, week_end in comet_week_ranges:
                week_day_indices = []
                for d_idx, day in enumerate(self.days):
                    if week_start <= day <= week_end:
                        week_day_indices.append(d_idx)
                
                # Discourage single isolated COMET nights
                for i in range(len(week_day_indices)):
                    d_idx = week_day_indices[i]
                    if (p_idx, d_idx, ShiftType.COMET_NIGHT) not in x:
                        continue
                    
                    # Check for adjacent nights
                    adjacent_nights = []
                    if i > 0:
                        prev_d_idx = week_day_indices[i-1]
                        if (p_idx, prev_d_idx, ShiftType.COMET_NIGHT) in x:
                            adjacent_nights.append(x[p_idx, prev_d_idx, ShiftType.COMET_NIGHT])
                    
                    if i < len(week_day_indices) - 1:
                        next_d_idx = week_day_indices[i+1]
                        if (p_idx, next_d_idx, ShiftType.COMET_NIGHT) in x:
                            adjacent_nights.append(x[p_idx, next_d_idx, ShiftType.COMET_NIGHT])
                    
                    # If working this night, encourage having at least one adjacent night
                    if adjacent_nights:
                        # Soft preference: if working night, try to have adjacent nights
                        current_night = x[p_idx, d_idx, ShiftType.COMET_NIGHT]
                        # If working this night, require at least one adjacent night
                        model.Add(sum(adjacent_nights) >= current_night)
                
                # Limit COMET night blocks to max 4 consecutive
                for i in range(len(week_day_indices) - 4):
                    consecutive_nights = []
                    for j in range(5):  # 5 consecutive days
                        d_idx = week_day_indices[i + j]
                        if (p_idx, d_idx, ShiftType.COMET_NIGHT) in x:
                            consecutive_nights.append(x[p_idx, d_idx, ShiftType.COMET_NIGHT])
                    
                    if len(consecutive_nights) >= 5:
                        model.Add(sum(consecutive_nights) <= 4)
    
    def _add_comet_fairness_objective(self, model, x, comet_shifts, comet_week_ranges):
        """Add objective function to bias COMET shift assignment toward underworked doctors based on cumulative 26-week tracking."""
        
        # Get all COMET-eligible people and their WTE values
        comet_eligible_people = [(i, p) for i, p in enumerate(self.people) if p.comet_eligible]
        
        if not comet_eligible_people:
            return
        
        # Calculate total WTE for proportional fairness
        total_wte = sum(person.wte for _, person in comet_eligible_people)
        
        # Count total COMET shifts in this period
        total_comet_days = 0
        for week_start, week_end in comet_week_ranges:
            total_comet_days += (week_end - week_start).days + 1
        
        # Calculate expected cumulative shifts per person over 26 weeks (for full rota)
        # For now, use proportional share of current period as proxy
        objective_terms = []
        
        for p_idx, person in comet_eligible_people:
            # Get historical counts for this person
            historical = self.historical_comet_counts.get(person.id, {"cmd": 0, "cmn": 0})
            current_cmd_count = historical["cmd"] 
            current_cmn_count = historical["cmn"]
            
            # Calculate expected share based on WTE
            wte_ratio = person.wte / total_wte
            expected_cmd_share = wte_ratio * total_comet_days
            expected_cmn_share = wte_ratio * total_comet_days
            
            # Count shifts being assigned to this person in current period
            cmd_vars = []
            cmn_vars = []
            
            for d_idx, day in enumerate(self.days):
                is_comet_day = any(week_start <= day <= week_end for week_start, week_end in comet_week_ranges)
                if is_comet_day:
                    if (p_idx, d_idx, ShiftType.COMET_DAY) in x:
                        cmd_vars.append(x[p_idx, d_idx, ShiftType.COMET_DAY])
                    if (p_idx, d_idx, ShiftType.COMET_NIGHT) in x:
                        cmn_vars.append(x[p_idx, d_idx, ShiftType.COMET_NIGHT])
            
            # Calculate "deficit" - how underworked is this person?
            # Use a scaled approach that works for small periods
            if cmd_vars:
                # Scale deficits by 10 to handle fractional expectations
                # This gives meaningful differences even with small expected values
                scaled_expected_cmd = expected_cmd_share * 10
                scaled_historical_cmd = current_cmd_count * 10
                cmd_deficit = max(0, int(scaled_expected_cmd - scaled_historical_cmd))
                
                # Higher deficit = more priority for getting shifts
                for cmd_var in cmd_vars:
                    objective_terms.append(-cmd_deficit * cmd_var)
            
            if cmn_vars:
                scaled_expected_cmn = expected_cmn_share * 10
                scaled_historical_cmn = current_cmn_count * 10  
                cmn_deficit = max(0, int(scaled_expected_cmn - scaled_historical_cmn))
                
                for cmn_var in cmn_vars:
                    objective_terms.append(-cmn_deficit * cmn_var)
        
        # Add basic anti-domination constraints to prevent one person taking everything
        for p_idx, person in comet_eligible_people:
            cmd_vars = []
            cmn_vars = []
            
            for d_idx, day in enumerate(self.days):
                is_comet_day = any(week_start <= day <= week_end for week_start, week_end in comet_week_ranges)
                if is_comet_day:
                    if (p_idx, d_idx, ShiftType.COMET_DAY) in x:
                        cmd_vars.append(x[p_idx, d_idx, ShiftType.COMET_DAY])
                    if (p_idx, d_idx, ShiftType.COMET_NIGHT) in x:
                        cmn_vars.append(x[p_idx, d_idx, ShiftType.COMET_NIGHT])
            
            # Prevent extreme domination (more than 60% of shifts)
            if cmd_vars and total_comet_days > 1:
                max_domination = max(1, (total_comet_days * 6) // 10)  # Max 60%
                model.Add(sum(cmd_vars) <= max_domination)
                
            if cmn_vars and total_comet_days > 1:
                max_domination = max(1, (total_comet_days * 6) // 10)  # Max 60%
                model.Add(sum(cmn_vars) <= max_domination)
        
        # Multi-objective approach: Fairness + Participation
        participation_terms = []
        
        # Add participation bonus variables - encourage using more doctors
        for p_idx, person in comet_eligible_people:
            # Create a boolean variable: "does this person work any COMET shifts this period?"
            person_participation = model.NewBoolVar(f"participation_{person.id}")
            
            # Collect all COMET shifts for this person
            person_comet_vars = []
            for d_idx, day in enumerate(self.days):
                is_comet_day = any(week_start <= day <= week_end for week_start, week_end in comet_week_ranges)
                if is_comet_day:
                    if (p_idx, d_idx, ShiftType.COMET_DAY) in x:
                        person_comet_vars.append(x[p_idx, d_idx, ShiftType.COMET_DAY])
                    if (p_idx, d_idx, ShiftType.COMET_NIGHT) in x:
                        person_comet_vars.append(x[p_idx, d_idx, ShiftType.COMET_NIGHT])
            
            if person_comet_vars:
                # participation = 1 if person works any COMET shift, 0 otherwise
                model.Add(person_participation <= sum(person_comet_vars))
                model.Add(sum(person_comet_vars) <= person_participation * len(person_comet_vars))
                
                # Weight participation bonus based on deficit
                historical = self.historical_comet_counts.get(person.id, {"cmd": 0, "cmn": 0})
                total_historical = historical["cmd"] + historical["cmn"]
                wte_ratio = person.wte / total_wte
                expected_total = wte_ratio * total_comet_days * 2  # CMD + CMN expected
                
                # Higher deficit = bigger participation bonus
                participation_weight = max(1, int((expected_total * 10) - (total_historical * 10)))
                participation_terms.append(participation_weight * person_participation)
        
        # Combined objective: Primary (fairness) + Secondary (participation)
        all_objective_terms = []
        
        # Primary objective: Deficit-based fairness (high weight)
        all_objective_terms.extend(objective_terms)
        
        # Secondary objective: Participation bonuses (encourage inclusion of underworked doctors)
        if participation_terms:
            # Negative because we want to MAXIMIZE participation
            all_objective_terms.extend([-100 * term for term in participation_terms])
        
        # Set the multi-objective function
        if all_objective_terms:
            model.Minimize(sum(all_objective_terms))
        
        # Add constraint: No CMD immediately before CMN (consecutive days, any boundary)
        for p_idx, person in comet_eligible_people:
            for d_idx in range(len(self.days) - 1):
                # If person does CMD today and CMN tomorrow, forbid it
                if ((p_idx, d_idx, ShiftType.COMET_DAY) in x and 
                    (p_idx, d_idx + 1, ShiftType.COMET_NIGHT) in x):
                    model.Add(x[p_idx, d_idx, ShiftType.COMET_DAY] + 
                             x[p_idx, d_idx + 1, ShiftType.COMET_NIGHT] <= 1)

    def _add_comet_preparation_constraints(self, model, x):
        """Add constraints to prepare for COMET nights with preceding day shifts when possible."""
        for p_idx, person in enumerate(self.people):
            for d_idx in range(len(self.days) - 1):
                # If person does COMET night, try to have them do a day shift the day before
                if (p_idx, d_idx + 1, ShiftType.COMET_NIGHT) in x:
                    # Check if they can do a day shift the day before
                    day_shift_vars = []
                    for day_shift in [ShiftType.COMET_DAY, ShiftType.LONG_DAY_REG, ShiftType.LONG_DAY_SHO, ShiftType.SHORT_DAY]:
                        if (p_idx, d_idx, day_shift) in x:
                            day_shift_vars.append(x[p_idx, d_idx, day_shift])
                    
                    # Soft constraint: if doing COMET night, prefer to have a day shift before
                    if day_shift_vars:
                        # This is a soft preference - we'll use it as an objective bonus later
                        pass  # Could add to objective function if needed
    
    def _add_basic_weekday_coverage(self, model, x, basic_day_shifts):
        """Add constraints to ensure basic weekday coverage during COMET stage."""
        for d_idx, day in enumerate(self.days):
            if day.weekday() < 5:  # Monday-Friday
                # Need at least minimum weekday coverage
                day_shift_vars = []
                for shift in basic_day_shifts:
                    for p_idx in range(len(self.people)):
                        if (p_idx, d_idx, shift) in x:
                            day_shift_vars.append(x[p_idx, d_idx, shift])
                
                # Also count COMET_DAY as day coverage
                for p_idx in range(len(self.people)):
                    if (p_idx, d_idx, ShiftType.COMET_DAY) in x:
                        day_shift_vars.append(x[p_idx, d_idx, ShiftType.COMET_DAY])
                
                if day_shift_vars:
                    # Ensure minimum coverage (at least 2 people for basic weekday coverage)
                    min_coverage = min(2, len(self.people))
                    model.Add(sum(day_shift_vars) >= min_coverage)
    
    def _add_night_coverage_constraints(self, model, x, night_shifts):
        """Add night coverage constraints - exactly 1 N_REG + 1 N_SHO every day."""
        for d_idx, day in enumerate(self.days):
            # EXACTLY one night registrar every day
            night_reg_vars = [x.get((p_idx, d_idx, ShiftType.NIGHT_REG), 0) 
                            for p_idx in range(len(self.people)) 
                            if (p_idx, d_idx, ShiftType.NIGHT_REG) in x]
            
            if night_reg_vars:
                model.Add(sum(night_reg_vars) == 1)
            
            # For now, ignoring SHO nights as requested
            # night_sho_vars = [x.get((p_idx, d_idx, ShiftType.NIGHT_SHO), 0) 
            #                 for p_idx in range(len(self.people))
            #                 if (p_idx, d_idx, ShiftType.NIGHT_SHO) in x]
            # 
            # if night_sho_vars:
            #     model.Add(sum(night_sho_vars) == 1)
    
    def _add_night_block_constraints(self, model, x, night_shifts):
        """Add constraints to ensure night shifts occur in blocks of 2-4 consecutive nights."""
        for p_idx, person in enumerate(self.people):
            for d_idx in range(len(self.days)):
                for night_shift in night_shifts:
                    if (p_idx, d_idx, night_shift) not in x:
                        continue
                        
                    night_var = x[p_idx, d_idx, night_shift]
                    
                    # If working a night shift, check for block patterns
                    # If it's a single night (isolated), discourage it
                    is_single_night = model.NewBoolVar(f"single_night_{p_idx}_{d_idx}_{night_shift.value}")
                    
                    # Check if this night is isolated (no nights before or after)
                    prev_night_vars = []
                    next_night_vars = []
                    
                    # Previous day
                    if d_idx > 0:
                        for prev_shift in night_shifts:
                            if (p_idx, d_idx - 1, prev_shift) in x:
                                prev_night_vars.append(x[p_idx, d_idx - 1, prev_shift])
                    
                    # Next day
                    if d_idx < len(self.days) - 1:
                        for next_shift in night_shifts:
                            if (p_idx, d_idx + 1, next_shift) in x:
                                next_night_vars.append(x[p_idx, d_idx + 1, next_shift])
                    
                    # Single night is when working this night but no adjacent nights
                    if prev_night_vars or next_night_vars:
                        # is_single_night = night_var AND NOT(any prev nights) AND NOT(any next nights)
                        has_adjacent = model.NewBoolVar(f"has_adjacent_{p_idx}_{d_idx}")
                        adjacent_vars = prev_night_vars + next_night_vars
                        if adjacent_vars:
                            # has_adjacent is 1 if any adjacent night is worked
                            model.Add(has_adjacent * len(adjacent_vars) >= sum(adjacent_vars))
                            model.Add(is_single_night <= night_var)
                            model.Add(is_single_night <= 1 - has_adjacent)
                            model.Add(is_single_night >= night_var + (1 - has_adjacent) - 1)
                            
                            # Discourage single nights (soft constraint via objective would be better)
                            # For now, we'll allow them but the natural flow should create blocks
    
    def _add_global_rest_constraints(self, model, x):
        """Add constraints to prevent violating rest periods from previously assigned shifts."""
        # Define working shifts that need rest after nights
        all_night_shifts = [ShiftType.NIGHT_REG, ShiftType.NIGHT_SHO, ShiftType.COMET_NIGHT]
        working_shifts = [s for s in ShiftType if s not in [ShiftType.OFF, ShiftType.LTFT]]
        
        for p_idx, person in enumerate(self.people):
            for d_idx, day in enumerate(self.days):
                current_assignment = self.partial_roster[day.isoformat()][person.id]
                
                # If person worked a night shift on this day, prevent working shifts in next 2 days
                if current_assignment in [s.value for s in all_night_shifts]:
                    for rest_day in range(1, 3):  # 1 and 2 days after night
                        if d_idx + rest_day < len(self.days):
                            rest_day_idx = d_idx + rest_day
                            # Prevent any working shift in rest period
                            for work_shift in working_shifts:
                                work_var = x.get((p_idx, rest_day_idx, work_shift), None)
                                if work_var is not None:
                                    model.Add(work_var == 0)

    def _add_global_fairness_constraints(self, model, x, shift_types, stage_name):
        """Add fairness constraints to ensure equitable distribution of shifts based on WTE."""
        
        # Group people by grade for fair comparison
        registrars = [i for i, p in enumerate(self.people) if p.grade == "Registrar"]
        shos = [i for i, p in enumerate(self.people) if p.grade == "SHO"]
        
        for grade_group in [registrars, shos]:
            if len(grade_group) < 2:
                continue
                
            # Calculate total WTE for this grade
            total_wte = sum(self.people[p_idx].wte for p_idx in grade_group)
            
            for shift_type in shift_types:
                # Count total shifts of this type being assigned in this stage
                shift_vars = []
                for p_idx in grade_group:
                    for d_idx in range(len(self.days)):
                        if (p_idx, d_idx, shift_type) in x:
                            shift_vars.append((p_idx, x[p_idx, d_idx, shift_type]))
                
                if not shift_vars:
                    continue
                
                # Calculate expected distribution based on WTE
                total_shifts_var = model.NewIntVar(0, len(self.days) * len(grade_group), f"total_{shift_type.value}_{stage_name}")
                model.Add(total_shifts_var == sum(var for _, var in shift_vars))
                
                # For each person, constrain their share to be proportional to WTE ±10%
                for p_idx in grade_group:
                    person = self.people[p_idx]
                    
                    # Count this person's shifts of this type
                    person_shift_vars = [var for p, var in shift_vars if p == p_idx]
                    if person_shift_vars:
                        person_shifts = model.NewIntVar(0, len(self.days), f"person_{p_idx}_{shift_type.value}_{stage_name}")
                        model.Add(person_shifts == sum(person_shift_vars))
                        
                        # Expected share with ±20% tolerance using integer arithmetic (relaxed for feasibility)
                        # Convert WTE ratio to integer fraction to avoid floating point
                        wte_numerator = int(person.wte * 1000)  # Scale by 1000 for precision
                        total_wte_denominator = int(total_wte * 1000)
                        
                        # Lower bound: person_shifts * total_wte >= 0.8 * person_wte * total_shifts
                        # person_shifts * total_wte_denominator >= 800 * wte_numerator * total_shifts
                        model.Add(person_shifts * total_wte_denominator >= 800 * wte_numerator * total_shifts_var)
                        
                        # Upper bound: person_shifts * total_wte <= 1.2 * person_wte * total_shifts
                        # person_shifts * total_wte_denominator <= 1200 * wte_numerator * total_shifts
                        model.Add(person_shifts * total_wte_denominator <= 1200 * wte_numerator * total_shifts_var)

    def _add_cumulative_fairness_constraints(self, model, x, shift_types, stage_name):
        """Add constraints based on cumulative assignments across all stages so far."""
        
        # Count assignments made in previous stages
        cumulative_counts = {}
        for p_idx, person in enumerate(self.people):
            cumulative_counts[p_idx] = {}
            for shift_type in [ShiftType.NIGHT_REG, ShiftType.NIGHT_SHO, ShiftType.LONG_DAY_REG, 
                              ShiftType.LONG_DAY_SHO, ShiftType.COMET_DAY, ShiftType.COMET_NIGHT]:
                count = 0
                for day_str, assignments in self.partial_roster.items():
                    if assignments[person.id] == shift_type.value:
                        count += 1
                cumulative_counts[p_idx][shift_type] = count
        
        # Group by grade
        registrars = [i for i, p in enumerate(self.people) if p.grade == "Registrar"]
        shos = [i for i, p in enumerate(self.people) if p.grade == "SHO"]
        
        for grade_group in [registrars, shos]:
            if len(grade_group) < 2:
                continue
                
            # Calculate total WTE for this grade
            total_wte = sum(self.people[p_idx].wte for p_idx in grade_group)
            
            # For each shift type being assigned in this stage
            for shift_type in shift_types:
                # Only apply to shifts relevant to this grade
                if shift_type in [ShiftType.LONG_DAY_REG, ShiftType.NIGHT_REG, ShiftType.COMET_DAY, ShiftType.COMET_NIGHT]:
                    if grade_group != registrars:
                        continue
                elif shift_type in [ShiftType.LONG_DAY_SHO, ShiftType.NIGHT_SHO]:
                    if grade_group != shos:
                        continue
                
                # Calculate cumulative + current assignments for fairness
                for p_idx in grade_group:
                    person = self.people[p_idx]
                    
                    # Current assignments in this stage
                    current_vars = []
                    for d_idx in range(len(self.days)):
                        if (p_idx, d_idx, shift_type) in x:
                            current_vars.append(x[p_idx, d_idx, shift_type])
                    
                    if current_vars:
                        current_count = model.NewIntVar(0, len(self.days), f"current_{p_idx}_{shift_type.value}_{stage_name}")
                        model.Add(current_count == sum(current_vars))
                        
                        # Total assignments = cumulative + current
                        cumulative = cumulative_counts[p_idx].get(shift_type, 0)
                        total_assignments = model.NewIntVar(0, 100, f"total_{p_idx}_{shift_type.value}_{stage_name}")
                        model.Add(total_assignments == cumulative + current_count)
                        
                        # Calculate expected total based on roster so far
                        total_assigned_so_far = sum(cumulative_counts[p][shift_type] for p in grade_group)
                        total_being_assigned = sum(1 for p in grade_group for d_idx in range(len(self.days)) 
                                                 if (p, d_idx, shift_type) in x)
                        
                        expected_total = total_assigned_so_far + total_being_assigned
                        
                        # Use integer arithmetic for fairness constraints
                        if expected_total > 0:  # Only apply if there are shifts to distribute
                            wte_numerator = int(person.wte * 1000)
                            total_wte_denominator = int(total_wte * 1000)
                            
                            # Allow ±20% variance: 0.8 * (expected * wte_ratio) <= actual <= 1.2 * (expected * wte_ratio)
                            # total_assignments * total_wte >= 0.8 * expected_total * person_wte
                            model.Add(total_assignments * total_wte_denominator >= 800 * expected_total * wte_numerator)
                            # total_assignments * total_wte <= 1.2 * expected_total * person_wte  
                            model.Add(total_assignments * total_wte_denominator <= 1200 * expected_total * wte_numerator)

    def _add_night_rest_constraints(self, model, x, night_shifts):
        """Add 46-hour rest constraints after nights (enhanced to prevent night-to-day violations)."""
        # Define all working shifts that require rest after nights
        working_shifts = [s for s in ShiftType if s not in [ShiftType.OFF, ShiftType.LTFT]]
        
        for p_idx, person in enumerate(self.people):
            for d_idx in range(len(self.days) - 2):  # Need 2 days for 46h rest
                # If working a night, must be OFF for next 2 days
                for night_shift in night_shifts:
                    if (p_idx, d_idx, night_shift) in x:
                        night_var = x[p_idx, d_idx, night_shift]
                        
                        # Check next 2 days for rest - prevent ANY working shift
                        for rest_day in range(1, 3):
                            if d_idx + rest_day < len(self.days):
                                rest_day_idx = d_idx + rest_day
                                day = self.days[rest_day_idx]
                                current_assignment = self.partial_roster[day.isoformat()][person.id]
                                
                                # FIXED: Check if already assigned to a working shift - if so, conflict!
                                if current_assignment in [s.value for s in working_shifts]:
                                    # This person already has a working shift assigned - prevent this night shift
                                    model.Add(night_var == 0)
                                elif current_assignment == ShiftType.OFF.value:
                                    # If not already assigned, must be OFF when night shift is worked
                                    off_var = x.get((p_idx, rest_day_idx, ShiftType.OFF), None)
                                    if off_var is not None:
                                        model.Add(off_var >= night_var)
                                else:
                                    # For any working shift variables in rest period, prevent them
                                    for work_shift in working_shifts:
                                        work_var = x.get((p_idx, rest_day_idx, work_shift), None)
                                        if work_var is not None:
                                            # Can't work both night and the working shift 
                                            model.Add(night_var + work_var <= 1)
    
    def _add_weekend_coverage_constraints(self, model, x, long_day_shifts, weekend_holiday_days):
        """Add weekend/holiday coverage constraints - exactly 1 LD_REG per weekend day."""
        for d_idx in weekend_holiday_days:
            # EXACTLY one LD_REG per weekend/holiday day
            weekend_vars = []
            for shift in long_day_shifts:
                shift_vars = [x.get((p_idx, d_idx, shift), 0) 
                            for p_idx in range(len(self.people))
                            if (p_idx, d_idx, shift) in x]
                weekend_vars.extend(shift_vars)
            
            if weekend_vars:
                model.Add(sum(weekend_vars) == 1)  # Exactly 1 LD_REG per weekend day
    
    def _add_target_hours_constraints(self, model, x, remaining_shifts):
        """Add constraints to meet target working hours."""
        for p_idx, person in enumerate(self.people):
            # Calculate hours already assigned
            assigned_hours = 0
            for day_str, person_roster in self.partial_roster.items():
                if person.id in person_roster:
                    shift_str = person_roster[person.id]
                    if shift_str != ShiftType.OFF.value:
                        try:
                            shift_type = ShiftType(shift_str)
                            assigned_hours += shift_duration_hours(shift_type)
                        except ValueError:
                            pass
            
            # Calculate target hours for the period
            days_in_period = len(self.days)
            weeks_in_period = days_in_period / 7.0
            target_weekly_hours = 40 * person.wte  # Standard 40 hours per week
            target_total_hours = target_weekly_hours * weeks_in_period
            
            # Calculate remaining hours needed
            remaining_hours_needed = max(0, target_total_hours - assigned_hours)
            
            # Add constraint for remaining hours
            if remaining_hours_needed > 0:
                remaining_hour_vars = []
                for d_idx, day in enumerate(self.days):
                    current_assignment = self.partial_roster[day.isoformat()][person.id]
                    if current_assignment == ShiftType.OFF.value:
                        for shift in remaining_shifts:
                            if (p_idx, d_idx, shift) in x:
                                hours = shift_duration_hours(shift)
                                remaining_hour_vars.append(x[p_idx, d_idx, shift] * hours)
                
                if remaining_hour_vars:
                    # Soft constraint - try to get close to target
                    model.Add(sum(remaining_hour_vars) >= remaining_hours_needed * 0.8)
    
    def _add_weekday_short_day_coverage_constraints(self, model, x, short_day_shifts):
        """Add weekday short day coverage constraints - 1-3 SD per weekday."""
        for d_idx, day in enumerate(self.days):
            if day.weekday() < 5:  # Monday-Friday
                # Count how many people are already assigned non-OFF shifts
                current_assignment = self.partial_roster[day.isoformat()]
                already_assigned = sum(1 for shift in current_assignment.values() 
                                     if shift != ShiftType.OFF.value)
                
                # Target 2-3 total people per weekday (including already assigned)
                target_total = 3
                short_day_needed = max(0, min(3, target_total - already_assigned))
                
                if short_day_needed > 0:
                    weekday_vars = []
                    for shift in short_day_shifts:
                        shift_vars = [x.get((p_idx, d_idx, shift), 0) 
                                    for p_idx in range(len(self.people))
                                    if (p_idx, d_idx, shift) in x]
                        weekday_vars.extend(shift_vars)
                    
                    if weekday_vars:
                        # At least 1, at most 3 short day shifts per weekday
                        model.Add(sum(weekday_vars) >= 1)
                        model.Add(sum(weekday_vars) <= short_day_needed)
    
    def get_current_roster(self) -> Dict[str, Dict[str, str]]:
        """Get the current partial roster."""
        return copy.deepcopy(self.partial_roster)
    
    def get_roster_statistics(self) -> Dict:
        """Get statistics about the current roster state."""
        stats = {}
        shift_counts = {}
        total_assigned = 0
        
        # Count shifts by type
        for day_str, day_assignments in self.partial_roster.items():
            for person_id, shift_str in day_assignments.items():
                if shift_str != ShiftType.OFF.value:
                    if shift_str not in shift_counts:
                        shift_counts[shift_str] = 0
                    shift_counts[shift_str] += 1
                    total_assigned += 1
                    
        stats['shift_counts'] = shift_counts
        stats['total_assigned'] = total_assigned
        stats['days_covered'] = len(self.partial_roster)
        
        return stats
    
    def check_hard_constraints(self) -> Dict:
        """Check current roster for hard constraint violations and suggest alternatives."""
        from .constraint_violations import HardConstraintViolationDetector
        
        detector = HardConstraintViolationDetector(self.problem)
        violations = detector.detect_violations(self.partial_roster)
        alternatives = detector.suggest_alternatives(violations)
        
        return {
            'violations': [
                {
                    'type': v.violation_type.value,
                    'person_id': v.person_id,
                    'person_name': v.person_name,
                    'date_range': [v.date_range[0].isoformat(), v.date_range[1].isoformat()],
                    'description': v.description,
                    'severity': v.severity,
                    'current_value': v.current_value,
                    'limit_value': v.limit_value,
                    'affected_shifts': [
                        {'date': shift[0].isoformat(), 'shift_type': shift[1].value}
                        for shift in v.affected_shifts
                    ]
                }
                for v in violations
            ],
            'alternatives': [
                {
                    'solution_type': a.solution_type,
                    'description': a.description,
                    'target_person_id': a.target_person_id,
                    'target_shifts': [
                        {'date': shift[0].isoformat(), 'shift_type': shift[1].value}
                        for shift in a.target_shifts
                    ],
                    'estimated_cost': a.estimated_cost,
                    'feasibility_score': a.feasibility_score
                }
                for a in alternatives
            ],
            'violation_summary': {
                'total_violations': len(violations),
                'critical_violations': len([v for v in violations if v.severity == 'CRITICAL']),
                'high_violations': len([v for v in violations if v.severity == 'HIGH']),
                'medium_violations': len([v for v in violations if v.severity == 'MEDIUM'])
            }
        }
    
    def _try_build_optimal_week_pattern(self, available_days, week_start, week_end, comet_eligible, running_totals):
        """Try to build optimal patterns within a week (4+3, 3+4, 2+2+3, etc.)"""
        
        if len(available_days) < 4:
            return False
        
        # Convert to day indices for easier handling
        available_indices = [(day - self.start_date).days for day in available_days]
        available_indices.sort()
        
        # Try different optimal patterns
        patterns_to_try = [
            # Pattern: [block1_size, block2_size, ...]
            [4, 3],    # 4+3 pattern 
            [3, 4],    # 3+4 pattern
            [3, 2, 2], # 3+2+2 pattern
            [2, 3, 2], # 2+3+2 pattern  
            [2, 2, 3], # 2+2+3 pattern
        ]
        
        for pattern in patterns_to_try:
            # Check if we have enough days for this pattern
            if sum(pattern) > len(available_indices):
                continue
            
            # Try to assign this pattern
            success = self._try_assign_pattern_in_week(pattern, available_indices, week_start, week_end, comet_eligible, running_totals)
            if success:
                return True
        
        return False
    
    def _try_assign_pattern_in_week(self, pattern, available_indices, week_start, week_end, comet_eligible, running_totals):
        """Try to assign a specific pattern (e.g., [4,3]) within available days."""
        
        # Find consecutive groups that can fit the pattern
        consecutive_groups = self._find_consecutive_groups(available_indices)
        
        # Try to match pattern blocks to consecutive groups
        assignments = self._generate_pattern_assignments(pattern, consecutive_groups)
        
        for i, assignment in enumerate(assignments):
            if self._try_assign_pattern_assignment(assignment, available_indices, comet_eligible, running_totals):
                return True
        
        return False
    
    def _find_consecutive_groups(self, day_indices):
        """Find all consecutive groups of days."""
        if not day_indices:
            return []
        
        groups = []
        current_group = [day_indices[0]]
        
        for i in range(1, len(day_indices)):
            if day_indices[i] == day_indices[i-1] + 1:
                current_group.append(day_indices[i])
            else:
                groups.append(current_group)
                current_group = [day_indices[i]]
        
        groups.append(current_group)
        return groups
    
    def _generate_pattern_assignments(self, pattern, consecutive_groups):
        """Generate possible ways to assign pattern blocks within consecutive groups."""
        
        assignments = []
        
        # For each consecutive group, try to fit the entire pattern within it
        for group in consecutive_groups:
            group_len = len(group)
            pattern_total = sum(pattern)
            
            if group_len >= pattern_total:
                # Try different starting positions within the group
                for start_pos in range(group_len - pattern_total + 1):
                    assignment = []
                    current_pos = start_pos
                    
                    # Assign each block in the pattern
                    valid = True
                    for block_idx, block_size in enumerate(pattern):
                        if current_pos + block_size <= group_len:
                            block_days = group[current_pos:current_pos + block_size]
                            assignment.append((block_size, block_days))
                            current_pos += block_size
                        else:
                            valid = False
                            break
                    
                    if valid:
                        assignments.append(assignment)
        
        return assignments
    
    def _try_assign_pattern_assignment(self, assignment, available_indices, comet_eligible, running_totals):
        """Try to assign a specific pattern assignment to doctors."""
        
        # Select doctors for each block based on WTE-adjusted fairness
        selected_doctors = []
        
        for i, (block_size, day_indices) in enumerate(assignment):
            doctor = self._select_doctor_for_block(block_size, day_indices, comet_eligible, running_totals, selected_doctors)
            if doctor is None:
                return False  # Can't find suitable doctor for this block
            selected_doctors.append(doctor)
        
        # If we found doctors for all blocks, make the assignments
        for i, (block_size, day_indices) in enumerate(assignment):
            p_idx, person = selected_doctors[i]
            
            for day_idx in day_indices:
                day_date = self.days[day_idx]
                self.partial_roster[day_date.isoformat()][person.id] = ShiftType.COMET_NIGHT.value
                running_totals[p_idx]['comet_nights'] += 1
        
        return True
    
    def _select_doctor_for_block(self, block_size, day_indices, comet_eligible, running_totals, already_selected):
        """Select the best doctor for a specific block based on WTE-adjusted fairness."""
        
        # Calculate total COMET nights dynamically from COMET weeks
        total_comet_nights = len(self.config.comet_on_weeks) * 7  # 7 nights per COMET week
        total_wte = sum(person.wte for _, person in comet_eligible)
        
        best_doctor = None
        best_shortfall = -1
        
        for p_idx, person in comet_eligible:
            # Skip if already selected for this week pattern
            if (p_idx, person) in already_selected:
                continue
            
            # Check if doctor is available for all days in this block
            available = True
            for day_idx in day_indices:
                day_date = self.days[day_idx]
                current_assignment = self.partial_roster[day_date.isoformat()][person.id]
                if current_assignment != ShiftType.OFF.value:
                    available = False
                    break
                
                # Check if another doctor already has COMET_NIGHT on this day
                for other_person_id, assignment in self.partial_roster[day_date.isoformat()].items():
                    if assignment == ShiftType.COMET_NIGHT.value:
                        available = False
                        break
                
                if not available:
                    break
            
            if not available:
                continue
            
            # Calculate WTE-adjusted target and shortfall
            wte_proportion = person.wte / total_wte
            wte_target = total_comet_nights * wte_proportion
            current_nights = running_totals[p_idx]['comet_nights']
            shortfall = wte_target - current_nights
            
            # Apply stronger WTE-based weighting to prioritize those furthest from target
            # Use percentage shortfall to make selection more sensitive to WTE imbalances
            if wte_target > 0:
                wte_ratio = current_nights / wte_target
                # Give extra weight to doctors who are further below their WTE target
                if wte_ratio < 0.9:  # If getting less than 90% of target
                    wte_boost = (0.9 - wte_ratio) * 5.0  # Strong boost for underassigned
                    shortfall += wte_boost
                elif wte_ratio > 1.1:  # If getting more than 110% of target  
                    wte_penalty = (wte_ratio - 1.1) * 3.0  # Penalty for overassigned
                    shortfall -= wte_penalty
            
            # Apply WTE-aware block size preference for part-time doctors
            adjusted_shortfall = shortfall
            if person.wte <= 0.6:
                # For 0.6 WTE doctors, prefer shorter blocks (2-3 nights) over longer ones (4+ nights)
                if block_size >= 4:
                    # Strong penalty for 4+ night blocks for part-time doctors
                    block_penalty = 4.0  # Increased penalty to strongly discourage long blocks
                    adjusted_shortfall -= block_penalty
                elif block_size in [2, 3]:
                    # Preference for 2-3 night blocks for part-time doctors
                    block_bonus = 1.0  # Increased bonus to encourage shorter blocks
                    adjusted_shortfall += block_bonus
            
            # Select doctor with highest adjusted shortfall (needs most nights, considering WTE preferences)
            if adjusted_shortfall > best_shortfall:
                best_shortfall = adjusted_shortfall
                best_doctor = (p_idx, person)
        
        return best_doctor
    
    def _doctor_focused_cleanup_assignment(self, comet_week_ranges, comet_eligible, running_totals, max_rounds=20):
        """Do a few rounds of doctor-focused assignment to balance remaining assignments."""
        
        # First, check if all COMET nights are already covered
        total_comet_nights = len([d for d in self.days if any(start <= d <= end for start, end in comet_week_ranges)])
        
        covered_nights = 0
        uncovered_days = []
        
        for week_start, week_end in comet_week_ranges:
            for day in self.days:
                if week_start <= day <= week_end:
                    # Check if this day has COMET night coverage
                    day_assignments = self.partial_roster[day.isoformat()]
                    comet_assigned = any(assignment == ShiftType.COMET_NIGHT.value 
                                       for assignment in day_assignments.values())
                    
                    if comet_assigned:
                        covered_nights += 1
                    else:
                        uncovered_days.append(day)
        
        # If all nights are covered, skip cleanup unless there are major imbalances
        if covered_nights == total_comet_nights:
            # Check for major WTE imbalances (>50% deviation from target)
            major_imbalance_detected = False
            total_wte = sum(person.wte for _, person in comet_eligible)
            
            for p_idx, person in comet_eligible:
                comet_nights = running_totals[p_idx]['comet_nights']
                wte_target = (total_comet_nights * person.wte) / total_wte
                wte_ratio = comet_nights / wte_target if wte_target > 0 else 0
                
                # Only worry about major imbalances (less than 50% of target)
                if comet_nights > 0 and wte_ratio < 0.5:  # Someone working but getting <50% of target
                    major_imbalance_detected = True
            
            if not major_imbalance_detected:
                return
        
        # Track failed attempts to detect stuck states
        failed_assignments = {}
        consecutive_failures = 0
        
        for round_num in range(max_rounds):
            # Find doctor who needs the most shifts (WTE-adjusted)
            p_idx, person = self._select_next_doctor_for_comet_nights(comet_eligible, running_totals)
            if p_idx is None:
                print(f"     ✅ All doctors balanced after {round_num} cleanup rounds")
                break
            
            print(f"     🔄 Cleanup round {round_num + 1}: Balancing {person.name}")
            
            # Try to assign a small block (2-3 nights) to this doctor
            cleanup_block_sizes = [2, 3] if person.wte >= 0.8 else [2]
            assigned = self._assign_comet_night_block_smart(p_idx, person, cleanup_block_sizes, comet_week_ranges, running_totals)
            
            if not assigned:
                print(f"     ❌ No cleanup assignment possible for {person.name}")
                
                # Track failed assignments to detect stuck states
                failed_assignments[person.id] = failed_assignments.get(person.id, 0) + 1
                consecutive_failures += 1
                
                # If the same doctor fails 3 times in a row, or we have 5 consecutive failures, stop
                if failed_assignments.get(person.id, 0) >= 3 or consecutive_failures >= 5:
                    print(f"     🛑 Detected stuck state - stopping cleanup after {consecutive_failures} consecutive failures")
                    break
                    
                continue
            else:
                # Reset failure counters on successful assignment
                consecutive_failures = 0
                failed_assignments[person.id] = 0
    
    def reset_to_stage(self, stage_name: str):
        """Reset roster to the beginning of a specific stage."""
        # This would allow admin to go back and redo stages
        # Implementation depends on how you want to handle stage rollbacks
        pass


def solve_roster_sequential(problem: ProblemInput, stage: str = "comet", 
                          timeout_per_stage: int = 1800) -> SequentialSolveResult:
    """
    Solve roster using sequential approach.
    
    Args:
        problem: The roster problem to solve
        stage: Which stage to solve ("comet", "nights", "weekend_holidays", "short_days")
        timeout_per_stage: Timeout for each stage in seconds
        
    Returns:
        SequentialSolveResult with results of the specified stage
    """
    
    solver = SequentialSolver(problem)
    return solver.solve_stage(stage, timeout_per_stage)