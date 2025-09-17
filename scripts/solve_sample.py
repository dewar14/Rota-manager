import yaml, pandas as pd, datetime as dt
from rostering.models import ProblemInput, Person, Config, Weights
from rostering.solver import solve_roster

with open("data/sample_config.yml") as f:
    cfg = yaml.safe_load(f)
config = Config(
    start_date=dt.date.fromisoformat(str(cfg["start_date"])[:10]),
    end_date=dt.date.fromisoformat(str(cfg["end_date"])[:10]),
    bank_holidays=[dt.date.fromisoformat(str(d)[:10]) for d in cfg.get("bank_holidays",[])],
    comet_on_weeks=[dt.date.fromisoformat(str(d)[:10]) for d in cfg.get("comet_on_weeks",[])],
    max_day_clinicians=cfg.get("max_day_clinicians",5),
    ideal_weekday_day_clinicians=cfg.get("ideal_weekday_day_clinicians",4),
    min_weekday_day_clinicians=cfg.get("min_weekday_day_clinicians",3),
)

df = pd.read_csv("data/sample_people.csv")
people = []
for _,r in df.iterrows():
    sd = None
    if isinstance(r.get("start_date"), str) and r.get("start_date"):
        sd = dt.date.fromisoformat(r["start_date"])
    fdo = None
    if not pd.isna(r.get("fixed_day_off")):
        try:
            fdo = int(r["fixed_day_off"])
        except Exception:
            fdo = None
    people.append(Person(
        id=r["id"], name=r["name"], grade=r["grade"],
        wte=float(r["wte"]), fixed_day_off=fdo,
        comet_eligible=bool(r["comet_eligible"]) if str(r["comet_eligible"]).lower() not in ["true","false"] else str(r["comet_eligible"]).lower()=="true",
        start_date=sd
    ))

problem = ProblemInput(people=people, config=config)
res = solve_roster(problem)
print(res.message, "| locum slots:", res.summary.get("locum_slots"))
