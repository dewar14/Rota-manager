from pydantic import BaseModel
from typing import List, Optional, Dict, Literal
import datetime as dt
from enum import Enum

Grade = Literal["SHO", "Registrar", "Supernumerary"]

class ShiftType(str, Enum):
    # Core operational shifts
    LONG_DAY_REG = "LD_REG"      # 13h 08:30-21:30 
    LONG_DAY_SHO = "LD_SHO"      # 13h 08:30-21:30
    NIGHT_REG = "N_REG"          # 13h 20:30-09:30
    NIGHT_SHO = "N_SHO"          # 13h 20:30-09:30
    COMET_DAY = "CMD"            # 12h 08:00-20:00
    COMET_NIGHT = "CMN"          # 12h 20:00-08:00
    SHORT_DAY = "SD"             # 9h 08:30-17:30
    
    # Educational/development
    CPD = "CPD"                  # 9h 08:30-17:30
    REG_TRAINING = "TREG"        # 9h 08:30-17:30
    SHO_TRAINING = "TSHO"        # 9h 08:30-17:30
    UNIT_TRAINING = "TUNIT"      # 9h 08:30-17:30
    INDUCTION = "IND"            # 9h 08:30-17:30
    
    # Leave/time off
    LEAVE = "LEAVE"              # 9h 08:30-17:30 (counts as worked)
    STUDY_LEAVE = "STUDY"        # 9h 08:30-17:30 (counts as worked)
    LTFT = "LTFT"                # Fixed day off (no hours)
    OFF = "OFF"                  # Day off (no hours)

# Shift definitions with hours, coverage counting, and restrictions
SHIFT_DEFINITIONS = {
    ShiftType.LONG_DAY_REG: {"hours": 13.0, "covers": True, "grade_req": "Registrar", "time": "08:30-21:30"},
    ShiftType.LONG_DAY_SHO: {"hours": 13.0, "covers": True, "grade_req": "SHO", "time": "08:30-21:30"},
    ShiftType.NIGHT_REG: {"hours": 13.0, "covers": True, "grade_req": "Registrar", "time": "20:30-09:30"},
    ShiftType.NIGHT_SHO: {"hours": 13.0, "covers": True, "grade_req": "SHO", "time": "20:30-09:30"},
    ShiftType.COMET_DAY: {"hours": 12.0, "covers": True, "grade_req": "Registrar", "time": "08:00-20:00", "comet_req": True},
    ShiftType.COMET_NIGHT: {"hours": 12.0, "covers": True, "grade_req": "Registrar", "time": "20:00-08:00", "comet_req": True},
    ShiftType.SHORT_DAY: {"hours": 9.0, "covers": True, "grade_req": None, "time": "08:30-17:30"},
    ShiftType.CPD: {"hours": 9.0, "covers": False, "grade_req": None, "time": "08:30-17:30"},
    ShiftType.REG_TRAINING: {"hours": 9.0, "covers": False, "grade_req": "Registrar", "time": "08:30-17:30"},
    ShiftType.SHO_TRAINING: {"hours": 9.0, "covers": False, "grade_req": "SHO", "time": "08:30-17:30"},
    ShiftType.UNIT_TRAINING: {"hours": 9.0, "covers": False, "grade_req": None, "time": "08:30-17:30"},
    ShiftType.INDUCTION: {"hours": 9.0, "covers": False, "grade_req": None, "time": "08:30-17:30"},
    ShiftType.LEAVE: {"hours": 9.0, "covers": False, "grade_req": None, "time": "08:30-17:30"},
    ShiftType.STUDY_LEAVE: {"hours": 9.0, "covers": False, "grade_req": None, "time": "08:30-17:30"},
    ShiftType.LTFT: {"hours": 0.0, "covers": False, "grade_req": None, "time": ""},
    ShiftType.OFF: {"hours": 0.0, "covers": False, "grade_req": None, "time": ""},
}

class Person(BaseModel):
    id: str
    name: str
    grade: Grade
    wte: float = 1.0
    fixed_day_off: Optional[int] = None  # 0=Mon .. 6=Sun for LTFT
    comet_eligible: bool = False
    start_date: Optional[dt.date] = None  # date they join (inclusive)
    end_date: Optional[dt.date] = None    # date they leave (inclusive)
    leave_allowance: int = 15  # days per 6 months (14/15/17 based on grade/contract)
    requested_leave: List[dt.date] = []  # pre-allocated leave requests
    
    # Historical fairness tracking (for 26-week periods)
    historical_long_days: int = 0    # Cumulative long days (including COMET)
    historical_nights: int = 0       # Cumulative nights (including COMET)  
    historical_weekends: int = 0     # Cumulative weekends worked

class Config(BaseModel):
    start_date: dt.date
    end_date: dt.date
    
    # Holiday/special day definitions
    bank_holidays: List[dt.date] = []
    school_holidays: List[dt.date] = []  # Nottinghamshire school holidays
    
    # CoMET weeks (Mondays marking start of alternate weeks)
    comet_on_weeks: List[dt.date] = []
    
    # Training day schedules
    registrar_training_days: List[dt.date] = []
    sho_training_days: List[dt.date] = []
    unit_training_days: List[dt.date] = []
    induction_days: List[dt.date] = []
    
    # Staffing targets
    max_day_clinicians: int = 5
    ideal_weekday_day_clinicians: int = 4
    min_weekday_day_clinicians: int = 3
    
    # Weekly hour targets
    min_weekly_hours: float = 42.0  # minimum average * WTE
    max_weekly_hours: float = 47.0  # maximum average * WTE
    
class ConstraintWeights(BaseModel):
    # Hard constraint penalties (very high to enforce)
    max_72h_violation: int = 10000
    weekend_frequency_violation: int = 10000
    night_rest_violation: int = 10000
    consecutive_limit_violation: int = 10000
    
    # Firm constraint penalties (high but may break)
    weekend_3in1_violation: int = 1000
    consecutive_night_blocks: int = 1000
    weekend_continuity: int = 500
    fairness_variance_15pct: int = 800
    training_fairness: int = 600
    
    # Preference penalties (lower, optimizable)
    weekend_day_staffing: int = 50
    night_preceded_by_short: int = 30
    night_block_size: int = 20
    long_day_singles: int = 15
    short_day_blocks: int = 10
    weekend_preparation: int = 25
    
    # Basic operational
    locum_usage: int = 1000
    understaffing: int = 500

class ProblemInput(BaseModel):
    people: List[Person]
    config: Config
    weights: ConstraintWeights = ConstraintWeights()

class SolveResult(BaseModel):
    model_config = {"arbitrary_types_allowed": True}
    
    success: bool
    message: str
    roster: Dict[str, Dict[str, str]]  # date -> person_id -> shift_code
    breaches: Dict[str, List[str]]  # constraint_type -> list of breach descriptions
    summary: dict  # statistics and metrics (allows any structure)
    
    # Enhanced outputs for tabulated view
    daily_staffing: Dict[str, int] = {}  # date -> total day clinicians
    doctor_stats: Dict[str, Dict[str, float]] = {}  # doctor_id -> stats (avg_hours, long_days, nights, weekends, etc.)
    constraint_violations: List[Dict[str, str]] = []  # detailed breach information with reasons

# Legacy compatibility
Weights = ConstraintWeights
