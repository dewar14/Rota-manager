import os
import os
import json
from typing import List, Optional
import tempfile
from rostering.models import Person, Preassignment

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
PEOPLE_PATH = os.path.join(DATA_DIR, "people.json")
PREASSIGN_PATH = os.path.join(DATA_DIR, "preassignments.json")


def _ensure_storage():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(PEOPLE_PATH):
        with open(PEOPLE_PATH, "w") as f:
            json.dump([], f)
    if not os.path.exists(PREASSIGN_PATH):
        with open(PREASSIGN_PATH, "w") as f:
            json.dump([], f)


def load_people() -> List[Person]:
    _ensure_storage()
    with open(PEOPLE_PATH) as f:
        raw = json.load(f)
    return [Person.model_validate(p) for p in raw]


def _atomic_write(path: str, data: str) -> None:
    dir_name = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as tmp:
            tmp.write(data)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def save_people(people: List[Person]) -> None:
    _ensure_storage()
    payload = json.dumps([p.model_dump(mode="json") for p in people], indent=2)
    _atomic_write(PEOPLE_PATH, payload)


def get_person(person_id: str) -> Optional[Person]:
    for p in load_people():
        if p.id == person_id:
            return p
    return None

def load_preassignments() -> List[Preassignment]:
    _ensure_storage()
    with open(PREASSIGN_PATH) as f:
        raw = json.load(f)
    return [Preassignment.model_validate(p) for p in raw]

def save_preassignments(items: List[Preassignment]) -> None:
    _ensure_storage()
    payload = json.dumps([p.model_dump(mode="json") for p in items], indent=2)
    _atomic_write(PREASSIGN_PATH, payload)