import datetime as dt
from app.storage import save_people, save_preassignments
from rostering.models import Person

# Build people from the provided snapshot
people: list[Person] = []

# Registrars R1..R11 with WTE and COMET eligibility
reg_info = [
    ("R1", 1.0, True, None, 13, 6),
    ("R2", 1.0, True, None, 13, 6),
    ("R3", 1.0, True, None, 13, 6),
    ("R4", 1.0, True, None, 13, 6),
    ("R5", 0.8, True, None, 11, 5),
    ("R6", 0.8, True, None, 11, 5),
    ("R7", 0.8, True, None, 11, 5),
    ("R8", 0.8, False, None, 11, 5),
    ("R9", 0.6, False, None, 9, 4),
    ("R10", 0.6, False, None, 9, 4),
    ("R11", 0.6, False, None, 9, 4),
]
for rid, wte, comet, start, al, cpd in reg_info:
    people.append(Person(
        id=rid.lower(), name=f"Registrar {rid[1:]}", grade="Registrar",
        wte=wte, comet_eligible=comet, start_date=start,
        fixed_day_off=None, annual_leave_days=al, cpd_entitlement=cpd
    ))

# SHOs S1..S7; S5 has start date 2026-04-06 per sheet
sho_info = [
    ("S1", 1.0, False, None, 13, 6),
    ("S2", 1.0, False, None, 13, 6),
    ("S3", 1.0, False, None, 13, 6),
    ("S4", 1.0, False, None, 13, 6),
    ("S5", 1.0, False, dt.date(2026,4,6), 13, 6),
    ("S6", 0.8, False, None, 11, 5),
    ("S7", 0.6, False, None, 9, 5),
]
for sid, wte, comet, start, al, cpd in sho_info:
    people.append(Person(
        id=sid, name=f"SHO {sid[1:]}", grade="SHO",
        wte=wte, comet_eligible=comet, start_date=start,
        fixed_day_off=None, annual_leave_days=al, cpd_entitlement=cpd
    ))

# Supernumeraries U1..U6
sup_info = [
    ("U1", 1.0), ("U2", 1.0), ("U3", 1.0), ("U4", 1.0), ("U5", 1.0), ("U6", 0.8)
]
for uid, wte in sup_info:
    people.append(Person(
        id=uid.lower(), name=f"Supernumerary {uid[1:]}", grade="Supernumerary",
        wte=wte, comet_eligible=False, start_date=None,
        fixed_day_off=None, annual_leave_days=None, cpd_entitlement=None
    ))

save_people(people)
save_preassignments([])
print(f"Seeded {len(people)} people from snapshot")
