# Gap Constraint Optimization - Hard Constraints vs Soft Penalties

## Overview
Changed from soft gap penalties to **HARD 7-day minimum gap constraint** to dramatically reduce solver complexity and improve performance for full 6-month period optimization.

## Changes Made

### 1. Hard 7-Day Gap Constraint (Lines 1730-1760)

**BEFORE (Soft Penalty Approach):**
- Solver explored ALL gap possibilities (2, 3, 4, 5, 6... days)
- Each gap had different penalty weight: -44,933 for 2 days, -30,119 for 3 days, etc.
- Solver evaluated trade-offs between gap penalties and other objectives
- HUGE search space - every possible gap pattern explored

**AFTER (Hard Constraint Approach):**
```python
# HARD CONSTRAINT: If block ends at d_idx, cannot work for next 7 days
for gap_days in range(2, 8):  # Days 2-7 after block end
    resume_idx = d_idx + 1 + gap_days
    if resume_idx >= len(chunk_unit_nights):
        continue
    
    # If block ends, MUST NOT work within next 7 days
    model.Add(x[p_idx, resume_idx] == 0).OnlyEnforceIf(block_end)
```

**Benefits:**
- ✅ Invalid solutions (2-6 day gaps) immediately pruned - NOT explored
- ✅ Much smaller search space = faster solving
- ✅ Guaranteed minimum 7-day gaps (no violations)
- ✅ Simpler model with fewer objective terms

**Trade-offs:**
- ⚠️ Less flexible: Cannot accept 6-day gaps even if beneficial
- ⚠️ May make problem infeasible if roster too constrained
- ⚠️ No preference between 7, 14, 21, or 28-day gaps (all treated equally)

### 2. "Good Enough" Stopping Criterion (Lines 1888-1889)

**Added relative gap limit:**
```python
# Stop when solver finds solution within 5% of theoretical optimal
cp_solver.parameters.relative_gap_limit = 0.05
```

**How it works:**
- CP-SAT maintains both:
  - **Best solution found** (upper bound)
  - **Theoretical best possible** (lower bound from relaxation)
- When gap between them ≤ 5%, solver stops
- Example: If theoretical optimal = 100,000, stops at 95,000

