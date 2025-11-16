# Current Solver Constraints & Preferences (Unit Nights Stage)

## HARD CONSTRAINTS (Cannot be violated)

1. **46-Hour Rest Rule**
   - After a night block ends, must have 2 full days off (46+ hours rest)
   - Enforced BACKWARD: Check if 46h rest has passed since last block
   - Enforced FORWARD: Next 2 days after block ends must be OFF

2. **Coverage Requirement**
   - Exactly 1 Registrar per night (all 7 nights of every week)
   - Enforced via: `model.Add(sum(day_vars) == 1)`

3. **Maximum Block Length**
   - Maximum 4 consecutive nights
   - Prevents exhaustion and ensures reasonable work patterns
   - Enforced via: `model.Add(sum(consecutive_5) <= 4)`

4. **Variable Exclusions**
   - Doctors already assigned to other shifts cannot work nights
   - Rest constraint violations prevent variable creation

---

## SOFT CONSTRAINTS (Preferences - Weighted in Objective Function)

### Priority Order (Your Requirements):
1. **Blocks of appropriate size** ✅
2. **Weekend coverage & fairness** ✅
3. **Gaps between night blocks (14-day target)** ✅
4. **Block size preference by WTE** ✅

---

## 1. BLOCK SIZE PREFERENCES (Highest Priority)

### For 1.0 WTE (Full-Time):
- **4-night blocks**: +15,000 (Very strong preference)
- **3-night blocks**: +12,000 (Strong preference)
- **2-night blocks**: +2,000 (Discouraged - only if necessary)
- **Singleton nights**: **-50,000** (MASSIVE penalty - unacceptable)

### For 0.8 WTE:
- **3-night blocks**: +15,000 (Very strong preference) 
- **4-night blocks**: +12,000 (Strong preference)
- **2-night blocks**: +2,000 (Discouraged)
- **Singleton nights**: **-50,000** (MASSIVE penalty)

### For 0.6 WTE (Part-Time):
- **3-night blocks**: +12,000 (Strong preference)
- **2-night blocks**: +8,000 (Acceptable second choice)
- **4-night blocks**: +6,000 (Acceptable but not ideal)
- **Singleton nights**: **-45,000** (MASSIVE penalty)

**Analysis**: Singleton penalty (-50,000) is the strongest negative weight, ensuring blocks are formed.

---

## 2. WEEKEND CONTINUITY (Second Priority)

- **Fri-Sat-Sun (3-day)**: **+35,000** (HIGHEST priority - core weekend)
- **Thu-Fri-Sat-Sun (4-day)**: +18,000 (Good but not essential)

**Analysis**: 35,000 bonus is higher than any block bonus (15,000 max), ensuring weekend continuity takes priority when conflicts arise.

---

## 3. GAP PENALTIES (Third Priority - 14-day target)

**Formula**: `-100,000 × e^(-gap/2.5)` for gaps 2-13 days

| Gap (days) | Penalty | Description |
|------------|---------|-------------|
| 2 days | **-44,933** | Almost unacceptable (near singleton penalty) |
| 3 days | **-30,119** | Very harsh |
| 4 days | **-20,190** | Harsh |
| 5 days | **-13,534** | Moderate |
| 6 days | **-9,072** | Moderate |
| 7 days | **-6,081** | Minor |
| 10 days | **-1,832** | Very minor |
| 13 days | **-554** | Negligible |
| 14+ days | **0** | No penalty (ideal) |

**Analysis**: 2-day gap penalty (-44,933) is close to singleton penalty (-50,000), making 2-day gaps extremely undesirable.

---

## 4. SPACING BONUSES (Encourages even distribution over time)

Rewards doctors who haven't worked recently (days since last block):

| Days Since Last Block | Bonus | Description |
|-----------------------|-------|-------------|
| 28+ days | +7,500 | Strong preference (4+ weeks) |
| 21-27 days | +6,200 | Good preference (3-4 weeks) |
| 14-20 days | +5,000 | Moderate spacing (2-3 weeks) |
| 10-13 days | +3,100 | Slight preference (1.5-2 weeks) |
| 7-9 days | +1,500 | Minor bonus (1 week minimum) |
| 5-6 days | +600 | Very minor (just above rest) |
| 3-4 days | 0 | Neutral (just met rest) |
| <3 days | -1,000 | Penalty (working too soon) |

