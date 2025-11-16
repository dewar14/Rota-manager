#!/usr/bin/env python3
"""Quick test of fairness optimization in Unit Nights stage"""

import yaml, pandas as pd, datetime as dt, sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rostering.models import ProblemInput, Person, Config, ConstraintWeights
from rostering.sequential_solver import SequentialSolver

# Load config
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

# Load people
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

problem = ProblemInput(people=people, config=config, weights=ConstraintWeights())

print(f"Testing fairness optimization for {len(people)} people over {(config.end_date - config.start_date).days + 1} days...")
print("\n" + "="*80)
print("STAGE 1: COMET NIGHTS")
print("="*80)

solver = SequentialSolver(problem, historical_comet_counts=None)
comet_result = solver.solve_stage("comet", timeout_seconds=60)

if not comet_result.success:
    print(f"❌ COMET stage failed: {comet_result.message}")
    sys.exit(1)

print(f"✅ {comet_result.message}")

# Show COMET distribution by WTE
comet_by_wte = {}
for person in people:
    if person.comet_eligible:
        count = sum(1 for day_str, assignments in comet_result.partial_roster.items() 
                   if assignments[person.id] == 'CMN')
        comet_by_wte[person.name] = {
            'wte': person.wte,
            'comet_nights': count
        }

print("\nCOMET Night Distribution:")
for name in sorted(comet_by_wte.keys(), key=lambda n: (comet_by_wte[n]['wte'], n), reverse=True):
    info = comet_by_wte[name]
    print(f"  {name:20} (WTE {info['wte']:.1f}): {info['comet_nights']:2d} COMET nights")

print("\n" + "="*80)
print("STAGE 2: UNIT NIGHTS (with FAIRNESS FIX)")
print("="*80)
print("⚖️  Fairness weight: -200,000 (dominates block/weekend bonuses)")
print("✅ 1.0 WTE doctors should get MOST unit nights")
print("✅ 0.6 WTE doctors should get proportionally fewer")
print()

unit_result = solver.solve_stage("nights", timeout_seconds=180)

if not unit_result.success:
    print(f"❌ Unit Nights stage failed: {unit_result.message}")
    sys.exit(1)

print(f"\n✅ {unit_result.message}")

# Count unit nights by WTE
unit_by_wte = {}
for person in people:
    comet_count = comet_by_wte.get(person.name, {}).get('comet_nights', 0)
    unit_count = sum(1 for day_str, assignments in unit_result.partial_roster.items() 
                    if assignments[person.id] in ['N_REG', 'N_SHO'])
    total_nights = comet_count + unit_count
    
    unit_by_wte[person.name] = {
        'wte': person.wte,
        'comet': comet_count,
        'unit': unit_count,
        'total': total_nights,
        'wte_adjusted': total_nights / person.wte if person.wte > 0 else 0
    }

print("\n" + "="*80)
print("FINAL NIGHT DISTRIBUTION (COMET + Unit)")
print("="*80)
print(f"{'Doctor':<20} {'WTE':>5} {'COMET':>6} {'Unit':>6} {'Total':>6} {'Per WTE':>8}")
print("-"*80)

for name in sorted(unit_by_wte.keys(), key=lambda n: (unit_by_wte[n]['wte'], n), reverse=True):
    info = unit_by_wte[name]
    print(f"{name:<20} {info['wte']:5.1f} {info['comet']:6d} {info['unit']:6d} {info['total']:6d} {info['wte_adjusted']:8.1f}")

# Check fairness
print("\n" + "="*80)
print("FAIRNESS CHECK")
print("="*80)

wte_1_0 = [info for info in unit_by_wte.values() if info['wte'] == 1.0]
wte_0_8 = [info for info in unit_by_wte.values() if info['wte'] == 0.8]
wte_0_6 = [info for info in unit_by_wte.values() if info['wte'] == 0.6]

if wte_1_0:
    avg_1_0 = sum(d['total'] for d in wte_1_0) / len(wte_1_0)
    print(f"1.0 WTE doctors (n={len(wte_1_0)}): avg {avg_1_0:.1f} total nights")
    
if wte_0_8:
    avg_0_8 = sum(d['total'] for d in wte_0_8) / len(wte_0_8)
    print(f"0.8 WTE doctors (n={len(wte_0_8)}): avg {avg_0_8:.1f} total nights")
    
if wte_0_6:
    avg_0_6 = sum(d['total'] for d in wte_0_6) / len(wte_0_6)
    print(f"0.6 WTE doctors (n={len(wte_0_6)}): avg {avg_0_6:.1f} total nights")

if wte_1_0 and wte_0_8:
    ratio = avg_1_0 / avg_0_8 if avg_0_8 > 0 else 0
    expected_ratio = 1.0 / 0.8
    print(f"\n1.0 WTE / 0.8 WTE ratio: {ratio:.2f} (expected: {expected_ratio:.2f})")
    if abs(ratio - expected_ratio) < 0.2:
        print("✅ PASS: Ratio is reasonable")
    else:
        print("⚠️  WARNING: Ratio deviates from expected")

print("\n" + "="*80)
print("TEST COMPLETE")
print("="*80)
