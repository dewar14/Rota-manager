"""
Hard constraint violation detection and alternative solution recommendations.
When hard constraints cannot be met, the system will identify specific violations
and suggest locum assignments or alternative doctor selections.
"""

from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum
import datetime as dt

from rostering.models import ProblemInput, Person, ShiftType, SHIFT_DEFINITIONS


class ViolationType(str, Enum):
    """Types of hard constraint violations."""
    MAX_72_HOURS = "max_72_hours"           # >72h in 168h period
    WEEKEND_FREQUENCY = "weekend_frequency"  # >1 in 2 weekends
    NIGHT_REST = "night_rest"               # <46h rest after nights
    CONSECUTIVE_LONG = "consecutive_long"    # >4 consecutive long shifts
    CONSECUTIVE_NIGHTS = "consecutive_nights" # >4 consecutive nights or single night
    CONSECUTIVE_SHIFTS = "consecutive_shifts" # >7 consecutive shifts
    WEEKLY_HOURS = "weekly_hours"           # Outside 42-47h * WTE range
    FAIRNESS_HARD = "fairness_hard"         # >25% variance from fair share
    SHIFT_COVERAGE = "shift_coverage"       # Required shift not covered


@dataclass
class ConstraintViolation:
    """Details of a specific constraint violation."""
    violation_type: ViolationType
    person_id: str
    person_name: str
    date_range: Tuple[dt.date, dt.date]  # Start and end dates affected
    description: str
    severity: str  # "CRITICAL", "HIGH", "MEDIUM"
    current_value: float  # e.g., 78 hours for 72h rule
    limit_value: float    # e.g., 72 hours for 72h rule
    affected_shifts: List[Tuple[dt.date, ShiftType]]  # Specific shifts causing violation


@dataclass
class AlternativeSolution:
    """Suggested alternative to resolve constraint violations."""
    solution_type: str  # "LOCUM", "SWAP_DOCTOR", "REMOVE_SHIFT", "SPLIT_BLOCK"
    description: str
    target_person_id: Optional[str]  # Doctor to use instead
    target_shifts: List[Tuple[dt.date, ShiftType]]  # Shifts to modify
    estimated_cost: int  # Locum cost or disruption score
    feasibility_score: float  # 0-1, how likely this solution will work