**Analysis**: These bonuses are smaller than gap penalties, meaning they encourage rotation but won't override gap penalties.

---

## 5. FAIRNESS (Load Balancing - Fourth Priority)

**MinMax Fairness**: Minimize the maximum WTE-adjusted workload

- Creates `max_load` variable: maximum of all doctors' WTE-adjusted night counts
- Each doctor's load = `(total_nights × 100/WTE)`
  - 1.0 WTE: load = nights × 100
  - 0.8 WTE: load = nights × 125
  - 0.6 WTE: load = nights × 167
- **Fairness weight**: -100 (per unit of max_load)

**Example**: If max_load = 500 (one doctor has 5 nights × 100), objective penalty = -50,000

**Analysis**: Fairness weight (-100) prevents extreme imbalances but is overridden by:
- Singleton penalties (-50,000)
- Weekend bonuses (+35,000)
- 2-day gap penalties (-44,933)

---

## PROCESSING STRATEGY

- **Chunk Size**: 21 days (3 weeks) - allows gap penalties to work across week boundaries
- **Chunk Overlap**: None (sequential 3-week chunks)
- **This fixes**: Gap penalties now catch 2-day gaps that span weeks (e.g., Sunday → Tuesday)

---

## RELATIVE WEIGHT HIERARCHY (Descending)

1. **-50,000**: Singleton penalty (STRONGEST)
2. **-44,933**: 2-day gap penalty (NEAR STRONGEST)
3. **+35,000**: Weekend continuity (HIGHEST POSITIVE)
4. **-30,119**: 3-day gap penalty
5. **-20,190**: 4-day gap penalty
6. **+18,000**: Thu-Sun weekend
7. **+15,000**: Block bonuses (4n for 1.0 WTE, 3n for 0.8 WTE)
8. **+12,000**: Block bonuses (3n for 1.0/0.6 WTE, 4n for 0.8 WTE)
9. **+8,000**: 2n block for 0.6 WTE
10. **+7,500**: Spacing bonus (28+ days)
11. **+6,200**: Spacing bonus (21-27 days)
12. **-6,081**: 7-day gap penalty
13. **+5,000**: Spacing bonus (14-20 days)
14. **+3,100**: Spacing bonus (10-13 days)
15. **+2,000**: 2-night blocks (1.0/0.8 WTE)
16. **+1,500**: Spacing bonus (7-9 days)
17. **-100**: Fairness weight (per unit max_load)

---

## EXPECTED BEHAVIOR

✅ **Singletons**: Should be extremely rare (only if mathematically forced)
✅ **2-day gaps**: Should be very rare (penalty -44,933 is near-singleton level)
✅ **Weekend continuity**: Should be strong (bonus +35,000 overrides most conflicts)
✅ **Block sizes**: Should match WTE preferences (4n/3n for 1.0, 3n for 0.8, 3n/2n for 0.6)
✅ **Fairness**: Should balance load across doctors (without breaking above rules)

---

## POTENTIAL ISSUES TO MONITOR

1. **Weekend bonus vs Gap penalty**: Weekend bonus (+35,000) is weaker than 2-day gap penalty (-44,933)
   - If a weekend causes a 2-day gap, the gap penalty might win
   - **Solution if needed**: Increase weekend bonus or add special logic to exempt weekends from gap penalties

2. **Fairness vs Block formation**: Fairness weight (-100 × max_load) could accumulate
   - If max_load reaches 500, penalty = -50,000 (equals singleton penalty)
   - This might force poor block choices to balance load
   - **Solution if needed**: Reduce fairness weight or cap max_load penalty

3. **3-week chunks**: Might create boundary effects between chunks
   - Gap penalties only work within each 21-day chunk
   - A gap spanning chunk boundaries won't be penalized
   - **Solution if needed**: Use overlapping chunks or longer chunks (4-6 weeks)

---

## QUESTIONS FOR VERIFICATION

1. **Weekend bonus strength**: Is +35,000 strong enough to override fairness concerns?
2. **Gap penalty curve**: Is the exponential decay appropriate? Should 7-day gaps be penalized more/less?
3. **Chunk size**: Should we use longer chunks (4-6 weeks) to catch more cross-chunk gaps?
4. **Fairness weight**: Is -100 the right balance between load balancing and pattern quality?
