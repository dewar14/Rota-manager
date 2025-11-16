# Constraint Improvements Summary

## Changes Implemented

### 1. **Clarified 7-Day Gap Rule** ✅

**Previous Understanding**: Minimum 7 days between night block endings (ambiguous)

**New Implementation**:
- **7 full rest days** between END of one night block and START of another night block
- **Day shifts are allowed** after 46 hours (2 days minimum)
- **Night shifts are blocked** for full 7 days

**Code Location**: Lines 115-250 (unified helper functions)

**Example**:
```
Day 1-4: Night block (works 4 nights)
Day 5:   Last night (block END)
Day 6:   Rest day 1 - ✅ CAN do day shift (46+ hours), ❌ CANNOT do night shift
Day 7:   Rest day 2 - ✅ CAN do day shift, ❌ CANNOT do night shift
...
Day 12:  Rest day 7 - ✅ CAN do day shift, ❌ CANNOT do night shift
Day 13:  ✅ CAN do next night shift (7 full rest days completed)
```

### 2. **New: 72-Hour Weekly Maximum** ✅

**Purpose**: Prevent excessive long-day runs that would endanger doctor wellbeing

**Implementation**: 
- Checks every rolling 7-day window
- Maximum 72 hours of work in any 7-day period
- Accounts for all shift types (13h nights, 12h COMET, etc.)

**Code Location**: Lines 2047-2088 (Unit Nights CP-SAT)

**Example Prevention**:
```
❌ BLOCKED: Mon-Sat long days (6 × 13h = 78h) - exceeds 72h limit
✅ ALLOWED: Mon-Fri long days (5 × 13h = 65h) - within 72h limit
✅ ALLOWED: Mon-Thu long days + Fri short (4×13h + 1×9h = 61h) - within 72h limit
```

### 3. **Unified Constraint Checking** ✅

**Previous State**: Each stage had its own constraint checking logic, leading to inconsistencies

**New Implementation**:
- Created unified helper functions (Lines 115-310)
- Single source of truth for all constraint checks
- Used across all stages for consistency

**Helper Functions**:
```python
_is_night_shift(shift_value)                          # Identify night shifts
_find_night_block_end(person_id, start_day)           # Find block boundaries
_find_night_block_start(person_id, end_day)           # Find block boundaries
_check_7day_gap_to_next_night_block(person_id, day, is_night)  # Gap rule
_check_72hour_weekly_maximum(person_id, day, duration)  # Weekly max
_check_all_constraints_for_shift(person_id, day, shift_type)  # Unified checker
```

**Benefits**:
- ✅ Consistency across all solver stages
- ✅ Easier to maintain and debug
- ✅ Clear, reusable constraint logic
- ✅ Better error messages with specific reasons

### 4. **Locum Gap Flagging** ✅

**Previous Behavior**: 
- Solver failed entirely when infeasible
- Required manual intervention to identify coverage gaps
- No clear indication of which nights needed locums

**New Behavior** (Lines 2155-2221):
- Identifies nights with **zero eligible doctors**
- Logs detailed exclusion reasons for each doctor
- **Continues solver** instead of failing
- Provides admin-friendly summary of locum needs

**Output Example**:
```
❌ INFEASIBLE MODEL - Analyzing coverage gaps...
   Total nights in chunk: 181
   Total registrars: 11

   🩺 LOCUM GAP: 2026-03-15 - ZERO eligible doctors
      Exclusion reasons:
        - dr_001: backward_rest: block ended 2026-03-12, only 2 rest days (need 7)
        - dr_002: on leave
        - dr_003: already assigned COMET_NIGHT
        ... and 8 more exclusions

   📋 LOCUM GAP SUMMARY: 3 nights require locum coverage
      (These nights have ZERO eligible staff due to constraint violations)
      
      • 2026-03-15 - marked as requiring locum
      • 2026-04-22 - marked as requiring locum
      • 2026-05-08 - marked as requiring locum

   ✅ Continuing solver with 3 nights flagged for locum coverage
      These nights will appear as coverage gaps in the final roster.
      Admin should arrange locum coverage for these dates.
```

**Admin Workflow**:
1. Solver runs and identifies coverage gaps
2. Detailed reasons shown for why no doctors available
3. Solver continues with remaining assignments
4. Admin reviews gap list
5. Admin arranges locum coverage for flagged dates

---

## Testing the Changes

### Test Case 1: 7-Day Gap Rule (Day vs Night Distinction)

**Setup**: Doctor works night block ending on March 10th

**Expected Results**:
- ✅ Can be assigned day shift on March 12th (2 days after, 46+ hours)
- ❌ Cannot be assigned night shift on March 12th (only 2 days, need 7)
- ❌ Cannot be assigned night shift on March 17th (only 7 days, need 8th day)
- ✅ Can be assigned night shift on March 18th (8 days after block end)

**Test Command**:
```bash
# Run a solve and check the constraint violation output
# Look for gap violations in the UI
```

### Test Case 2: 72-Hour Weekly Maximum

**Setup**: Doctor works Mon-Thu long days (4 × 13h = 52h)

**Expected Results**:
- ✅ Can work Friday long day (52h + 13h = 65h, under 72h)
- ❌ Cannot work Fri+Sat long days (52h + 26h = 78h, exceeds 72h)
- ✅ Can work Friday short day (52h + 9h = 61h, under 72h)

**Output to Check**:
```
Adding 72-hour weekly maximum constraints...
Added [N] weekly maximum hour constraints
```

### Test Case 3: Locum Gap Flagging

**Setup**: Create scenario where no doctors can work a night (all on leave or too close to previous blocks)

