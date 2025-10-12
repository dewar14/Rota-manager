from ortools.sat.python import cp_model
from typing import Dict
import pandas as pd
import json
import os
import time
from rostering.models import ProblemInput, SolveResult, ShiftType, SHIFT_DEFINITIONS
from rostering.constraints import add_core_constraints, soft_objective
from rostering.hard_constraints import add_hard_constraints
from rostering.firm_constraints import add_firm_constraints
from rostering.output_formatter import generate_enhanced_output

def solve_roster(problem: ProblemInput) -> SolveResult:
    """Main solver function with enhanced constraints and output."""
    
    model = cp_model.CpModel()
    
    # Build decision variables and basic constraints
    x, locums, days, people = add_core_constraints(problem, model)
    
    # Initialize breach tracking variables
    breach_vars = {
        'weekend_1in3': [],
        'consecutive_night_blocks': [],
        'weekend_continuity': [],
        'training_fairness': []
    }
    
    # Add hard constraints (must not be violated) 
    add_hard_constraints(problem, model, x, days, people)
    
    # Add firm constraints (high penalty if violated)
    add_firm_constraints(problem, model, x, days, people, breach_vars)
    
    # Add soft objective (preferences and optimization)
    soft_objective(problem, model, x, locums, days, people, breach_vars)
    
    # Solve with extended timeout for complex medical rotas
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 8
    
    # Extended timeout: 30 minutes for large medical rotas
    solver.parameters.max_time_in_seconds = 1800  # 30 minutes
    
    # Enable best solution mode - return best found even if not optimal
    solver.parameters.enumerate_all_solutions = False
    solver.parameters.cp_model_presolve = True
    solver.parameters.linearization_level = 2
    
    print(f"Solving roster for {len(people)} people over {len(days)} days...")
    print("Extended timeout: 30 minutes - will return best solution found...")
    print(f"Problem size: {solver.NumVariables() if hasattr(solver, 'NumVariables') else 'unknown'} variables")
    
    start_time = time.time()
    res = solver.Solve(model)
    solve_time = time.time() - start_time
    
    # Accept any solution found (OPTIMAL, FEASIBLE, or even partial)
    if res in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        status_msg = "OPTIMAL" if res == cp_model.OPTIMAL else "FEASIBLE (best found)"
        print(f"Solution found in {solve_time:.1f}s. Status: {status_msg}")
        
        try:
            obj_value = solver.ObjectiveValue()
            print(f"Objective value: {obj_value}")
        except Exception:
            print("Objective value: N/A")
        
        # Extract results even if not optimal
        roster = extract_roster_solution(solver, x, days, people)
        breaches = extract_breaches(solver, breach_vars)
        summary = calculate_summary_stats(solver, locums, roster, days, people)
        # Add detailed infeasibility analysis
        print(f"Solver failed with status: {solver.StatusName(res)}")
        print(f"Number of people: {len(people)}")
        print(f"Number of days: {len(days)}")
        print(f"Date range: {days[0]} to {days[-1]}")
        
        # Show people details
        for i, person in enumerate(people):
            print(f"Person {i}: {person.name} ({person.grade}, WTE {person.wte})")
        
        # Show what constraints were added
        print(f"Model has {model.Proto().constraints} constraints")
        print(f"Model has {len(model.Proto().variables)} variables")
        
        return SolveResult(
            success=False, 
            message=f"No feasible solution found. Status: {solver.StatusName(res)}. Check constraints: too few people ({len(people)}) for {len(days)} days, or constraints too strict.", 
            roster={}, 
            breaches={}, 
            summary={}
        )
    
    print(f"Solution found in {solver.WallTime():.2f}s. Status: {solver.StatusName(res)}")
    
    # Check if we actually have a solution to extract
    if res == cp_model.INFEASIBLE:
        return SolveResult(
            success=False, 
            message=f"Problem is infeasible. Status: {solver.StatusName(res)}. Try relaxing constraints or adding locum slots.", 
            roster={}, 
            breaches={}, 
            summary={}
        )
    
    # Extract solution
    roster = extract_roster_solution(solver, x, days, people)
    breaches = extract_breaches(solver, breach_vars)
    summary = calculate_summary_stats(solver, locums, roster, days, people)
    
    # Generate enhanced outputs
    result = SolveResult(
        success=True,
        message=f"Solved successfully ({solver.StatusName(res)})",
        roster=roster,
        breaches=breaches, 
        summary=summary
    )
    
    # Save outputs
    save_outputs(result, problem)
    
    return result


