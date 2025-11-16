# Medical Rota Solver - Complete Context Document

**Last Updated:** 2024-10-29  
**Version:** 1.0  
**Status:** Core constraints implemented, optimizations in progress

---

## Table of Contents
1. [Overview](#overview)
2. [Hard Constraints](#hard-constraints)
3. [Soft Constraints & Preferences](#soft-constraints--preferences)
4. [Solver Architecture](#solver-architecture)
5. [Implementation Status](#implementation-status)
6. [Known Issues & Future Work](#known-issues--future-work)
7. [Testing & Verification](#testing--verification)

---

## Overview

### Purpose
The Medical Rota Solver generates fair and compliant rotas (schedules) for medical registrars in a hospital setting. It must balance:
- **Legal/safety requirements** (rest periods, working time regulations)
- **Clinical coverage needs** (ensure all shifts are covered)
- **Fairness** (distribute workload equitably across doctors)
- **Individual constraints** (leave, training requirements, part-time working)

### Key Shift Types
1. **COMET Nights (CMN)** - Acute medicine night shifts during designated "COMET weeks"
2. **COMET Days (CMD)** - Acute medicine day shifts during COMET weeks
3. **Unit Night Shifts** - Regular on-call nights outside COMET weeks:
   - **N_REG** - Registrar-level night shifts
   - **N_SHO** - Senior House Officer-level night shifts
4. **Day Shifts** - Regular day work on specific units/wards
5. **Leave** - Annual leave, study leave, sick leave
6. **OFF** - Rest days

### Eligibility Rules
- **COMET eligible**: Only registrars can do COMET shifts (not SHOs)
- **Night shift eligible**: Based on role and experience level
- **WTE (Whole Time Equivalent)**: Part-time doctors (WTE < 1.0) work proportionally fewer shifts

---

## Hard Constraints

These **MUST** be satisfied for a valid rota. Violations are unacceptable.

### 1. Rest Period Requirements (46-Hour Rule)
**Rule**: After completing a night block (2+ consecutive night shifts), a doctor must have **2 FULL rest days** before working again.

**Implementation Details**:
- If a night block ends on day D:
  - D+1 = Rest day 1
  - D+2 = Rest day 2  
  - D+3 = Can work again
- A "block" is defined as 2+ consecutive night shifts
- Single night shifts (isolated nights) are not considered blocks
- **Must check BOTH directions**:
  - **Backward**: Don't assign if previous block ended ≤1 day ago
  - **Forward**: Don't assign if it would end too close to an upcoming block
  
**Current Status**: ✅ **FULLY IMPLEMENTED AND VERIFIED**
- Backward checking: `days_since <= 1` prevents work too soon after previous block
- Forward checking within chunks: CP-SAT constraint enforces rest on d+2
- Forward checking for COMET blocks: Prevents unit nights being assigned too close to upcoming COMET blocks
- **Verified**: Zero rest violations in test runs

### 2. Leave Constraints
**Rule**: If a doctor has leave booked:
- They cannot be assigned ANY shifts on those days
- Leave is pre-assigned in the roster
- Types: Annual leave, study leave, sick leave

**Current Status**: ✅ Implemented via `_is_available()` checks

### 3. Coverage Requirements
**Rule**: Every shift that needs coverage MUST be filled.
- **COMET weeks**: All 7 nights in each COMET week must be covered
- **Unit nights**: All non-COMET nights need either N_REG or N_SHO coverage
- Cannot leave gaps in the rota

**Current Status**: ✅ Implemented and verified
- COMET nights: 100% coverage achieved
- Unit nights: 100% coverage achieved (181/181 shifts)

### 4. Block Formation Rules
**Rule**: Night shifts should form contiguous blocks of 2-4 nights.
- **Minimum**: 2 consecutive nights (no isolated single nights)
- **Maximum**: 4 consecutive nights (no 5+ night marathons)
- **Exception**: Final night of a chunk can be standalone if necessary

**Current Status**: ✅ Implemented via CP-SAT constraints
- Prevents 5+ night blocks
- Strongly discourages single isolated nights (penalties applied)
- Verified: Blocks are {2, 3, 4} nights only

### 5. Eligibility Constraints
**Rule**: Only eligible doctors can be assigned to specific shift types.
- COMET shifts → Only COMET-eligible registrars
- Night shifts → Only night-shift eligible doctors
- Role-specific shifts → Must match doctor's role/grade

**Current Status**: ✅ Implemented via eligibility filtering

### 6. WTE-Adjusted Workload
**Rule**: Part-time doctors should work proportionally to their WTE.
- 0.8 WTE → 80% of full-time workload
- Applies to all shift types (nights, days, weekends)

**Current Status**: ✅ Implemented via WTE-adjusted targets

---

## Soft Constraints & Preferences

These are **goals** the solver tries to achieve but can compromise on if necessary.

### 1. Fairness & Equity
**Goal**: Distribute workload evenly across all eligible doctors.
- **Primary metric**: Cumulative deviation from target assignments
- **Target calculation**: Total shifts ÷ Total WTE-adjusted eligible doctors
- **Tracking**: Running totals updated after each assignment

**Priority**: HIGH  
**Current Status**: ✅ Implemented via cumulative fairness scoring

### 2. Block Patterns (COMET Weeks)
**Goal**: Prefer specific coverage patterns for COMET weeks.
- **Optimal**: 4+3 nights (one doctor does 4, another does 3) or 3+4
- **Good**: 2+2+3 nights (three doctors split the week)
- **Avoid**: Multiple small blocks or singleton nights

**Priority**: MEDIUM  
**Current Status**: ✅ Implemented via CP-SAT objective function
- 4+3 patterns: Heavily rewarded
- 2+2+3 patterns: Moderately rewarded
- Singletons: Heavily penalized

### 3. Weekend Distribution
**Goal**: Distribute weekend shifts fairly.
- Track weekend days separately
- Avoid giving same doctor too many weekends

**Priority**: MEDIUM  
**Current Status**: ⚠️ Partially implemented (tracking exists, not yet optimized)

### 4. Consecutive Block Spacing
**Goal**: Space out night blocks for same doctor.
- Avoid assigning same doctor to back-to-back COMET weeks
- Give doctors recovery time between intense periods

**Priority**: LOW  
**Current Status**: ⚠️ Not yet implemented

---

## Solver Architecture

### Sequential Multi-Stage Approach
The solver runs in **sequential stages** rather than solving everything simultaneously. This improves scalability and allows prioritization.

```
Stage 1: COMET Nights (CMN) → Stage 2: COMET Days (CMD) → Stage 3: Unit Nights → Stage 4: Day Shifts
```

Each stage uses the `partial_roster` from previous stages as input.

### Stage 1: COMET Night Assignment
**File**: `rostering/sequential_solver.py`  
**Method**: `_assign_comet_nights_sequential()`

**Algorithm**:
1. Identify all COMET weeks (Monday-Sunday ranges)
2. Filter COMET-eligible registrars
3. Calculate WTE-adjusted fair targets
4. **Doctor-focused assignment loop**:
   - For each doctor (starting with most under-target):
     - Find their "neediest" week (least coverage)
     - Try to assign them to that week
     - Use CP-SAT to find optimal block pattern
     - Update running totals
5. **Cleanup pass**: Fill any remaining gaps
6. Verify 100% coverage achieved

**CP-SAT Model per Week**:
- **Variables**: `x[p_idx, d_idx]` = 1 if doctor p works day d
- **Constraints**:
  - Each night has exactly 1 doctor assigned
  - Block size limits (no 5+ night blocks)
  - Rest period enforcement (2 days off after block ends)
  - Doctor availability (leave, previous assignments)
- **Objective**: Maximize block quality score (prefer 4+3, avoid singletons)

**Current Status**: ✅ Fully implemented and working

### Stage 2: COMET Day Assignment
**Status**: ⚠️ **NOT YET IMPLEMENTED** - Placeholder only

**Planned Algorithm**:
- Similar to COMET nights but for day shifts
- Must respect night shift assignments (can't work day after night)
- Should spread days fairly across eligible doctors

### Stage 3: Unit Night Assignment
**File**: `rostering/sequential_solver.py`  
**Method**: `_assign_multichunk_unit_nights_cpsat()`

**Algorithm**:
1. Identify all non-COMET nights needing coverage
2. Split into "chunks" separated by COMET weeks
3. For each chunk:
   - Create CP-SAT model with ALL eligible doctors
   - **Variables**: `x[p_idx, d_idx]` = 1 if doctor p works night d
   - **Constraints**:
     - **Backward rest check**: Skip variable creation if `days_since <= 1` from previous block
     - **Forward COMET check**: Skip variable creation if COMET block starts within 2 days
     - Block size limits (2-4 nights)
     - **Forward rest within chunk**: Enforce rest on d+2 after block ends
     - Coverage: Each night gets exactly 1 doctor
   - **Objective**: Minimize fairness penalty + block quality
4. Verify 100% coverage and zero rest violations

**Current Status**: ✅ Fully implemented with complete rest checking

### Stage 4: Day Shift Assignment
**Status**: ⚠️ **NOT YET IMPLEMENTED**

---

## Implementation Status

### ✅ Completed Features
- [x] COMET night assignment with fairness optimization
- [x] Unit night assignment with CP-SAT
- [x] 46-hour rest constraint (all three check types)
- [x] Block formation rules (2-4 nights only)
- [x] Coverage verification (100% for COMET + unit nights)
- [x] WTE-adjusted workload distribution
- [x] Leave handling and availability checking
- [x] Block pattern preferences (4+3 optimization)
- [x] Cumulative fairness tracking
- [x] Rest violation detection and verification
- [x] Output formatting (clean, essential info only)

### ⚠️ Partially Implemented
- [ ] Weekend distribution tracking (tracked but not optimized)
- [ ] COMET day assignments (placeholder only)

### ❌ Not Yet Implemented
- [ ] Full day shift assignment (Stage 4)
- [ ] Consecutive block spacing optimization
- [ ] Cross-stage fairness balancing (nights vs days)
- [ ] User preference handling (requested shifts)
- [ ] Shift swapping and rota modification
- [ ] Long-term fairness tracking (across multiple rotas)

---

## Known Issues & Future Work

### Current Known Issues
1. **COMET day assignment**: Placeholder stage needs full implementation
2. **Weekend fairness**: Not yet optimized, only tracked
3. **Cross-stage fairness**: Each stage optimizes independently; no global fairness check
4. **Lint warnings**: Pre-existing f-string and undefined variable warnings (non-critical)

### Future Enhancements

#### High Priority
1. **Implement COMET day assignment** (Stage 2)
   - Respect night→day rest periods
   - Fair distribution across eligible doctors
   - Integration with COMET night assignments

2. **Implement day shift assignment** (Stage 4)
   - Handle ward/unit-specific requirements
   - Balance teaching/clinic/ward time
   - Respect all previous assignments (nights + COMET)

3. **Cross-stage fairness optimization**
   - Balance total workload (not just within each stage)
   - Account for intensity differences (night vs day)
   - Global fairness score across all shift types

#### Medium Priority
4. **Weekend distribution optimization**
   - Penalize consecutive weekends
   - Fair weekend distribution across all doctors

5. **Long-term fairness tracking**
   - Track fairness across multiple consecutive rotas
   - Preferentially assign under-worked doctors in future rotas

6. **User preference system**
   - Allow doctors to request specific shifts
   - Soft constraints for preference satisfaction

#### Low Priority
7. **Shift swapping mechanism**
   - Allow post-generation modifications
   - Validate swaps don't violate constraints

8. **Advanced reporting**
   - Detailed fairness reports
   - Workload intensity analysis
   - Historical trend analysis

---

## Testing & Verification

### Test Files
- `test_comet_fairness.py` - COMET assignment fairness testing
- `test_comet_constraints.py` - COMET-specific constraint validation
- `test_constraints.py` - General constraint testing
- `test_full_solve.py` - End-to-end solver testing
- `test_violations.py` - Rest violation detection

### Key Verification Checks
1. **Rest Violations**: `✅ NO REST VIOLATIONS - All blocks have 2+ rest days!`
2. **Coverage**: `181/181 unit nights assigned` (100%)
3. **Block Distribution**: `{2: 1, 3: 25, 4: 26}` (no 5+ blocks)
4. **Fairness**: All eligible doctors assigned within reasonable range

### How to Run Tests
```bash
# Full fairness test
python test_comet_fairness.py

# Quick constraint check
python test_constraints.py

# Full solver run
python scripts/solve_sample.py
```

---

## Key Code Locations

### Main Solver
- **File**: `rostering/sequential_solver.py`
- **Class**: `SequentialSolver`
- **Entry point**: `solve()` method (line ~200)

### Constraint Implementations
- **Rest constraints**: Lines 1476-1570 (backward, forward COMET, forward within chunk)
- **Block formation**: Lines 1663-1690 (CP-SAT constraints)
- **Coverage constraints**: Lines 1691-1695 (each night = 1 doctor)
- **Eligibility filtering**: `_is_available()` method

### Fairness Optimization
- **Cumulative scoring**: Lines 380-410
- **Target calculation**: Lines 470-490
- **Doctor selection**: Lines 950-1050 (neediest-first approach)

### Output Formatting
- **Essential output only**: Lines 469-640 (verbose sections commented out)
- **Violation checking**: `constraint_violations.py`

---

## Configuration

### Input Files
- **Config**: `data/medical_rota_6month.yml` - Shift requirements, COMET weeks, constraints
- **People**: `data/sample_people.csv` - Doctor details, WTE, eligibility, leave

### Key Config Parameters
```yaml
comet_on_weeks:  # List of COMET week start dates (Mondays)
  - 2026-01-06
  - 2026-02-10
  # ...

shift_requirements:  # Daily shift needs
  - date: "2026-01-01"
    shifts:
      - type: "N_REG"
        count: 1
      # ...
```

---

## Update Guidelines

**When making changes to the solver, please update this document**:

1. **Hard constraints added/modified** → Update [Hard Constraints](#hard-constraints) section
2. **New stage implemented** → Update [Solver Architecture](#solver-architecture) and [Implementation Status](#implementation-status)
3. **Bug fixes** → Update [Current Status] markers and [Known Issues](#known-issues--future-work)
4. **New features** → Add to [Implementation Status](#implementation-status)
5. **Test coverage changes** → Update [Testing & Verification](#testing--verification)

**How to update**:
```bash
# Edit this file
nano SOLVER_CONTEXT.md

# Update the "Last Updated" date at the top
# Add details to relevant sections
# Mark features as ✅, ⚠️, or ❌ as appropriate
```

---

## Quick Reference for New LLM Sessions

### "I want to understand the solver"
→ Read [Overview](#overview) and [Solver Architecture](#solver-architecture)

### "I want to fix a bug"
→ Check [Known Issues](#known-issues--future-work) and [Key Code Locations](#key-code-locations)

### "I want to add a new feature"
→ Review [Implementation Status](#implementation-status) and [Future Enhancements](#future-enhancements)

### "I want to verify constraints"
→ See [Hard Constraints](#hard-constraints) and [Testing & Verification](#testing--verification)

### "I want to understand rest periods"
→ Read [Hard Constraints > Rest Period Requirements](#1-rest-period-requirements-46-hour-rule)

### "I want to improve fairness"
→ Check [Soft Constraints](#soft-constraints--preferences) and [Fairness Optimization](#fairness-optimization)

---

**End of Context Document**
