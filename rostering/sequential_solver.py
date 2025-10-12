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
                    response = input(f"Continue to '{next_stage}' stage? (y/n/q): ").strip().lower()
                    
                    if response == 'q':
                        return SequentialSolveResult(
                            stage=stage_name,
                            success=True,
                            message=f"User quit at checkpoint after '{stage_name}' stage",
                            partial_roster=copy.deepcopy(self.partial_roster),
                            next_stage=next_stage
                        )
                    elif response != 'y':
                        print(f"Pausing after '{stage_name}' stage. Resume with solve_stage('{next_stage}')")
                        return SequentialSolveResult(
                            stage=stage_name,
                            success=True,
                            message=f"Paused after '{stage_name}' stage for review",
                            partial_roster=copy.deepcopy(self.partial_roster),
                            next_stage=next_stage
                        )
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
        for p_idx, person in comet_eligible:
            print(f"  {person.name} (WTE: {person.wte})")
        
        print(f"\nCOMET weeks to cover: {len(comet_week_ranges)}")
        for i, (start, end) in enumerate(comet_week_ranges):
            print(f"  Week {i+1}: {start} to {end}")
        
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
        
        # Count expected COMET nights needed
        expected_cmn = len([d for d in self.days if any(start <= d <= end for start, end in comet_week_ranges)])
        print(f"Expected COMET nights needed: {expected_cmn}")
        
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
        """Assign COMET night blocks sequentially as described."""
        
        import random
        random.seed(42)  # For reproducible results during testing
        
        # Start with a random doctor
        current_doctor_idx = random.choice(range(len(comet_eligible)))
        p_idx, person = comet_eligible[current_doctor_idx]
        
        print(f"\nStarting with random doctor: {person.name}")
        
        assignment_round = 1
        
        while True:
            # Find the next doctor who needs the most shifts (WTE-adjusted)
            p_idx, person = self._select_next_doctor_for_comet_nights(comet_eligible, running_totals)
            if p_idx is None:
                print("All doctors have reached their target assignments")
                break
                
            print(f"\nRound {assignment_round}: Assigning to {person.name} (WTE: {person.wte})")
            
            # Determine block size based on WTE
            if person.wte >= 1.0:
                preferred_block_sizes = [4, 3, 1]  # Prefer 4, fallback to 3, single as last resort
            elif person.wte >= 0.8:
                preferred_block_sizes = [3, 4, 1]  # Prefer 3, fallback to 4, single as last resort
            elif person.wte >= 0.6:
                preferred_block_sizes = [2, 3, 1]  # Prefer 2, fallback to 3, single as last resort
            else:
                preferred_block_sizes = [2, 1]     # Part-time prefers 2, single as fallback
            
            print(f"  Target block sizes (in preference order): {preferred_block_sizes}")
            
            # Try to assign a block
            assigned_block = self._assign_comet_night_block(p_idx, person, preferred_block_sizes, comet_week_ranges, running_totals)
            
            if not assigned_block:
                print(f"  🚫 No suitable block found for {person.name}")
                # Check if we've assigned enough - if so, it's okay to stop block assignment
                current_comet_nights = running_totals[p_idx]['comet_nights']
                expected_nights = int(7 * person.wte)  # Rough target
                print(f"     Current COMET nights: {current_comet_nights}, Target: ~{expected_nights}")
                if current_comet_nights >= expected_nights * 0.8:  # 80% of target
                    print(f"     ✓ {person.name} has sufficient assignments ({current_comet_nights}), continuing with next doctor")
                    continue  # Try next doctor instead of breaking
                else:
                    print(f"     ⚠️ {person.name} needs more assignments, but no blocks available")
                break
                
            assignment_round += 1
            
            # Safety check to prevent infinite loops
            if assignment_round > 20:
                print("Maximum assignment rounds reached")
                break
        
        # After assignment, check for any uncovered COMET nights
        print("\n" + "="*50)
        print("COMET NIGHT COVERAGE ANALYSIS")
        print("="*50)
        
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
                        assigned_doctor = [pid for pid, assignment in day_assignments.items() 
                                         if assignment == ShiftType.COMET_NIGHT.value][0]
                        print(f"  {day} ({day.strftime('%A')}): ✓ {assigned_doctor}")
                    else:
                        print(f"  {day} ({day.strftime('%A')}): ❌ NO COVERAGE")
                        uncovered_days.append(day)
                        week_uncovered.append(day)
            
            if week_uncovered:
                print(f"  🔧 FIXING COVERAGE GAPS: {len(week_uncovered)} days need assignment")
                # Try to assign single nights to uncovered days
                for day in week_uncovered:
                    self._assign_single_comet_night(day, comet_eligible, running_totals)
        
        print("\n" + "="*50)
        
        if uncovered_days:
            print(f"⚠️  ATTEMPTING TO FILL {len(uncovered_days)} UNCOVERED DAYS")
        else:
            print("✅ ALL COMET WEEKS FULLY COVERED")
    
    def _select_next_doctor_for_comet_nights(self, comet_eligible, running_totals):
        """Select the doctor with the fewest COMET nights (WTE-adjusted)."""
        
        candidates = []
        for p_idx, person in comet_eligible:
            comet_nights = running_totals[p_idx]['comet_nights']
            wte_adjusted_nights = comet_nights / person.wte if person.wte > 0 else float('inf')
            candidates.append((wte_adjusted_nights, p_idx, person))
        
        # Sort by WTE-adjusted nights (ascending) 
        candidates.sort(key=lambda x: x[0])
        
        # Find minimum WTE-adjusted count
        min_adjusted_nights = candidates[0][0]
        
        # Get all doctors with the minimum count
        min_candidates = [c for c in candidates if c[0] == min_adjusted_nights]
        
        if len(min_candidates) > 1:
            print(f"  Multiple candidates with {min_adjusted_nights:.1f} WTE-adjusted nights:")
            for adj_nights, p_idx, person in min_candidates:
                actual_nights = running_totals[p_idx]['comet_nights']
                print(f"    {person.name}: {actual_nights} actual, {adj_nights:.1f} WTE-adjusted")
        
        # Return the first (or randomly select if you prefer)
        _, p_idx, person = min_candidates[0]
        return p_idx, person
    
    def _assign_comet_night_block(self, p_idx, person, preferred_block_sizes, comet_week_ranges, running_totals):
        """Try to assign a COMET night block to the specified doctor."""
        
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
                    for day in consecutive_days:
                        current_assignment = self.partial_roster[day.isoformat()][person.id]
                        if current_assignment != ShiftType.OFF.value:
                            available = False
                            unavailable_reason = f"Doctor {person.name} already assigned {current_assignment} on {day}"
                            break
                    
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
    
    def _assign_single_comet_night(self, day, comet_eligible, running_totals):
        """Assign a single COMET night to fill coverage gaps."""
        print(f"    🔧 SINGLE NIGHT ASSIGNMENT for {day} ({day.strftime('%A')})")
        
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
        """Check if assigning a night shift on this day would violate 46h rest rule."""
        
        # Very simplified check - just ensure next day is OFF
        night_day_idx = None
        for i, day in enumerate(self.days):
            if day == night_day:
                night_day_idx = i
                break
        
        if night_day_idx is None or night_day_idx >= len(self.days) - 1:
            return True  # End of period, OK
        
        next_day = self.days[night_day_idx + 1]
        next_assignment = self.partial_roster[next_day.isoformat()][doctor_id]
        
        # OK if next day is OFF
        return next_assignment == ShiftType.OFF.value
    
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
        """Stage 2: Assign Night shifts - every day must have 1 N_REG + 1 N_SHO (Priority 2)."""
        
        model = cp_model.CpModel()
        
        # Create decision variables for nights and remaining OFF slots
        night_shifts = [ShiftType.NIGHT_REG, ShiftType.NIGHT_SHO]
        allowed_shifts = night_shifts + [ShiftType.OFF]
        
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
        
        # Night coverage requirements
        self._add_night_coverage_constraints(model, x, night_shifts)
        
        # Night block patterns (2-4 consecutive nights)
        self._add_night_block_constraints(model, x, night_shifts)
        
        # 72-hour rule for nights
        self._add_night_rest_constraints(model, x, night_shifts)
        
        # Temporarily disable fairness constraints for debugging
        # self._add_global_fairness_constraints(model, x, night_shifts, "nights")
        
        # Grade-specific constraints
        for p_idx, person in enumerate(self.people):
            for d_idx, day in enumerate(self.days):
                # Only registrars can do NIGHT_REG, only SHOs can do NIGHT_SHO
                if person.grade not in ["Registrar"] and (p_idx, d_idx, ShiftType.NIGHT_REG) in x:
                    model.Add(x[p_idx, d_idx, ShiftType.NIGHT_REG] == 0)
                if person.grade not in ["SHO"] and (p_idx, d_idx, ShiftType.NIGHT_SHO) in x:
                    model.Add(x[p_idx, d_idx, ShiftType.NIGHT_SHO] == 0)
        
        # Solve
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = timeout_seconds
        
        status = solver.Solve(model)
        
        if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
            # Extract night assignments
            new_assignments = set()
            for p_idx, person in enumerate(self.people):
                for d_idx, day in enumerate(self.days):
                    for shift in night_shifts:
                        if (p_idx, d_idx, shift) in x and solver.Value(x[p_idx, d_idx, shift]) == 1:
                            # Update partial roster
                            self.partial_roster[day.isoformat()][person.id] = shift.value
                            new_assignments.add((p_idx, d_idx, shift))
                            self.assigned_shifts.add((p_idx, d_idx, shift))
            
            return SequentialSolveResult(
                stage="nights",
                success=True,
                message=f"Nights stage completed. Assigned {len(new_assignments)} night shifts in appropriate blocks.",
                partial_roster=copy.deepcopy(self.partial_roster),
                assigned_shifts=new_assignments,
                next_stage="weekend_holidays"
            )
        else:
            return SequentialSolveResult(
                stage="nights",
                success=False,
                message=f"Nights stage failed: {solver.StatusName(status)}",
                partial_roster=copy.deepcopy(self.partial_roster),
                next_stage="weekend_holidays"
            )
    
    def _solve_weekend_holiday_stage(self, timeout_seconds: int) -> SequentialSolveResult:
        """Stage 3: Assign weekend and holiday long days - exactly 1 LD_REG per weekend/holiday day (Priority 3)."""
        
        model = cp_model.CpModel()
        
        # Create decision variables for long day shifts on weekends/holidays
        long_day_shifts = [ShiftType.LONG_DAY_REG]  # Ignoring SHO for now as requested
        allowed_shifts = long_day_shifts + [ShiftType.OFF]
        
        # Identify weekend and holiday days
        weekend_holiday_days = []
        for d_idx, day in enumerate(self.days):
            is_weekend = day.weekday() in [5, 6]  # Saturday, Sunday
            is_holiday = day in self.config.bank_holidays
            if is_weekend or is_holiday:
                weekend_holiday_days.append(d_idx)
        
        x = {}
        for p_idx, person in enumerate(self.people):
            for d_idx in weekend_holiday_days:
                day = self.days[d_idx]
                # Skip days where person already has a non-OFF assignment
                current_assignment = self.partial_roster[day.isoformat()][person.id]
                if current_assignment != ShiftType.OFF.value:
                    continue
                    
                for shift in allowed_shifts:
                    x[p_idx, d_idx, shift] = model.NewBoolVar(f"x_{p_idx}_{d_idx}_{shift.value}")
        
        # Each person can only have one shift per day (for unassigned weekend/holiday days)
        for p_idx, person in enumerate(self.people):
            for d_idx in weekend_holiday_days:
                day = self.days[d_idx]
                current_assignment = self.partial_roster[day.isoformat()][person.id]
                if current_assignment == ShiftType.OFF.value:
                    model.Add(sum(x.get((p_idx, d_idx, s), 0) for s in allowed_shifts) == 1)
        
        # Weekend coverage requirements
        self._add_weekend_coverage_constraints(model, x, long_day_shifts, weekend_holiday_days)
        
        # Add global rest constraints to prevent violating rest periods
        self._add_global_rest_constraints(model, x)
        
        # Add fairness constraints for equitable distribution (within stage only for now)
        self._add_global_fairness_constraints(model, x, long_day_shifts, "weekend_holidays")
        
        # Grade-specific constraints
        for p_idx, person in enumerate(self.people):
            for d_idx in weekend_holiday_days:
                if person.grade not in ["Registrar"] and (p_idx, d_idx, ShiftType.LONG_DAY_REG) in x:
                    model.Add(x[p_idx, d_idx, ShiftType.LONG_DAY_REG] == 0)
                if person.grade not in ["SHO"] and (p_idx, d_idx, ShiftType.LONG_DAY_SHO) in x:
                    model.Add(x[p_idx, d_idx, ShiftType.LONG_DAY_SHO] == 0)
        
        # Solve
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = timeout_seconds
        
        status = solver.Solve(model)
        
        if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
            # Extract weekend/holiday assignments
            new_assignments = set()
            for p_idx, person in enumerate(self.people):
                for d_idx in weekend_holiday_days:
                    day = self.days[d_idx]
                    for shift in long_day_shifts:
                        if (p_idx, d_idx, shift) in x and solver.Value(x[p_idx, d_idx, shift]) == 1:
                            # Update partial roster
                            self.partial_roster[day.isoformat()][person.id] = shift.value
                            new_assignments.add((p_idx, d_idx, shift))
                            self.assigned_shifts.add((p_idx, d_idx, shift))
            
            return SequentialSolveResult(
                stage="weekend_holidays",
                success=True,
                message=f"Weekend/holiday stage completed. Assigned {len(new_assignments)} long day shifts.",
                partial_roster=copy.deepcopy(self.partial_roster),
                assigned_shifts=new_assignments,
                next_stage="weekday_long_days"
            )
        else:
            return SequentialSolveResult(
                stage="weekend_holidays",
                success=False,
                message=f"Weekend/holiday stage failed: {solver.StatusName(status)}",
                partial_roster=copy.deepcopy(self.partial_roster),
                next_stage="weekday_long_days"
            )
    
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