# PICU Roster Optimizer (FastAPI + OR-Tools)

Gold-standard web backend for generating compliant paediatric intensive care rosters for UK junior doctor rules.

## Stack
- Python 3.11
- [OR-Tools CP-SAT](https://developers.google.com/optimization) for constraints
- FastAPI for API
- PyTest for tests
- Devcontainer/Codespaces ready

## Quick start (local or Codespaces)
```bash
# create & activate venv (if local)
python -m venv .venv && source .venv/bin/activate

pip install -r requirements.txt

# run sample solve (small 14-day horizon)
python scripts/solve_sample.py

# run API server (auto-starts in Codespaces)
uvicorn app.main:app --reload

# or use VS Code tasks:
# - "Auto-Start Medical Rota Server" (runs on folder open)
# - "Restart Server" (manual restart)
```

## Project layout
- `app/` FastAPI endpoints
- `rostering/` domain models and solver
- `data/` sample inputs (6-month medical_rota_6month.yml is main config)
- `scripts/` helper CLIs
- `tests/` quick unit tests
- `.devcontainer/` Codespaces environment
- `.vscode/` tasks for convenience

## Inputs
- `data/medical_rota_6month.yml` — 6-month horizon (Feb-Aug 2026), bank holidays, COMET weeks, doctor details with WTE/availability/leave
- `data/sample_config.yml` — smaller test config
- `data/sample_people.csv` — legacy CSV format (now using YAML)

## Outputs
- `out/roster.csv` — wide CSV (Days × People)
- `out/breaches.json` — hard/soft breaches summary
- `out/summary.json` — stats/fairness/EWTD dashboard

---

## Solver Purpose & Methodology

### Objective
Generate a **6-month medical roster** (Feb-Aug 2026, 181 days) for 11 junior doctors across a Paediatric Intensive Care Unit (PICU), ensuring:
1. **Complete coverage** for all required shifts (nights, weekends, days)
2. **Hard constraint compliance** (rest periods, consecutive shift limits, availability)
3. **Fair distribution** of undesirable shifts (nights, weekends) across all doctors
4. **Preference optimization** where possible (block preferences, day-off requests)

### Sequential Solving Approach
The solver uses a **6-stage sequential optimization** strategy (implemented in `rostering/sequential_solver.py`):

#### Stage 1: COMET Nights Assignment
- **COMET weeks**: Pre-scheduled 2-week blocks where 2 doctors work night rotations
- **Pattern**: Monday-Thursday (4 nights) + Friday-Sunday (3 nights) per week
- **Eligibility**: 8 doctors eligible for COMET (trainee registrars only)
- **Method**: Deterministic assignment with fairness rotation
- **Output**: 91 COMET night shifts assigned across 13 two-week blocks

#### Stage 2: Unit Nights Assignment  
- **Coverage**: All remaining nights not covered by COMET (90 additional nights)
- **Pattern**: Flexible 3-4 night blocks with hard rest gap enforcement
- **Eligibility**: All 11 doctors (registrars + SHOs)
- **Method**: CP-SAT optimization with hard gap constraints (7-day minimum between blocks)
- **Key Feature**: Full-period optimization (181 days in single solve) for perfect gap detection
- **Locum Handling**: Identifies nights with zero eligible doctors, flags for external locum coverage

#### Stage 3: Weekend/Holiday Working
- **Coverage**: Long day shifts on weekends and bank holidays
- **Pattern**: Saturday + Sunday pairs (continuity preferred)
- **Method**: CP-SAT with MinMax fairness optimization
- **Constraints**: Minimum weekend requirements (50% COMET doctors, 70% Unit doctors)
- **Output**: Balanced weekend distribution ensuring everyone shares burden

#### Stage 4: COMET Day Shifts
- **Coverage**: Weekday long days during COMET weeks
- **Eligibility**: COMET-eligible doctors only
- **Method**: Greedy assignment with gap checking

#### Stage 5: Weekday Long Days
- **Coverage**: Remaining Monday-Friday long day shifts
- **Eligibility**: All registrars
- **Method**: Greedy assignment with preference consideration

#### Stage 6: Short Day Shifts
- **Coverage**: Fill remaining day shift requirements
- **Eligibility**: All doctors
- **Method**: Greedy assignment

Each stage builds upon the previous stage's assignments stored in `partial_roster`, ensuring cross-stage constraint awareness.

---

## Hard Constraints (MUST be respected)

These are **absolute requirements** enforced primarily in CP-SAT stages (Nights, Weekends):

### 1. Coverage Requirements
- **Every night shift MUST have coverage** (1 doctor for COMET nights, 1+ for Unit nights)
- **Every weekend MUST have coverage** (sufficient long day shifts on Sat/Sun)
- If coverage impossible due to constraints → Flag as **LOCUM GAP** (requires external locum)

### 2. Rest Period Constraints
- **46-Hour Minimum Rest**: Minimum 46 hours (2 full days) rest between shift blocks
- **7-Day Gap Between Night Blocks**: Minimum 7 full rest days between the END of one night block and the START of another night block
  - Important: Day shifts are allowed after 46 hours (2 days)
  - Night shifts blocked for full 7 days after night block ends
  - This prevents rapid night → night rotations while allowing day work

### 3. Consecutive Shift Limits
- **Maximum 4 consecutive night shifts** per block
- **Maximum 4 consecutive long days** per block
- Night blocks typically: 3-4 nights, then mandatory rest

### 4. Availability & Leave Constraints
- **Respect leave periods**: No assignments during marked leave
- **Respect availability**: Doctors only assigned when available (from YAML config)
- **Fixed day off**: If specified (e.g., "every Tuesday off"), must be honored

### 5. Weekly Hour Limits
- **72-Hour Weekly Maximum**: No more than 72 hours worked in any rolling 7-day window
  - Currently enforced post-solve for large rosters (>100 days)
  - For smaller rosters (<100 days), enforced in CP-SAT model
  - Night shift = 13 hours, Long day = 13 hours, Short day = 8 hours

### 6. COMET Eligibility
- **Only trainee registrars** can work COMET night weeks
- **SHO-grade doctors** excluded from COMET rotations
- Enforced by grade checking in configuration

---

## Preferences (Should be prioritized)

These are **soft constraints** optimized where possible without violating hard constraints:

### 1. Fairness Optimization (Highest Priority)
- **Equal night shift distribution**: MinMax optimization to minimize max-min gap
- **Weekend fairness**: Everyone should work similar number of weekends
- **WTE-adjusted fairness**: Part-time doctors (0.6 WTE, 0.8 WTE) get proportionally fewer undesirable shifts
- **Cumulative fairness**: Track running totals across entire 6-month period

### 2. Block Preferences
- **Preferred block lengths**: Some doctors prefer 3-night vs 4-night blocks
- **Spacing bonuses**: Reward better distribution of shifts across roster period
- **Continuity**: Prefer Saturday+Sunday weekend pairs over isolated days

### 3. Pattern Quality
- **Avoid clustered shifts**: Spread shifts evenly rather than bunching
- **Block boundary awareness**: Avoid assignments immediately after previous block
- **Weekend continuity**: Keep Sat/Sun together where possible

### 4. Day-Off Requests
- **Fixed weekly day off**: Honor if specified (e.g., "every Tuesday")
- **Specific date requests**: Accommodate where possible without constraint violation

---

## Recent Changes (November 2025)

### Critical Bug Fixes
1. **Fixed locum gap return flow** (Lines 1645-1670, 2155-2221, 2395-2425)
   - **Problem**: `_assign_unit_night_blocks_with_cpsat` always returned `True` regardless of solve success
   - **Result**: Solver continued with empty roster when locum gaps prevented assignment
   - **Fix**: Return actual solve result; stage handler checks `self.last_locum_gaps` to distinguish locum gaps from true failure
   - **Behavior**: Now continues with warning when locum gaps identified, fails only if over-constrained

2. **Fixed 72-hour constraint performance** (Lines 2047-2098)
   - **Problem**: 72-hour weekly maximum constraint created ~1,925 expressions for 181-day roster, causing solver to hang
   - **Fix**: Skip constraint for rosters >100 days during model building; validate post-solve instead
   - **Result**: Solver proceeds past model building stage for large rosters

### Constraint Improvements
3. **Unified constraint checking** (Lines 115-310)
   - Added helper functions for consistent constraint checking across all stages:
     - `_check_7day_gap_to_next_night_block()`: Unified gap checking with night vs day distinction
     - `_check_72hour_weekly_maximum()`: Rolling 7-day window hour checking
     - `_check_all_constraints_for_shift()`: Single entry point for all constraint validation
   - Improves consistency and reduces code duplication

4. **Clarified 7-day gap rule semantics**
   - Gap is from **END of night block** to **START of next night block**
   - Day shifts allowed after 46 hours (2 days)
   - Night shifts blocked for full 7 days
   - Implementation: Lines 164-193 distinguish `proposed_shift_is_night` parameter

5. **Weekend fairness fixes**
   - Added minimum weekend constraints (50% COMET, 70% Unit doctors)
   - Fixed issue where doctors with high availability got zero weekends
   - MinMax optimization ensures fair distribution

### Documentation Added
6. **HARD_CONSTRAINTS_ANALYSIS.md** (~700 lines)
   - Comprehensive technical documentation of all constraints
   - Includes code examples, enforcement details, cross-stage analysis
   - Recommendations for future improvements

7. **CONSTRAINT_IMPROVEMENTS_SUMMARY.md** (~400 lines)
   - User-friendly summary of recent changes
   - Testing guide and impact assessment
   - Configuration recommendations

### Known Issues
- **72-hour weekly max**: Currently skipped in CP-SAT for large rosters, validated post-solve
  - Should be added to weekend/day stages using unified helper functions
  - Performance optimization needed for large-scale enforcement
  
- **Locum gap handling**: Works but needs UI integration
  - Gaps correctly identified and logged
  - Final roster should clearly indicate which nights need external locums
  - Admin workflow needs definition

### Performance Notes
- **Full-period optimization**: Unit Nights processes entire 181 days in single CP-SAT solve
  - Benefits: Perfect gap detection, global optimization, no chunk boundary issues
  - Cost: 2-5 minute solve time with 300s timeout
  - 5% relative gap stopping criterion balances speed vs optimality

### File Locations
- Main solver: `rostering/sequential_solver.py` (4479 lines)
- Constraint checker: `rostering/constraint_violations.py`
- API endpoints: `app/main.py`
- Main configuration: `data/medical_rota_6month.yml`
- Server log: `/workspaces/Rota-manager/server.log` (for debugging)

---

## Development Tips

### Debugging
- Check `server.log` for detailed solver output
- Use `grep` to filter: `tail -200 server.log | grep "LOCUM\|INFEASIBLE"`
- CP-SAT outputs detailed constraint violation info when infeasible

### Testing
- Run PyTest: `pytest -q`
- Run specific test: `pytest tests/test_basic.py -v`
- Test constraint checker: `python test_constraints.py`

### Common Commands
```bash
# Restart server
./start_dev_server.sh

# Check server status
./check_server.sh

# Run sample solve
python scripts/solve_sample.py

# Analyze rota
python analyze_comet_assignments.py
```
