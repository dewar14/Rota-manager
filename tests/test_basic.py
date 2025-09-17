import datetime as dt
from rostering.models import Person, Config, ProblemInput
from rostering.solver import solve_roster

def test_smoke():
    people = [
        Person(id="r1", name="Reg1", grade="Registrar", wte=1.0, comet_eligible=True),
        Person(id="r2", name="Reg2", grade="Registrar", wte=1.0, comet_eligible=False),
        Person(id="s1", name="SHO1", grade="SHO", wte=1.0),
        Person(id="s2", name="SHO2", grade="SHO", wte=1.0),
    ]
    cfg = Config(
        start_date=dt.date(2025,2,5),
        end_date=dt.date(2025,2,12),
        bank_holidays=[],
        comet_on_weeks=[dt.date(2025,2,10)],
    )
    problem = ProblemInput(people=people, config=cfg)
    res = solve_roster(problem)
    assert res.success