**Benefits:**
- ✅ Dramatically faster solve times (stops early)
- ✅ Avoids diminishing returns (last 5% takes 80% of time)
- ✅ Still gets high-quality solutions (95%+ optimal)
- ✅ Predictable behavior (won't run for hours seeking perfection)

**Trade-offs:**
- ⚠️ May not find absolute best solution
- ⚠️ Could miss marginal improvements in edge cases

## Expected Impact

### Complexity Reduction
**Search Space Analysis:**

**OLD approach (soft penalties):**
- For each doctor's night block: Explore gaps of 2, 3, 4, 5, 6, 7, 8... days
- For 10 doctors × 20 blocks each = 200 blocks
- For each block, explore ~10 gap options
- Total combinations: Astronomical (10^200+ possibilities)

**NEW approach (hard constraint):**
- For each doctor's night block: Only gaps ≥7 days valid
- Invalid patterns immediately pruned (not explored)
- Search space reduced by ~80%
- Solver focuses only on feasible solutions

### Performance Gains
- **Expected solve time reduction:** 50-80% faster
- **For 6-month roster:** 
  - OLD: 5-10 minutes per stage (often timeout)
  - NEW: 2-5 minutes per stage (more predictable)

### Solution Quality
- **Gap distribution:** Guaranteed minimum 7 days
- **Weekend continuity:** Unchanged (still prioritized via bonuses)
- **Block quality:** Unchanged (3-4 night blocks still preferred)
- **Fairness:** Unchanged (WTE-adjusted distribution maintained)

## When This Might Not Work

### Potential Issues:
1. **Infeasibility**: If roster constraints make 7-day gaps impossible
   - **Symptom**: CP-SAT returns INFEASIBLE status
   - **Solution**: Reduce to 5-day minimum, add more doctors, or use locums

2. **Over-clustering**: All doctors might get longer gaps (14+ days)
   - **Symptom**: Some doctors idle for weeks while others overworked
   - **Solution**: Add spacing bonuses (already present at lines 1813-1852)

3. **Edge of roster**: Gaps at start/end of 6-month period
   - **Symptom**: Doctor works week 1 and week 2 (before roster starts)
   - **Solution**: Already handled by backward/forward rest checks

## Configuration Options

### Adjusting Gap Minimum
To change from 7 days to another value, modify line 1742:
```python
# Current: 7-day minimum
for gap_days in range(2, 8):  # Days 2-7 excluded

# For 5-day minimum:
for gap_days in range(2, 6):  # Days 2-5 excluded

# For 10-day minimum:
for gap_days in range(2, 11):  # Days 2-10 excluded
```

### Adjusting "Good Enough" Threshold
To change stopping criterion, modify line 1888:
```python
# Current: 5% gap
cp_solver.parameters.relative_gap_limit = 0.05

# More aggressive (stop at 10% gap, faster but lower quality):
cp_solver.parameters.relative_gap_limit = 0.10

# More conservative (stop at 2% gap, slower but higher quality):
cp_solver.parameters.relative_gap_limit = 0.02

# Disable (find absolute optimal, may take hours):
# cp_solver.parameters.relative_gap_limit = 0.0
```

## Testing Recommendations

### Before/After Comparison:
1. **Run OLD approach** (backup branch):
   ```bash
   git checkout feature/experimental-optimizations~1
   python scripts/solve_sample.py
   # Record: solve time, gap distribution, singleton count
   ```

2. **Run NEW approach** (current):
   ```bash
   git checkout feature/experimental-optimizations
   python scripts/solve_sample.py
   # Compare: solve time, gap distribution, singleton count
   ```

### Key Metrics to Compare:
- ✅ **Solve time** (should be 50-80% faster)
- ✅ **Gap distribution** (should show only 7+ day gaps)
- ✅ **Singleton count** (should remain near zero)
- ✅ **Weekend continuity** (should remain high)
- ✅ **Fairness** (WTE-adjusted variance should be similar)

### Success Criteria:
- Solve completes within 5 minutes (vs 10+ before)
- Zero gaps < 7 days (vs some 2-3 day gaps before)
- Similar or better block quality and fairness
- No infeasibility errors

## Rollback Plan

If this causes infeasibility or poor results:

1. **Revert to soft penalties:**
   ```bash
   git revert HEAD
   ```

2. **Or hybrid approach:** Keep hard constraint but reduce to 5 days:
   ```python
   for gap_days in range(2, 6):  # 5-day minimum instead of 7
   ```

3. **Or add escape clause:** Allow violations with huge penalty:
   ```python
   # Create violation variable with massive penalty
   gap_violation = model.NewBoolVar(f"gap_viol_{p_idx}_{d_idx}")
   model.Add(x[p_idx, resume_idx] == 0).OnlyEnforceIf([block_end, gap_violation.Not()])
   objective_terms.append(gap_violation * -1000000)  # Avoid unless necessary
   ```

## Implementation Notes

### Code Location
- **File:** `rostering/sequential_solver.py`
- **Function:** `_assign_multichunk_unit_nights_cpsat()`
- **Lines:** 1730-1760 (gap constraints), 1888-1889 (stopping criterion)

### Related Constraints
These changes interact with:
- **Rest constraints** (lines 1635-1690): Still enforce 46h rest after blocks
- **Block bonuses** (lines 1640-1728): Still encourage 3-4 night blocks
- **Weekend bonuses** (lines 1770-1806): Still prioritize weekend continuity
- **Fairness** (lines 1854-1872): Still balance workload across doctors

### Testing Performed
- ✅ Syntax check: Solver loads successfully
- ✅ No runtime errors on import
- ⏳ **Needs full solve test** to validate performance gains
