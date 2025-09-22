from fastapi import FastAPI, Depends, Header, HTTPException, Request
import os
from pydantic import BaseModel
from rostering.solver import solve_roster
from rostering.models import ProblemInput, SolveResult
from rostering.models import Person, Config, Preassignment
from app.storage import load_people, save_people, get_person, load_preassignments, save_preassignments
import csv
import datetime as dt
from fastapi.responses import HTMLResponse, RedirectResponse
import pathlib
import threading
import time
import sys
from typing import Optional, List, Dict as _Dict

app = FastAPI(title="PICU Roster Optimizer")

class SolveRequest(BaseModel):
    problem: ProblemInput

class AdminSolveRequest(BaseModel):
    config: Config

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/")
def root(request: Request):
    # Always redirect to admin UI for convenience
    return RedirectResponse(url="/admin")

@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    p = pathlib.Path(__file__).with_name("admin.html")
    return HTMLResponse(p.read_text(encoding="utf-8"))

@app.post("/solve", response_model=SolveResult)
def solve(req: SolveRequest):
    try:
        return solve_roster(req.problem)
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        return SolveResult(
            success=False,
            message=f"Solve failed: {e}",
            roster={},
            breaches={},
            summary={
                "error": str(e),
                "traceback": tb,
            },
        )

# Optional admin protection
def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    required = os.getenv("ADMIN_API_KEY")
    if not required:
        return
    if x_api_key != required:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

# --- Admin People CRUD ---
@app.get("/admin/people", response_model=list[Person], dependencies=[Depends(require_api_key)])
def list_people():
    return load_people()

@app.get("/admin/people/{person_id}", response_model=Person, dependencies=[Depends(require_api_key)])
def read_person(person_id: str):
    p = get_person(person_id)
    if not p:
        raise HTTPException(status_code=404, detail="Person not found")
    return p

@app.post("/admin/people", response_model=Person, dependencies=[Depends(require_api_key)])
def create_person(person: Person):
    people = load_people()
    if any(p.id == person.id for p in people):
        raise HTTPException(status_code=409, detail="Person id already exists")
    people.append(person)
    save_people(people)
    return person

@app.put("/admin/people/{person_id}", response_model=Person, dependencies=[Depends(require_api_key)])
def update_person(person_id: str, person: Person):
    people = load_people()
    found = False
    for i, p in enumerate(people):
        if p.id == person_id:
            people[i] = person
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail="Person not found")
    save_people(people)
    return person

@app.delete("/admin/people/{person_id}", dependencies=[Depends(require_api_key)])
def delete_person(person_id: str):
    people = load_people()
    new_people = [p for p in people if p.id != person_id]
    if len(new_people) == len(people):
        raise HTTPException(status_code=404, detail="Person not found")
    save_people(new_people)
    return {"deleted": person_id}

@app.delete("/admin/people", dependencies=[Depends(require_api_key)])
def clear_people():
    save_people([])
    return {"cleared": True}

@app.post("/admin/people/import-sample", dependencies=[Depends(require_api_key)])
def import_sample_people():
    """Import people from data/sample_people.csv and merge by id (update or add)."""
    csv_path = pathlib.Path(__file__).parents[1] / "data" / "sample_people.csv"
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail="sample_people.csv not found")
    def parse_bool(s: str):
        s = (s or '').strip().lower()
        return s in ("1","true","yes","y")
    def parse_optional_int(s: str):
        s = (s or '').strip()
        return int(s) if s else None
    def parse_optional_date(s: str):
        s = (s or '').strip()
        return dt.date.fromisoformat(s) if s else None
    existing = {p.id: p for p in load_people()}
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = row['id'].strip()
            existing[pid] = Person(
                id=pid,
                name=row['name'].strip(),
                grade=row['grade'].strip(),
                wte=float(row['wte']) if row['wte'] else 1.0,
                fixed_day_off=parse_optional_int(row.get('fixed_day_off','')),
                comet_eligible=parse_bool(row.get('comet_eligible','')),
                start_date=parse_optional_date(row.get('start_date','')),
            )
    save_people(list(existing.values()))
    return {"imported": True, "count": len(existing)}

@app.post("/admin/solve", response_model=SolveResult, dependencies=[Depends(require_api_key)])
def admin_solve(req: AdminSolveRequest):
    try:
        people = load_people()
        pre = load_preassignments()
        problem = ProblemInput(people=people, config=req.config, preassignments=pre)
        return solve_roster(problem)
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        # Return a structured failure so the UI can display details
        return SolveResult(
            success=False,
            message=f"Solve failed: {e}",
            roster={},
            breaches={},
            summary={
                "error": str(e),
                "traceback": tb,
                "people_count": len(load_people()),
            },
        )