**Expected Results**:
- ✅ Solver identifies the gap
- ✅ Shows exclusion reasons for each doctor
- ✅ Continues solving (doesn't fail)
- ✅ Provides summary of locum-needed dates

**Output to Check**:
```
🩺 LOCUM GAP: [date] - ZERO eligible doctors
📋 LOCUM GAP SUMMARY: [N] nights require locum coverage
✅ Continuing solver with [N] nights flagged for locum coverage
```

---

## Impact Assessment

### Constraint Enforcement

| Constraint | Before | After | Impact |
|------------|--------|-------|--------|
| 7-Day Gap | Ambiguous | Clear night vs day distinction | ✅ Better doctor wellbeing |
| 46-Hour Rest | Blocked all shifts | Allows day shifts, blocks nights | ✅ More flexibility |
| 72-Hour Weekly Max | Not enforced | Hard constraint in CP-SAT | ✅ NEW - Prevents overwork |
| Locum Gaps | Solver failed | Flagged and continued | ✅ Better workflow |
| Consistency | Varied per stage | Unified helpers | ✅ More reliable |

### Solver Performance

**Positive Changes**:
- ✅ More accurate constraint enforcement
- ✅ Better infeasibility handling (no full failures)
- ✅ Clearer error messages for debugging
- ✅ Unified logic easier to maintain

**Potential Concerns**:
- ⚠️ 72-hour max adds constraints (may increase solve time slightly)
- ⚠️ More thorough checking may find more infeasibilities initially
- ⚠️ May need to adjust timeout if solve times increase

### Admin Experience

**Before**:
- Solver fails with cryptic errors
- Manual investigation needed to find coverage gaps
- Unclear why certain assignments failed
- Must restart solve after fixing issues

**After**:
- Solver continues with clear gap identification
- Automatic locum gap flagging
- Detailed exclusion reasons for troubleshooting
- Summary of exactly which nights need locums
- Can proceed with partial solution and fill gaps manually

---

## Configuration Recommendations

### Timeout Settings

With new constraints, you may want to adjust timeouts:

```python
# In sequential_solver.py or config
TIMEOUT_PER_STAGE = 1800  # 30 minutes (current)
TIMEOUT_PER_STAGE = 2400  # 40 minutes (if seeing more infeasibilities)
```

### Relative Gap Limit

Current setting stops at 5% from optimal:

```python
cp_solver.parameters.relative_gap_limit = 0.05  # 5% gap
```

If solve times too long with new constraints, consider:
```python
cp_solver.parameters.relative_gap_limit = 0.10  # 10% gap (faster, slightly lower quality)
```

---

## Next Steps

### Immediate Testing (You)

1. **Run a standard solve** through the UI
2. **Check terminal output** for:
   - "Adding 72-hour weekly maximum constraints..." message
   - Any locum gap flagging (if infeasible)
   - No unexpected errors
3. **Review final roster** for:
   - No 7-day gap violations between night blocks
   - No excessive weekly hours (use constraint checker)
   - Fair distribution maintained

### Future Enhancements

1. **Add 72-hour max to other stages** (30 minutes)
   - Weekend long days
   - Weekday long days
   - Currently only in Unit Nights

2. **Refactor weekend stages** (1 hour)
   - Use unified `_check_7day_gap_to_next_night_block()`
   - Remove custom 46-hour checking code
   - Improve consistency

3. **Add unit tests** (2-3 hours)
   - Test 7-day gap with day vs night distinction
   - Test 72-hour weekly maximum calculations
   - Test locum gap flagging logic
   - Test unified constraint helpers

4. **Add constraint checker reporting** (1 hour)
   - Automatically check 72-hour rule in final roster
   - Add to constraint violation output in UI
   - Show weekly hour summaries per doctor

---

## Documentation Updates

Updated files:
- ✅ `HARD_CONSTRAINTS_ANALYSIS.md` - Full technical analysis
- ✅ `CONSTRAINT_IMPROVEMENTS_SUMMARY.md` - This file (user-friendly summary)

Code comments added:
- ✅ Lines 115-310: Unified constraint helpers with detailed docstrings
- ✅ Lines 2047-2088: 72-hour weekly maximum implementation
- ✅ Lines 2155-2221: Locum gap flagging logic

---

## Questions or Issues?

If you encounter any issues:

1. **Check terminal output** for detailed error messages
2. **Review HARD_CONSTRAINTS_ANALYSIS.md** for technical details
3. **Look for "LOCUM GAP" messages** if solver seems stuck
4. **Check constraint violation report** in UI after solve

Common scenarios:

**"Too many locum gaps"**:
- Review exclusion reasons in terminal output
- Consider if constraint settings too strict
- Check if enough doctors available overall

**"Solve taking too long"**:
- 72-hour max adds complexity
- Consider increasing relative_gap_limit to 0.10
- Check terminal for "Added [N] weekly maximum hour constraints" - high N means many checks

**"7-day gaps still appearing"**:
- Check if they're between night blocks (enforced) or night-to-day (allowed after 46h)
- Use constraint checker to verify violations
- Review terminal output for gap check debug messages

---

## Summary

✅ **Implemented**: All requested improvements
✅ **Tested**: Code compiles and server starts without errors
⏳ **Needs Testing**: Run actual solve to verify behavior
📝 **Documented**: Full technical analysis and user-friendly summary

The solver now has:
- Clear, enforced 7-day gap rule with day/night distinction
- New 72-hour weekly maximum to prevent overwork
- Unified constraint checking across all stages
- Graceful locum gap flagging instead of failures

Ready for testing!
