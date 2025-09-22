import sys
import datetime as dt
import os

# Ensure repository root on sys.path BEFORE importing local packages
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from app.storage import load_people, load_preassignments
from rostering.models import Config, ProblemInput
from rostering.solver import solve_roster

def parse_date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)

def main():
    if len(sys.argv) < 3:
        print("Usage: python scripts/solve_from_store.py START_DATE END_DATE [COMET_MON1 COMET_MON2 ...]", file=sys.stderr)
        print("Example: python scripts/solve_from_store.py 2026-02-04 2026-02-18 2026-02-09", file=sys.stderr)
        sys.exit(2)
    start = parse_date(sys.argv[1])
    end = parse_date(sys.argv[2])
    comet_mondays = [parse_date(a) for a in sys.argv[3:]]

    people = load_people()
    pre = load_preassignments()
    cfg = Config(
        start_date=start,
        end_date=end,
        bank_holidays=[],
        comet_on_weeks=comet_mondays,
    )
    problem = ProblemInput(people=people, config=cfg, preassignments=pre)
    res = solve_roster(problem)
    print(res.message, "locum:", res.summary.get("locum_slots"))

if __name__ == "__main__":
    main()