# ------------------ Async solve with progress ------------------
JobsLock = threading.Lock()
JOBS: _Dict[str, _Dict[str, object]] = {}

class _StreamTee:
    def __init__(self, job_id: str):
        self.job_id = job_id
    def write(self, data):
        s = str(data)
        if not s:
            return 0
        with JobsLock:
            job = JOBS.get(self.job_id)
            if job is None:
                return len(s)
            buf: List[str] = job.setdefault('log', [])  # type: ignore
            # Limit total log size
            if isinstance(buf, list):
                for line in s.splitlines():
                    if not line.strip():
                        continue
                    buf.append(line)
                if len(buf) > 1000:
                    del buf[:len(buf)-1000]
            job['last_log_at'] = time.time()
        return len(s)
    def flush(self):
        return

def _run_solve_job(job_id: str, problem: ProblemInput):
    start = time.time()
    with JobsLock:
        JOBS[job_id] = {"state": "running", "started_at": start, "log": []}
    # Tee stdout/stderr for progress capture
    old_out, old_err = sys.stdout, sys.stderr
    tee = _StreamTee(job_id)
    sys.stdout = tee  # type: ignore
    sys.stderr = tee  # type: ignore
    try:
        print("[job] building+solving...")
        # Ensure some progress logs if enabled
        os.environ.setdefault("SOLVER_PROGRESS", "1")
        res = solve_roster(problem)
        dur = time.time() - start
        with JobsLock:
            JOBS[job_id].update({"state": "completed", "duration": dur, "result": res.model_dump(mode="json")})
        print(f"[job] done in {dur:.1f}s")
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        with JobsLock:
            JOBS[job_id].update({"state": "failed", "error": str(e), "traceback": tb})
        print(f"[job] failed: {e}")
    finally:
        sys.stdout = old_out  # type: ignore
        sys.stderr = old_err  # type: ignore

class AsyncSolveRequest(BaseModel):
    config: Config

class AsyncSolveResponse(BaseModel):
    job_id: str

@app.post("/admin/solve-async", response_model=AsyncSolveResponse, dependencies=[Depends(require_api_key)])
def admin_solve_async(req: AsyncSolveRequest):
    people = load_people()
    pre = load_preassignments()
    problem = ProblemInput(people=people, config=req.config, preassignments=pre)
    job_id = f"job-{int(time.time()*1000)}"
    t = threading.Thread(target=_run_solve_job, args=(job_id, problem), daemon=True)
    t.start()
    return AsyncSolveResponse(job_id=job_id)

class AsyncSolveStatus(BaseModel):
    state: str
    duration: Optional[float] = None
    log: List[str] = []
    result: Optional[SolveResult] = None
    error: Optional[str] = None
    traceback: Optional[str] = None

@app.get("/admin/solve-status/{job_id}", response_model=AsyncSolveStatus, dependencies=[Depends(require_api_key)])
def admin_solve_status(job_id: str):
    with JobsLock:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Unknown job id")
        # Build response
        state = str(job.get('state'))
        dur = job.get('duration')
        log = list(job.get('log', []))
        result = job.get('result')
        error = job.get('error')
        tb = job.get('traceback')
    if result is not None:
        # Coerce back to SolveResult model for the response
        try:
            res = SolveResult.model_validate(result)
        except Exception:
            res = None
    else:
        res = None
    return AsyncSolveStatus(state=state, duration=dur, log=log, result=res, error=error, traceback=tb)

# --- Admin Preassignments CRUD ---
@app.get("/admin/preassignments", response_model=list[Preassignment], dependencies=[Depends(require_api_key)])
def list_preassignments():
    return load_preassignments()

@app.post("/admin/preassignments", response_model=Preassignment, dependencies=[Depends(require_api_key)])
def create_preassignment(item: Preassignment):
    # Upsert by (person_id, date)
    items = load_preassignments()
    new_items = [it for it in items if not (it.person_id == item.person_id and it.date == item.date)]
    new_items.append(item)
    save_preassignments(new_items)
    return item

@app.delete("/admin/preassignments", dependencies=[Depends(require_api_key)])
def clear_preassignments():
    save_preassignments([])
    return {"cleared": True}

@app.delete("/admin/preassignments/{person_id}/{date}", dependencies=[Depends(require_api_key)])
def delete_preassignment(person_id: str, date: str):
    # Remove preassignment matching person + date (ISO YYYY-MM-DD)
    try:
        d = dt.date.fromisoformat(date)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date format; expected YYYY-MM-DD")
    items = load_preassignments()
    new_items = [it for it in items if not (it.person_id == person_id and it.date == d)]
    if len(new_items) == len(items):
        # nothing removed, but treat as idempotent success
        return {"deleted": False}
    save_preassignments(new_items)
    return {"deleted": True}
