from fastapi import FastAPI, Body
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from rostering.solver import solve_roster
from rostering.models import ProblemInput, SolveResult

app = FastAPI(title="PICU Roster Optimizer")

# Mount static files directory
app.mount("/static", StaticFiles(directory="app/static"), name="static")

class SolveRequest(BaseModel):
    problem: ProblemInput

@app.get("/")
def root():
    """Redirect to the medical roster UI."""
    return RedirectResponse(url="/static/medical_rota_ui.html")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/solve", response_model=SolveResult)
def solve(req: SolveRequest):
    return solve_roster(req.problem)

# Global sequential solver instance for stateful solving
sequential_solver_instance = None

@app.post('/solve_sequential')
async def solve_sequential_endpoint(payload: dict):
    """Start or continue sequential solving with admin checkpoints."""
    global sequential_solver_instance
    from rostering.sequential_solver import SequentialSolver
    
    try:
        stage = payload.get('stage', 'comet_nights')
        timeout = payload.get('timeout', 1800)  # 30 minutes per stage default
        
        # If starting fresh, create new solver instance
        if stage == 'comet_nights' or sequential_solver_instance is None:
            problem_raw = payload.get('problem') or payload
            problem = ProblemInput.parse_obj(problem_raw)
            sequential_solver_instance = SequentialSolver(problem)
        
        # Solve the requested stage
        result = sequential_solver_instance.solve_stage(stage, timeout_seconds=timeout)
        
        return {
            "success": result.success,
            "message": result.message,
            "stage": result.stage,
            "next_stage": getattr(result, 'next_stage', None),
            "partial_roster": result.partial_roster,
            "stats": getattr(result, 'stats', None)
        }
        
    except Exception as e:
        return {"success": False, "message": f"Error during sequential solve: {e}"}

@app.post('/check_constraints')
async def check_constraints_endpoint():
    """Check current roster for hard constraint violations and get alternatives."""
    global sequential_solver_instance
    
    if sequential_solver_instance is None:
        return {"success": False, "message": "No active roster to check. Start sequential solving first."}
    
    try:
        constraint_check = sequential_solver_instance.check_hard_constraints()
        
        return {
            "success": True,
            "message": "Constraint check completed",
            "violations": constraint_check['violations'],
            "alternatives": constraint_check['alternatives'],
            "summary": constraint_check['violation_summary']
        }
        
    except Exception as e:
        return {"success": False, "message": f"Error checking constraints: {e}"}

@app.post('/solve_with_checkpoints')
async def solve_with_checkpoints_endpoint(payload: dict):
    """Solve roster with admin checkpoints between stages (auto-continue mode for API)."""
    global sequential_solver_instance
    from rostering.sequential_solver import SequentialSolver
    
    try:
        problem_raw = payload.get('problem') or payload
        problem = ProblemInput.parse_obj(problem_raw)
        
        # Extract settings
        timeout_per_stage = payload.get('timeout_per_stage', 1800)
        auto_continue = payload.get('auto_continue', True)  # API defaults to auto-continue
        
        # Create solver instance
        sequential_solver_instance = SequentialSolver(problem)
        
        # Solve with checkpoints
        result = sequential_solver_instance.solve_with_checkpoints(
            timeout_per_stage=timeout_per_stage, 
            auto_continue=auto_continue
        )
        
        return {
            "success": result.success,
            "message": result.message,
            "stage": result.stage,
            "next_stage": getattr(result, 'next_stage', None),
            "partial_roster": result.partial_roster,
            "stats": getattr(result, 'stats', None)
        }
        
    except Exception as e:
        return {"success": False, "message": f"Error during checkpoint solve: {e}"}

@app.post('/solve_interactive')
async def solve_interactive_endpoint(payload: dict):
    """Interactive solving with stage-by-stage control."""
    global sequential_solver_instance
    from rostering.sequential_solver import SequentialSolver
    
    try:
        action = payload.get('action', 'start')  # start, continue, stats, violations, pause
        
        if action == 'start':
            # Initialize new solver
            problem_raw = payload.get('problem') or payload
            problem = ProblemInput.parse_obj(problem_raw)
            sequential_solver_instance = SequentialSolver(problem)
            
            # Start with first stage
            result = sequential_solver_instance.solve_stage('comet_nights', timeout_seconds=300)
            
            return {
                "success": result.success,
                "message": result.message,
                "stage": result.stage,
                "next_stage": getattr(result, 'next_stage', None),
                "action": "checkpoint",
                "partial_roster": result.partial_roster if result.success else None
            }
            
        elif action == 'continue' and sequential_solver_instance:
            # Continue to next stage
            next_stage = payload.get('next_stage', 'nights')
            result = sequential_solver_instance.solve_stage(next_stage, timeout_seconds=300)
            
            return {
                "success": result.success,
                "message": result.message,
                "stage": result.stage,
                "next_stage": getattr(result, 'next_stage', None),
                "action": "checkpoint" if getattr(result, 'next_stage', None) else "complete",
                "partial_roster": result.partial_roster if result.success else None
            }
            
        elif action == 'stats' and sequential_solver_instance:
            # Return current statistics
            sequential_solver_instance._show_detailed_statistics()
            return {"success": True, "message": "Statistics displayed in console", "action": "stats"}
            
        elif action == 'violations' and sequential_solver_instance:
            # Return constraint violations
            sequential_solver_instance._show_constraint_violations()
            return {"success": True, "message": "Violations displayed in console", "action": "violations"}
            
        else:
            return {"success": False, "message": f"Invalid action: {action}"}
            
    except Exception as e:
        return {"success": False, "message": f"Error during interactive solve: {e}"}

@app.get('/medical-rota')
def medical_rota_ui():
    """Comprehensive 6-month medical rota planning interface."""
    return HTMLResponse(open('app/static/medical_rota_ui.html').read())
