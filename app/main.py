from fastapi import FastAPI, Body
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from rostering.solver import solve_roster
from rostering.models import ProblemInput, SolveResult

app = FastAPI(title="PICU Roster Optimizer")

class SolveRequest(BaseModel):
    problem: ProblemInput

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/solve", response_model=SolveResult)
def solve(req: SolveRequest):
    return solve_roster(req.problem)