def extract_roster_solution(solver, x, days, people):
    """Extract roster assignments from solver solution."""
    roster = {}
    
    for d_idx, day in enumerate(days):
        date_key = day.isoformat()
        roster[date_key] = {}
        
        for p_idx, person in enumerate(people):
            assigned_shift = ShiftType.OFF  # default
            
            # Find which shift this person is assigned to on this day
            for shift in ShiftType:
                if (p_idx, d_idx, shift) in x and solver.Value(x[p_idx, d_idx, shift]) == 1:
                    assigned_shift = shift
                    break
            
            roster[date_key][person.id] = assigned_shift
    
    return roster


def extract_breaches(solver, breach_vars):
    """Extract constraint breaches from solver solution."""
    breaches = {}
    
    for constraint_type, vars_list in breach_vars.items():
        breaches[constraint_type] = []
        
        for var in vars_list:
            if solver.Value(var) == 1:
                breaches[constraint_type].append(f"Breach in {var.Name()}")
    
    return breaches


def calculate_summary_stats(solver, locums, roster, days, people):
    """Calculate summary statistics from solution."""
    summary = {}
    
    # Count total locum usage
    total_locums = 0
    for locum_type, var_list in locums.items():
        type_total = sum(solver.Value(var) for var in var_list)
        summary[f"locums_{locum_type}"] = float(type_total)
        total_locums += type_total
    
    summary["total_locum_slots"] = float(total_locums)
    
    # Calculate shift distribution
    shift_counts = {}
    for date_roster in roster.values():
        for person_id, shift in date_roster.items():
            if shift != ShiftType.OFF:
                shift_counts[shift] = shift_counts.get(shift, 0) + 1
    
    summary["shift_distribution"] = {str(k): float(v) for k, v in shift_counts.items()}
    
    # Calculate average utilization
    total_person_days = len(people) * len(days)
    working_assignments = sum(len([s for s in day_roster.values() if s != ShiftType.OFF]) 
                             for day_roster in roster.values())
    summary["utilization_rate"] = float(working_assignments / total_person_days) if total_person_days > 0 else 0.0
    
    return summary


def save_outputs(result: SolveResult, problem: ProblemInput):
    """Save solver outputs to files."""
    out_dir = "out"
    os.makedirs(out_dir, exist_ok=True)
    
    # Save basic CSV roster
    df = pd.DataFrame(result.roster).T  # Transpose so dates are rows
    df.to_csv(f"{out_dir}/roster.csv")
    
    # Save JSON outputs
    with open(f"{out_dir}/summary.json", "w") as f:
        json.dump(result.summary, f, indent=2, default=str)
    
    with open(f"{out_dir}/breaches.json", "w") as f:
        json.dump(result.breaches, f, indent=2, default=str)
    
    # Generate and save enhanced outputs
    try:
        enhanced = generate_enhanced_output(result, problem)
        
        # Save HTML version
        if "html" in enhanced.get("formatted_output", {}):
            with open(f"{out_dir}/roster.html", "w") as f:
                f.write(enhanced["formatted_output"]["html"])
        
        # Save enhanced CSV with statistics
        if "excel" in enhanced.get("formatted_output", {}):
            with open(f"{out_dir}/roster_detailed.csv", "w") as f:
                f.write(enhanced["formatted_output"]["excel"])
                
        print(f"Outputs saved to {out_dir}/ directory")
        
    except Exception as e:
        print(f"Warning: Could not generate enhanced outputs: {e}")
        # Continue with basic outputs
