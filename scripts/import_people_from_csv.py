import csv
import datetime as dt
from pathlib import Path
from rostering.models import Person
from app.storage import save_people

def parse_bool(s: str):
    s = (s or '').strip().lower()
    return s in ('1','true','yes','y')

def parse_optional_int(s: str):
    s = (s or '').strip()
    return int(s) if s else None

def parse_optional_date(s: str):
    s = (s or '').strip()
    if not s:
        return None
    return dt.date.fromisoformat(s)

def main():
    csv_path = Path('data/sample_people.csv')
    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")
    people: list[Person] = []
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            people.append(Person(
                id=row['id'].strip(),
                name=row['name'].strip(),
                grade=row['grade'].strip(),
                wte=float(row['wte']) if row['wte'] else 1.0,
                fixed_day_off=parse_optional_int(row.get('fixed_day_off','')),
                comet_eligible=parse_bool(row.get('comet_eligible','')),
                start_date=parse_optional_date(row.get('start_date','')),
            ))
    save_people(people)
    print(f"Imported {len(people)} people into storage.")

if __name__ == '__main__':
    main()
