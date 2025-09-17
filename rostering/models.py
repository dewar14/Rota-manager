from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Literal
import datetime as dt

Grade = Literal["SHO", "Registrar", "Supernumerary"]

class Person(BaseModel):
    id: str
    name: str
    grade: Grade
    wte: float = 1.0
    fixed_day_off: Optional[int] = None  # 0=Mon .. 6=Sun
    comet_eligible: bool = False
    start_date: Optional[dt.date] = None  # date they join (inclusive)

class Shift(BaseModel):
    code: str             # e.g., SD, LD, N, CMD, CMN, CPD, TREG, TSHO, TPCCU, IND, OFF, LOCUM
    label: str
    hours: float
    count_in_cover: bool = True
    grade_requirement: Optional[Grade] = None  # if exactly one of this grade required (for LD/N etc.)

class Config(BaseModel):
    start_date: dt.date
    end_date: dt.date
    bank_holidays: List[dt.date] = []
    comet_on_weeks: List[dt.date] = []  # Mondays marking weeks to run COMET (both day & night), alternate blocks
    max_day_clinicians: int = 5
    ideal_weekday_day_clinicians: int = 4
    min_weekday_day_clinicians: int = 3

class Weights(BaseModel):
    locum: int = 1000
    single_night_penalty: int = 30
    fairness_variance: int = 5
    weekday_day_target_penalty: int = 1
    winter_extra_day_penalty: int = 2

class ProblemInput(BaseModel):
    people: List[Person]
    config: Config
    weights: Weights = Weights()

class SolveResult(BaseModel):
    success: bool
    message: str
    roster: Dict[str, Dict[str, str]]  # date -> person_id -> shift_code
    breaches: Dict[str, List[str]]
    summary: Dict[str, float]
