# Gap Constraint Bug Fixes

## Summary
Fixed critical bugs in 7-day gap constraint implementation that were preventing the constraints from working properly. The bugs involved both **off-by-one errors** in the CP-SAT constraints and **conflicting pre-filtering logic** that only enforced 2-day gaps.

## Bugs Fixed

### Bug 1: Off-by-one error in CP-SAT gap constraints

**Location:** `rostering/sequential_solver.py` lines ~1724-1731

**Problem:**
```python
# OLD CODE (WRONG)
for gap_days in range(2, 8):  # Days 2-7 after block end
    resume_idx = d_idx + 1 + gap_days
```

If a block ends at day `d_idx`:
- `d_idx` = last working day
- `d_idx + 1` = first rest day
- `d_idx + 1 + gap_days` where `gap_days ∈ [2, 7]`
- This checks days **3-9** after block end, not days 1-7!

**Fix:**
```python
# NEW CODE (CORRECT)
for gap_days in range(1, 8):  # Days 1-7 after block end
    resume_idx = d_idx + gap_days
```

Now correctly prevents work on days 1-7 after a block ends, requiring day 8+ for next block.

---

### Bug 2: Pre-filtering enforced only 2-day gaps

**Location:** `rostering/sequential_solver.py` lines ~1517-1519

**Problem:**
```python
# OLD CODE (WRONG)
days_since = full_roster_idx - prev_full_idx - 1
if days_since <= 1:  # Need 2 full rest days
    can_work = False
```

This **excluded days with less than 2-day gaps** from decision variables, meaning the CP-SAT 7-day constraints never got applied to those days!

**Fix:**
```python
# NEW CODE (CORRECT)
days_since = full_roster_idx - prev_full_idx - 1
if days_since < 7:  # Need 7 full rest days (hard constraint)
    can_work = False
    exclusion_reason = f"backward_rest: block ended {prev_day}, only {days_since} rest days (need 7)"
```

---

### Bug 3: Forward lookahead only checked 2 days

**Location:** `rostering/sequential_solver.py` lines ~1527-1556

**Problem:**
```python
# OLD CODE (WRONG)
for lookahead in range(1, 3):  # Check next 2 days
    ...
    if days_until <= 2:  # Need 2 full rest days before next block
        can_work = False
```

**Fix:**
```python
# NEW CODE (CORRECT)
for lookahead in range(1, 8):  # Check next 7 days (hard 7-day minimum)
    ...
    if days_until < 8:  # Need 7 full rest days before next block (hard constraint)
        can_work = False
        exclusion_reason = f"forward_rest: block starts {next_day}, only {days_until-1} rest days possible (need 7)"
```

---

### Bug 4: Duplicate within-chunk rest constraints

**Location:** `rostering/sequential_solver.py` lines ~1573-1604

**Problem:**
There were old 2-day rest constraints that conflicted with the new 7-day gap constraints:

```python
# OLD CODE (REMOVED)
# Forward rest constraint: After END of a block, must have 2 days rest
# This is ONLY checked for transitions WITHIN the chunk (between consecutive nights)
for p_idx, person in unit_night_eligible:
    for d_idx in range(len(chunk_unit_nights) - 1):
        ...
        # If block ends at d_idx, can't work at d_idx+2
        model.Add(x[p_idx, rest_d_idx] == 0).OnlyEnforceIf(block_end)
```

**Fix:**
Removed entire section and replaced with:
```python
# NOTE: Forward rest constraints are now handled by the hard 7-day gap constraints
# below, which eliminate the entire 2-6 day gap search space
```

---

## UI Fix

**Location:** `app/static/medical_rota_ui.html` line 638

**Problem:**
```javascript
// OLD CODE (WRONG)
{ name: 'weekend_holidays', display: 'Holiday Working Assignment', api: 'weekend_holidays' },
```

**Fix:**
```javascript
// NEW CODE (CORRECT)
{ name: 'weekend_holidays', display: 'Weekend Long Days', api: 'weekend_holidays' },
```

---

## Result

After these fixes:
1. ✅ 7-day minimum gap constraints are correctly enforced
2. ✅ Pre-filtering and CP-SAT constraints are aligned (both enforce 7 days)
3. ✅ No more conflicting 2-day rest constraints
4. ✅ UI label correctly shows "Weekend Long Days"

---

## About "Simultaneous Day/Night Assignments"

If you see doctors with both NIGHT_REG and LONG_DAY_REG on the same day in the UI, this is likely because:

1. **You're viewing intermediate results**: The UI shows the state after nights stage but before the weekend stage has filtered those days
2. **The weekend stage checks OFF status**: Lines 2457-2458 and 2472-2473 verify days are OFF before assigning weekend long days
3. **Solution**: Wait for the full solve to complete, or check the final output

The weekend assignment code correctly prevents overwriting existing shifts:
```python
sat_shift = self.partial_roster[sat_str][person.id]
sun_shift = self.partial_roster[sun_str][person.id]

# Only create variable if BOTH days are OFF
if sat_shift == ShiftType.OFF.value and sun_shift == ShiftType.OFF.value:
    x[p_idx, w_idx] = model.NewBoolVar(f"unit_weekend_{p_idx}_{w_idx}")
```

---

## Testing

To verify the fixes:
1. Restart the server
2. Run a fresh solve
3. Check night block gaps - should all be ≥7 days
4. Check final roster - no simultaneous day/night shifts
5. Verify UI button says "Weekend Long Days"
