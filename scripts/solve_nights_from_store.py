import sys
import os
import datetime as dt
# Ensure repository root first
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)
from app.storage import load_people
from rostering.models import Config, ProblemInput
from rostering.solver import solve_nights_only

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('Usage: python scripts/solve_nights_from_store.py START_DATE END_DATE [COMET_MON1 COMET_MON2 ...]', file=sys.stderr)
        sys.exit(2)
    start = dt.date.fromisoformat(sys.argv[1])
    end = dt.date.fromisoformat(sys.argv[2])
    comet = [dt.date.fromisoformat(a) for a in sys.argv[3:]]
    people = load_people()
    cfg = Config(start_date=start, end_date=end, bank_holidays=[], comet_on_weeks=comet)
    problem = ProblemInput(people=people, config=cfg)
    res = solve_nights_only(problem)
    print(res.message, '| night locum slots:', res.summary.get('locum_slots'))
    print('Wrote out/roster_nights.csv')
