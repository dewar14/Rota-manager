from pydantic import BaseModel
from typing import List, Optional, Dict, Literal, Any
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
    # Entitlements (admin editable)
    annual_leave_days: Optional[int] = None
    cpd_entitlement: Optional[int] = None  # per 6 months

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
    global_induction_days: List[dt.date] = []
    global_registrar_teaching_days: List[dt.date] = []
    global_sho_teaching_days: List[dt.date] = []
    global_unit_teaching_days: List[dt.date] = []

class Weights(BaseModel):
    locum: int = 5000  # Significantly increased but not excessive
    single_night_penalty: int = 30
    fairness_variance: int = 20
    fairness_band_penalty: int = 15
    weekday_day_target_penalty: int = 4
    winter_extra_day_penalty: int = 2
    weekend_split_penalty: int = 25  # Moderate increase
    preassign_violation: int = 200
    fdo_violation: int = 50
    min_weekly_hours_penalty: int = 5
    max_weekly_hours_penalty: int = 4
    weekend_continuity_bonus: int = 5
    nights_pref_sd_before_bonus: int = 5
    nights_crossover_bonus: int = 3
    comet_ldn_share_factor: float = 0.8  # eligible registrars expected share multiplier for LD/N
    # Simplified weights for sequence penalties
    shift_switch_penalty: int = 8   # Moderate penalty for switching
    consecutive_ld_bonus: int = 4   # Moderate bonus for consecutive LD days
    night_block_bonus: int = 6      # Moderate bonus for proper night blocks

class Preassignment(BaseModel):
    person_id: str
    date: dt.date
    shift_code: str

class ProblemInput(BaseModel):
    people: List[Person]
    config: Config
    weights: Weights = Weights()
    preassignments: List[Preassignment] = []

class SolveResult(BaseModel):
    success: bool
    message: str
    roster: Dict[str, Dict[str, str]]  # date -> person_id -> shift_code
    breaches: Dict[str, List[str]]
    summary: Dict[str, Any]