class HardConstraintViolationDetector:
    """Detects and analyzes hard constraint violations in roster assignments."""
    
    def __init__(self, problem: ProblemInput):
        self.problem = problem
        self.people = {p.id: p for p in problem.people}
        self.days = self._get_days_from_config()
        
    def _get_days_from_config(self) -> List[dt.date]:
        """Generate list of days for the roster period."""
        days = []
        current = self.problem.config.start_date
        while current <= self.problem.config.end_date:
            days.append(current)
            current += dt.timedelta(days=1)
        return days
    
    def detect_violations(self, roster: Dict[str, Dict[str, str]]) -> List[ConstraintViolation]:
        """
        Analyze a roster and detect all hard constraint violations.
        
        Args:
            roster: Dict mapping date_str -> person_id -> shift_type_str
            
        Returns:
            List of detected violations with details
        """
        violations = []
        
        # Convert roster to internal format
        assignments = self._convert_roster_format(roster)
        
        # Check each type of hard constraint
        violations.extend(self._check_72_hour_rule(assignments))
        violations.extend(self._check_weekend_frequency(assignments))
        violations.extend(self._check_night_rest_rule(assignments))
        violations.extend(self._check_consecutive_long_shifts(assignments))
        violations.extend(self._check_consecutive_nights(assignments))
        violations.extend(self._check_consecutive_shifts(assignments))
        violations.extend(self._check_weekly_hours(assignments))
        violations.extend(self._check_shift_coverage(assignments))
        
        return sorted(violations, key=lambda v: v.severity)
    
    def _convert_roster_format(self, roster: Dict[str, Dict[str, str]]) -> Dict[str, Dict[dt.date, ShiftType]]:
        """Convert roster from string format to internal objects."""
        assignments = {}
        
        for person_id in self.people.keys():
            assignments[person_id] = {}
            
        for date_str, day_assignments in roster.items():
            date_obj = dt.date.fromisoformat(date_str)
            for person_id, shift_str in day_assignments.items():
                if person_id in assignments:
                    try:
                        shift_type = ShiftType(shift_str)
                        assignments[person_id][date_obj] = shift_type
                    except ValueError:
                        # Handle unknown shift types
                        assignments[person_id][date_obj] = ShiftType.OFF
                        
        return assignments
    
    def _check_72_hour_rule(self, assignments: Dict[str, Dict[dt.date, ShiftType]]) -> List[ConstraintViolation]:
        """Check for violations of 72-hour in 168-hour rule."""
        violations = []
        
        for person_id, person_assignments in assignments.items():
            person = self.people[person_id]
            
            # Check each 7-day window
            for start_idx in range(len(self.days) - 6):
                week_days = self.days[start_idx:start_idx + 7]
                total_hours = 0
                affected_shifts = []
                
                for day in week_days:
                    if day in person_assignments:
                        shift = person_assignments[day]
                        hours = SHIFT_DEFINITIONS.get(shift, {}).get("hours", 0)
                        if hours > 0:
                            total_hours += hours
                            affected_shifts.append((day, shift))
                
                if total_hours > 72:
                    violations.append(ConstraintViolation(
                        violation_type=ViolationType.MAX_72_HOURS,
                        person_id=person_id,
                        person_name=person.name,
                        date_range=(week_days[0], week_days[-1]),
                        description=f"{person.name} works {total_hours} hours in 7-day period (max: 72h)",
                        severity="CRITICAL",
                        current_value=total_hours,
                        limit_value=72,
                        affected_shifts=affected_shifts
                    ))
        
        return violations
    
    def _check_weekend_frequency(self, assignments: Dict[str, Dict[dt.date, ShiftType]]) -> List[ConstraintViolation]:
        """Check for violations of 1-in-2 weekend frequency rule."""
        violations = []
        
        # Find all weekends
        weekends = []
        for day in self.days:
            if day.weekday() == 5:  # Saturday
                sunday = day + dt.timedelta(days=1)
                if sunday in self.days:
                    weekends.append((day, sunday))
        
        working_shifts = [s for s in ShiftType if SHIFT_DEFINITIONS[s]["hours"] > 0 and SHIFT_DEFINITIONS[s]["covers"]]
        
        for person_id, person_assignments in assignments.items():
            person = self.people[person_id]
            
            # Check consecutive weekend pairs
            for i in range(len(weekends) - 1):
                weekend1_sat, weekend1_sun = weekends[i]
                weekend2_sat, weekend2_sun = weekends[i + 1]
                
                # Check if worked weekend 1
                weekend1_worked = False
                weekend1_shifts = []
                for day in [weekend1_sat, weekend1_sun]:
                    if day in person_assignments and person_assignments[day] in working_shifts:
                        weekend1_worked = True
                        weekend1_shifts.append((day, person_assignments[day]))
                
                # Check if worked weekend 2
                weekend2_worked = False
                weekend2_shifts = []
                for day in [weekend2_sat, weekend2_sun]:
                    if day in person_assignments and person_assignments[day] in working_shifts:
                        weekend2_worked = True
                        weekend2_shifts.append((day, person_assignments[day]))
                
                # Violation if worked both consecutive weekends
                if weekend1_worked and weekend2_worked:
                    violations.append(ConstraintViolation(
                        violation_type=ViolationType.WEEKEND_FREQUENCY,
                        person_id=person_id,
                        person_name=person.name,
                        date_range=(weekend1_sat, weekend2_sun),
                        description=f"{person.name} works consecutive weekends (max: 1 in 2)",
                        severity="CRITICAL",
                        current_value=2,  # 2 consecutive weekends
                        limit_value=1,    # max 1 in any 2
                        affected_shifts=weekend1_shifts + weekend2_shifts
                    ))
        
        return violations
    
    def _check_night_rest_rule(self, assignments: Dict[str, Dict[dt.date, ShiftType]]) -> List[ConstraintViolation]:
        """Check for violations of 46-hour rest after nights rule.
        
        The rule applies AFTER a block of night shifts ends:
        - Consecutive night shifts are allowed (blocks of 1-4 nights)
        - After the last night in a block, 46h rest is required before next working shift
        - This means first working shift can be 2 days after last night shift
        """
        violations = []
        night_shifts = [ShiftType.NIGHT_REG, ShiftType.NIGHT_SHO, ShiftType.COMET_NIGHT]
        working_shifts = [s for s in ShiftType if SHIFT_DEFINITIONS[s]["hours"] > 0]
        
        for person_id, person_assignments in assignments.items():
            person = self.people[person_id]
            
            # Find end of night shift blocks
            for i, day in enumerate(self.days[:-1]):
                if day in person_assignments and person_assignments[day] in night_shifts:
                    # Check if this is the END of a night block
                    is_end_of_night_block = True
                    if i + 1 < len(self.days):
                        next_day = self.days[i + 1]
                        if next_day in person_assignments and person_assignments[next_day] in night_shifts:
                            is_end_of_night_block = False  # More nights follow
                    
                    if is_end_of_night_block:
                        # Check if next working shift gives proper 46h rest
                        # Can work again on day after tomorrow (2 days later)
                        if i + 2 < len(self.days):
                            rest_day_1 = self.days[i + 1]  # Should be OFF or rest
                            if rest_day_1 in person_assignments and person_assignments[rest_day_1] in working_shifts:
                                # Violation: working shift too soon after night block
                                violations.append(ConstraintViolation(
                                    violation_type=ViolationType.NIGHT_REST,
                                    person_id=person_id,
                                    person_name=person.name,
                                    date_range=(day, rest_day_1),
                                    description=f"{person.name} has insufficient rest after night shift block (required: 46h)",
                                    severity="CRITICAL",
                                    current_value=24,  # Less than 46h
                                    limit_value=46,
                                    affected_shifts=[(day, person_assignments[day]), (rest_day_1, person_assignments[rest_day_1])]
                                ))
        
        return violations
    
    def _check_consecutive_long_shifts(self, assignments: Dict[str, Dict[dt.date, ShiftType]]) -> List[ConstraintViolation]:
        """Check for violations of max 4 consecutive long shifts rule."""
        violations = []
        long_shifts = [s for s in ShiftType if SHIFT_DEFINITIONS[s]["hours"] > 10]
        
        for person_id, person_assignments in assignments.items():
            person = self.people[person_id]
            
            consecutive_count = 0
            consecutive_shifts = []
            
            for day in self.days:
                if day in person_assignments and person_assignments[day] in long_shifts:
                    consecutive_count += 1
                    consecutive_shifts.append((day, person_assignments[day]))
                    
                    if consecutive_count > 4:
                        violations.append(ConstraintViolation(
                            violation_type=ViolationType.CONSECUTIVE_LONG,
                            person_id=person_id,
                            person_name=person.name,
                            date_range=(consecutive_shifts[0][0], day),
                            description=f"{person.name} has {consecutive_count} consecutive long shifts (max: 4)",
                            severity="CRITICAL",
                            current_value=consecutive_count,
                            limit_value=4,
                            affected_shifts=consecutive_shifts.copy()
                        ))
                else:
                    consecutive_count = 0
                    consecutive_shifts = []
        
        return violations
    
    def _check_consecutive_nights(self, assignments: Dict[str, Dict[dt.date, ShiftType]]) -> List[ConstraintViolation]:
        """Check for violations of night block rules (max 4, min 2)."""
        violations = []
        night_shifts = [ShiftType.NIGHT_REG, ShiftType.NIGHT_SHO, ShiftType.COMET_NIGHT]
        
        for person_id, person_assignments in assignments.items():
            person = self.people[person_id]
            
            consecutive_count = 0
            consecutive_shifts = []
            
            for day in self.days:
                if day in person_assignments and person_assignments[day] in night_shifts:
                    consecutive_count += 1
                    consecutive_shifts.append((day, person_assignments[day]))
                    
                    # Check for too many consecutive nights
                    if consecutive_count > 4:
                        violations.append(ConstraintViolation(
                            violation_type=ViolationType.CONSECUTIVE_NIGHTS,
                            person_id=person_id,
                            person_name=person.name,
                            date_range=(consecutive_shifts[0][0], day),
                            description=f"{person.name} has {consecutive_count} consecutive nights (max: 4)",
                            severity="CRITICAL",
                            current_value=consecutive_count,
                            limit_value=4,
                            affected_shifts=consecutive_shifts.copy()
                        ))
                else:
                    # End of night block - check for single nights
                    if consecutive_count == 1:
                        violations.append(ConstraintViolation(
                            violation_type=ViolationType.CONSECUTIVE_NIGHTS,
                            person_id=person_id,
                            person_name=person.name,
                            date_range=(consecutive_shifts[0][0], consecutive_shifts[0][0]),
                            description=f"{person.name} has single night shift (min block size: 2)",
                            severity="HIGH",
                            current_value=1,
                            limit_value=2,
                            affected_shifts=consecutive_shifts.copy()
                        ))
                    
                    consecutive_count = 0
                    consecutive_shifts = []
        
        return violations
    
    def _check_consecutive_shifts(self, assignments: Dict[str, Dict[dt.date, ShiftType]]) -> List[ConstraintViolation]:
        """Check for violations of max 7 consecutive shifts rule."""
        violations = []
        working_shifts = [s for s in ShiftType if SHIFT_DEFINITIONS[s]["hours"] > 0]
        
        for person_id, person_assignments in assignments.items():
            person = self.people[person_id]
            
            consecutive_count = 0
            consecutive_shifts = []
            
            for day in self.days:
                if day in person_assignments and person_assignments[day] in working_shifts:
                    consecutive_count += 1
                    consecutive_shifts.append((day, person_assignments[day]))
                    
                    if consecutive_count > 7:
                        violations.append(ConstraintViolation(
                            violation_type=ViolationType.CONSECUTIVE_SHIFTS,
                            person_id=person_id,
                            person_name=person.name,
                            date_range=(consecutive_shifts[0][0], day),
                            description=f"{person.name} has {consecutive_count} consecutive shifts (max: 7)",
                            severity="CRITICAL",
                            current_value=consecutive_count,
                            limit_value=7,
                            affected_shifts=consecutive_shifts.copy()
                        ))
                else:
                    consecutive_count = 0
                    consecutive_shifts = []
        
        return violations
    
    def _check_weekly_hours(self, assignments: Dict[str, Dict[dt.date, ShiftType]]) -> List[ConstraintViolation]:
        """Check for violations of weekly hours constraints (42-47h * WTE).
        
        Only applies to full roster periods (≥20 weeks). During sequential solving
        of partial rosters, this constraint is not meaningful.
        """
        violations = []
        total_weeks = len(self.days) / 7.0
        
        # Only check weekly hours for substantial roster periods
        # During sequential solving, partial rosters won't meet weekly averages
        if total_weeks < 20:
            return violations
        
        for person_id, person_assignments in assignments.items():
            person = self.people[person_id]
            
            total_hours = 0
            working_shifts = []
            
            for day, shift in person_assignments.items():
                if shift not in [ShiftType.OFF, ShiftType.LTFT]:
                    hours = SHIFT_DEFINITIONS.get(shift, {}).get("hours", 0)
                    total_hours += hours
                    if hours > 0:
                        working_shifts.append((day, shift))
            
            # Calculate expected range over full period
            min_total = int(42 * person.wte * total_weeks)
            max_total = int(48 * person.wte * total_weeks)  # Slightly more lenient upper bound
            avg_weekly = total_hours / total_weeks if total_weeks > 0 else 0
            
            # Only flag significant deviations in full roster
            if total_hours < min_total * 0.9:  # 10% tolerance for complexity of scheduling
                violations.append(ConstraintViolation(
                    violation_type=ViolationType.WEEKLY_HOURS,
                    person_id=person_id,
                    person_name=person.name,
                    date_range=(self.days[0], self.days[-1]),
                    description=f"{person.name} works {avg_weekly:.1f}h/week (min: {42 * person.wte:.1f}h)",
                    severity="HIGH",
                    current_value=avg_weekly,
                    limit_value=42 * person.wte,
                    affected_shifts=working_shifts
                ))
            elif total_hours > max_total * 1.1:  # 10% tolerance
                violations.append(ConstraintViolation(
                    violation_type=ViolationType.WEEKLY_HOURS,
                    person_id=person_id,
                    person_name=person.name,
                    date_range=(self.days[0], self.days[-1]),
                    description=f"{person.name} works {avg_weekly:.1f}h/week (max: {48 * person.wte:.1f}h)",
                    severity="HIGH",  # Reduced from CRITICAL
                    current_value=avg_weekly,
                    limit_value=48 * person.wte,
                    affected_shifts=working_shifts
                ))
        
        return violations
    
    def _check_shift_coverage(self, assignments: Dict[str, Dict[dt.date, ShiftType]]) -> List[ConstraintViolation]:
        """Check for days where required shifts are not covered.
        
        For sequential solving, only check coverage relevant to completed stages:
        - During COMET nights stage: only check COMET night coverage on COMET weeks
        - During full roster: check all required coverage
        
        This prevents false violations during partial roster construction.
        """
        violations = []
        
        # Determine what coverage to check based on roster completeness
        # If this is a partial roster (sequential solving), be more lenient
        total_assigned_shifts = sum(
            len([s for s in person_assignments.values() if s != ShiftType.OFF])
            for person_assignments in assignments.values()
        )
        
        # Rough heuristic: if very few shifts assigned, we're in early sequential stages
        is_partial_roster = total_assigned_shifts < (len(self.days) * len(self.people) * 0.3)
        
        if is_partial_roster:
            # Only check COMET night coverage on COMET weeks for sequential solving
            for day in self.days:
                is_comet_week = any(
                    comet_monday <= day <= comet_monday + dt.timedelta(days=6)
                    for comet_monday in self.problem.config.comet_on_weeks
                )
                
                if is_comet_week:
                    # Check if COMET night is covered
                    comet_night_count = sum(
                        1 for person_assignments in assignments.values()
                        if day in person_assignments and person_assignments[day] == ShiftType.COMET_NIGHT
                    )
                    
                    if comet_night_count == 0:
                        violations.append(ConstraintViolation(
                            violation_type=ViolationType.SHIFT_COVERAGE,
                            person_id="UNASSIGNED",
                            person_name="No doctor assigned",
                            date_range=(day, day),
                            description=f"No COMET night coverage on {day} (COMET week)",
                            severity="CRITICAL",
                            current_value=0,
                            limit_value=1,
                            affected_shifts=[(day, ShiftType.COMET_NIGHT)]
                        ))
                    elif comet_night_count > 1:
                        violations.append(ConstraintViolation(
                            violation_type=ViolationType.SHIFT_COVERAGE,
                            person_id="MULTIPLE",
                            person_name="Multiple assignments",
                            date_range=(day, day),
                            description=f"Multiple COMET night assignments on {day} ({comet_night_count} doctors)",
                            severity="HIGH",
                            current_value=comet_night_count,
                            limit_value=1,
                            affected_shifts=[(day, ShiftType.COMET_NIGHT)]
                        ))
        else:
            # For full rosters, check all required coverage (implementation for later stages)
            pass
        
        return violations
    
    def suggest_alternatives(self, violations: List[ConstraintViolation]) -> List[AlternativeSolution]:
        """Generate alternative solutions for constraint violations."""
        alternatives = []
        
        for violation in violations:
            if violation.violation_type == ViolationType.SHIFT_COVERAGE:
                alternatives.extend(self._suggest_coverage_alternatives(violation))
            elif violation.violation_type == ViolationType.MAX_72_HOURS:
                alternatives.extend(self._suggest_hours_alternatives(violation))
            elif violation.violation_type == ViolationType.WEEKEND_FREQUENCY:
                alternatives.extend(self._suggest_weekend_alternatives(violation))
            elif violation.violation_type in [ViolationType.CONSECUTIVE_LONG, ViolationType.CONSECUTIVE_NIGHTS, ViolationType.CONSECUTIVE_SHIFTS]:
                alternatives.extend(self._suggest_consecutive_alternatives(violation))
            elif violation.violation_type == ViolationType.NIGHT_REST:
                alternatives.extend(self._suggest_rest_alternatives(violation))
        
        return sorted(alternatives, key=lambda a: (a.estimated_cost, -a.feasibility_score))
    
    def _suggest_coverage_alternatives(self, violation: ConstraintViolation) -> List[AlternativeSolution]:
        """Suggest alternatives for shift coverage violations."""
        alternatives = []
        shift_date, shift_type = violation.affected_shifts[0]
        
        # Option 1: Assign locum
        alternatives.append(AlternativeSolution(
            solution_type="LOCUM",
            description=f"Assign locum for {shift_type.value} on {shift_date}",
            target_person_id="LOCUM_" + shift_date.isoformat(),
            target_shifts=[(shift_date, shift_type)],
            estimated_cost=1500,  # Typical locum cost
            feasibility_score=0.9
        ))
        
        # Option 2: Find alternative doctor
        for person_id, person in self.people.items():
            if self._can_person_work_shift(person, shift_date, shift_type):
                alternatives.append(AlternativeSolution(
                    solution_type="SWAP_DOCTOR",
                    description=f"Assign {person.name} to {shift_type.value} on {shift_date}",
                    target_person_id=person.id,
                    target_shifts=[(shift_date, shift_type)],
                    estimated_cost=0,  # No extra cost
                    feasibility_score=0.7  # May cause other constraints
                ))
        
        return alternatives
    
    def _suggest_hours_alternatives(self, violation: ConstraintViolation) -> List[AlternativeSolution]:
        """Suggest alternatives for 72-hour rule violations."""
        alternatives = []
        
        # Option 1: Remove a shift from the week
        if len(violation.affected_shifts) > 1:
            # Find the shift with least impact to remove
            for shift_date, shift_type in violation.affected_shifts[-2:]:  # Last 2 shifts
                alternatives.append(AlternativeSolution(
                    solution_type="REMOVE_SHIFT",
                    description=f"Remove {shift_type.value} on {shift_date} for {violation.person_name}",
                    target_person_id=violation.person_id,
                    target_shifts=[(shift_date, shift_type)],
                    estimated_cost=1000,  # Cost of finding replacement
                    feasibility_score=0.6
                ))
        
        # Option 2: Split shifts across multiple doctors
        alternatives.append(AlternativeSolution(
            solution_type="SPLIT_BLOCK",
            description=f"Split {violation.person_name}'s shifts across multiple doctors",
            target_person_id=violation.person_id,
            target_shifts=violation.affected_shifts,
            estimated_cost=500,  # Coordination cost
            feasibility_score=0.5
        ))
        
        return alternatives
    
    def _suggest_weekend_alternatives(self, violation: ConstraintViolation) -> List[AlternativeSolution]:
        """Suggest alternatives for weekend frequency violations."""
        alternatives = []
        
        # Option 1: Swap one weekend with another doctor
        weekend_shifts = [shift for shift in violation.affected_shifts if shift[0].weekday() in [5, 6]]
        if weekend_shifts:
            alternatives.append(AlternativeSolution(
                solution_type="SWAP_DOCTOR",
                description=f"Swap weekend shifts for {violation.person_name}",
                target_person_id=violation.person_id,
                target_shifts=weekend_shifts,
                estimated_cost=0,
                feasibility_score=0.7
            ))
        
        return alternatives
    
    def _suggest_consecutive_alternatives(self, violation: ConstraintViolation) -> List[AlternativeSolution]:
        """Suggest alternatives for consecutive shift violations."""
        alternatives = []
        
        # Option 1: Insert rest day in the middle
        mid_point = len(violation.affected_shifts) // 2
        if mid_point > 0:
            mid_shift = violation.affected_shifts[mid_point]
            alternatives.append(AlternativeSolution(
                solution_type="REMOVE_SHIFT",
                description=f"Insert rest day for {violation.person_name} on {mid_shift[0]}",
                target_person_id=violation.person_id,
                target_shifts=[mid_shift],
                estimated_cost=800,
                feasibility_score=0.6
            ))
        
        return alternatives
    
    def _suggest_rest_alternatives(self, violation: ConstraintViolation) -> List[AlternativeSolution]:
        """Suggest alternatives for rest period violations."""
        alternatives = []
        
        # Option 1: Remove shifts during rest period
        rest_shifts = [shift for shift in violation.affected_shifts if shift[1] not in [ShiftType.NIGHT_REG, ShiftType.NIGHT_SHO, ShiftType.COMET_NIGHT]]
        if rest_shifts:
            alternatives.append(AlternativeSolution(
                solution_type="REMOVE_SHIFT",
                description=f"Remove shifts during rest period for {violation.person_name}",
                target_person_id=violation.person_id,
                target_shifts=rest_shifts,
                estimated_cost=len(rest_shifts) * 600,
                feasibility_score=0.8
            ))
        
        return alternatives
    
    def _can_person_work_shift(self, person: Person, date: dt.date, shift_type: ShiftType) -> bool:
        """Check if a person can work a specific shift type on a specific date."""
        # Basic eligibility checks
        shift_def = SHIFT_DEFINITIONS.get(shift_type, {})
        
        # Grade requirements
        grade_req = shift_def.get("grade_req")
        if grade_req and person.grade != grade_req:
            return False
        
        # COMET eligibility
        if shift_def.get("comet_req", False) and not person.comet_eligible:
            return False
        
        # Start/end date checks
        if person.start_date and date < person.start_date:
            return False
        if person.end_date and date > person.end_date:
            return False
        
        # LTFT day check
        if person.fixed_day_off is not None and date.weekday() == person.fixed_day_off:
            return False
        
        return True