# PICU Roster Optimizer (FastAPI + OR-Tools)

Gold-standard web backend for generating compliant paediatric intensive care rosters for UK junior doctor rules.

## Stack
- Python 3.11
- [OR-Tools CP-SAT](https://developers.google.com/optimization) for constraints
- FastAPI for API
- PyTest for tests
- Devcontainer/Codespaces ready

## Quick start (local or Codespaces)
```bash
# create & activate venv (if local)
python -m venv .venv && source .venv/bin/activate

pip install -r requirements.txt

# run sample solve (small 14-day horizon)
python scripts/solve_sample.py

# run API
uvicorn app.main:app --reload
```

## Project layout
- `app/` FastAPI endpoints
- `rostering/` domain models and solver
- `data/` sample inputs
- `scripts/` helper CLIs
- `tests/` quick unit tests
- `.devcontainer/` Codespaces environment
- `.vscode/` tasks for convenience

## Inputs
- `data/sample_config.yml` — horizon, bank holidays, COMET weeks, weights
- `data/sample_people.csv` — clinicians with grade, WTE, fixed day-off, COMET eligibility

## Outputs
- `out/roster.csv` — wide CSV (Days × People)
- `out/breaches.json` — hard/soft breaches summary
- `out/summary.json` — stats/fairness/EWTD dashboard

## Notes
This scaffold enforces the **core hard constraints** and introduces **locum slack** variables so the model stays feasible. Several advanced constraints are stubbed with TODO markers and can be added incrementally.

See `rostering/constraints.py` for a checklist mapping your rules → exact constraints.
