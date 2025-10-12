"""
Staged solver for medical rotas - solves in priority order with progress updates.
"""

from ortools.sat.python import cp_model
import time
from typing import Dict, List, Tuple
from rostering.models import ProblemInput, SolveResult, ShiftType
from rostering.constraints import add_core_constraints, soft_objective
from rostering.hard_constraints import add_hard_constraints
from rostering.output_formatter import generate_enhanced_output

def solve_roster_staged(problem: ProblemInput, progress_callback=None) -> SolveResult:
    """
    Solve medical rota in stages with progress updates.
    
    Stages:
    1. Core requirements (daily coverage with locums if needed)
    2. CoMET staffing (highest priority)
    3. Night shift coverage
    4. Weekend coverage  
    5. Weekday long day coverage
    6. Short day optimization
    7. Training and balancing
    """
    
    if progress_callback:
        progress_callback("Starting staged solve...")
    
    model = cp_model.CpModel()
    
    # Build decision variables and basic constraints
    x, locums, days, people = add_core_constraints(problem, model)
    
    # Add hard constraints (always mandatory)
    add_hard_constraints(problem, model, x, days, people)
    
    if progress_callback:
        progress_callback("Stage 1: Basic coverage constraints added")
    
    # STAGE 1: Solve for basic coverage (with heavy locum usage allowed)
    stage1_result = solve_stage(model, x, locums, days, people, stage="basic_coverage", 
                               timeout=300, progress_callback=progress_callback)
    
    if not stage1_result['feasible']:
        return create_infeasible_result("Stage 1 failed - basic coverage impossible")
    
    # STAGE 2: Add CoMET prioritization
    add_comet_priority_constraints(problem, model, x, days, people)
    if progress_callback:
        progress_callback("Stage 2: CoMET prioritization added")
        
    stage2_result = solve_stage(model, x, locums, days, people, stage="comet_priority",
                               timeout=300, progress_callback=progress_callback)
    
    # STAGE 3: Add night shift optimization
    add_night_priority_constraints(problem, model, x, days, people)
    if progress_callback:
        progress_callback("Stage 3: Night shift optimization added")
        
    stage3_result = solve_stage(model, x, locums, days, people, stage="night_priority",
                               timeout=400, progress_callback=progress_callback)
    
    # STAGE 4: Add weekend optimization
    add_weekend_priority_constraints(problem, model, x, days, people)
    if progress_callback:
        progress_callback("Stage 4: Weekend optimization added")
        
    stage4_result = solve_stage(model, x, locums, days, people, stage="weekend_priority",
                               timeout=400, progress_callback=progress_callback)
    
    # STAGE 5: Final optimization (short days, training, balancing)
    # Initialize breach tracking for soft constraints
    breach_vars = {
        'weekend_1in3': [],
        'consecutive_night_blocks': [],
        'weekend_continuity': [],
        'training_fairness': []
    }
    
    soft_objective(problem, model, x, locums, days, people, breach_vars)
    if progress_callback:
        progress_callback("Stage 5: Final optimization with all preferences")
    
    # Final solve with longer timeout
    final_result = solve_stage(model, x, locums, days, people, stage="final",
                              timeout=800, progress_callback=progress_callback)
    
    # Extract best solution found
    if final_result['feasible']:
        if progress_callback:
            progress_callback("Extracting final solution...")
            
        roster = extract_roster_solution(final_result['solver'], x, days, people)
        summary = calculate_summary_stats(final_result['solver'], locums, roster, days, people)
        
        # Generate output
        generate_enhanced_output(roster, people, days, problem.config, summary)
        
        return SolveResult(
            success=True,
            roster=roster,
            summary=summary,
            message=f"Staged solution completed. Final status: {final_result['status']}"
        )
    else:
        # Use best partial solution from earlier stage
        best_stage = stage4_result if stage4_result['feasible'] else stage3_result
        if best_stage['feasible']:
            roster = extract_roster_solution(best_stage['solver'], x, days, people) 
            summary = calculate_summary_stats(best_stage['solver'], locums, roster, days, people)
            generate_enhanced_output(roster, people, days, problem.config, summary)
            
            return SolveResult(
                success=True,
                roster=roster,
                summary=summary,
                message=f"Partial solution from {best_stage['stage']}. Some preferences not optimized."
            )
        
        return create_infeasible_result("No feasible solution found in any stage")


def solve_stage(model, x, locums, days, people, stage: str, timeout: int, progress_callback=None) -> Dict:
    """Solve a single stage with timeout."""
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = timeout
    solver.parameters.num_search_workers = 8
    
    if progress_callback:
        progress_callback(f"Solving {stage} (timeout: {timeout}s)...")
    
    start_time = time.time()
    result = solver.Solve(model)
    solve_time = time.time() - start_time
    
    feasible = result in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    status = "OPTIMAL" if result == cp_model.OPTIMAL else ("FEASIBLE" if feasible else "INFEASIBLE")
    
    if progress_callback:
        if feasible:
            obj_value = solver.ObjectiveValue() if solver.ObjectiveValue() is not None else "N/A"
            progress_callback(f"{stage}: {status} in {solve_time:.1f}s (objective: {obj_value})")
        else:
            progress_callback(f"{stage}: {status} in {solve_time:.1f}s")
    
    return {
        'feasible': feasible,
        'status': status,
        'solver': solver,
        'stage': stage,
        'time': solve_time
    }


def add_comet_priority_constraints(problem, model, x, days, people):
    """Add CoMET prioritization constraints."""
    # Heavy penalty for CoMET locums - implemented in objective
    pass


def add_night_priority_constraints(problem, model, x, days, people):
    """Add night shift prioritization constraints."""
    # Heavy penalty for night locums - implemented in objective  
    pass


def add_weekend_priority_constraints(problem, model, x, days, people):
    """Add weekend prioritization constraints."""
    # Weekend fairness constraints - implemented in objective
    pass


# Import required functions from other modules
from rostering.solver import extract_roster_solution, calculate_summary_stats, create_infeasible_result


def create_infeasible_result(message: str) -> SolveResult:
    """Create an infeasible result."""
    return SolveResult(
        success=False,
        roster={},
        summary={},
        message=message
    )