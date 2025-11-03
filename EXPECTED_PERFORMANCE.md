# Expected Performance & Quality Analysis

## Theoretical Analysis

### Search Space Reduction

**OLD: Soft Penalty Approach**
- For each doctor's block pair, explore gaps: 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13 days
- 12 possible gap values per block transition
- For 10 doctors × 15 blocks/doctor = 150 block transitions
- Approximate combinations: 12^150 ≈ **10^162** possibilities

**NEW: Hard Constraint Approach**
- For each doctor's block pair, only gaps ≥7 are valid: 7, 8, 9, 10, 11, 12, 13 days
- 7 possible gap values per block transition (5 eliminated)
- For 10 doctors × 15 blocks/doctor = 150 block transitions
- Approximate combinations: 7^150 ≈ **10^127** possibilities

**Reduction:** ~10^35 fewer combinations to explore (99.99999...% reduction)

### Objective Function Complexity

**OLD: Soft Penalties**
- Gap penalty terms: ~2000-3000 per stage
- Singleton penalties: ~200 per stage
- Block bonuses: ~400 per stage
- Weekend bonuses: ~100 per stage
- Fairness terms: ~10 per stage
- **TOTAL: ~2700 objective terms**

**NEW: Hard Constraints**
- Gap constraints: ~2000-3000 HARD constraints (not in objective)
- Singleton penalties: ~200 per stage
- Block bonuses: ~400 per stage
- Weekend bonuses: ~100 per stage
- Fairness terms: ~10 per stage
- **TOTAL: ~700 objective terms (74% reduction)**

## Expected Time Improvements

### Unit Nights Stage (Most Complex)

| Configuration | Old (Soft) | New (Hard + 5% stop) | Improvement |
|---------------|------------|---------------------|-------------|
| **1 Month** | 30-60 sec | 10-20 sec | 50-67% faster |
| **3 Months** | 2-4 min | 45-90 sec | 50-62% faster |
| **6 Months** | 8-15 min | 2-5 min | 60-75% faster |

### Full 6-Stage Solve

| Stage | Old Time | New Time | Notes |
|-------|----------|----------|-------|
| 1. COMET Nights | 30-60s | 30-60s | No change (greedy assignment) |
| 2. Unit Nights | 8-15 min | 2-5 min | **MAJOR improvement** |
| 3. Weekend/Holidays | 2-4 min | 1-2 min | Moderate improvement |
| 4. COMET Days | 1-2 min | 30-60s | Moderate improvement |
| 5. Weekday Long Days | 3-5 min | 1-2 min | Moderate improvement |
| 6. Short Days | 2-3 min | 1-2 min | Moderate improvement |
| **TOTAL** | **16-29 min** | **5-12 min** | **65-72% faster** |

### "Good Enough" Stopping Impact

Typical CP-SAT optimization curve:
```
Time:     0s    30s   1m    2m    3m    4m    5m    6m    7m    8m
Quality:  50%   70%   85%   92%   95%   97%   98%   98.5% 99%   99.2%
          ↑     ↑     ↑     ↑     ↑ STOP
          |_____|_____|_____|_____|
          Fast improvement  →  Diminishing returns
```

**5% Relative Gap:**
- Stops around 95% quality (typically 2-3 minutes)
- Last 5% quality takes 80% of time (6-8 additional minutes)
- **Trade-off:** Accept 95-99% quality, save 60-80% time

## Expected Quality Metrics

### Gap Distribution

**OLD (Soft Penalties):**
```
Gap Size    Count   Percentage
2 days      5-10    5-10%     ← Some violations
3 days      3-7     3-7%      ← Some violations
4 days      2-4     2-4%      ← Occasional
5 days      1-3     1-3%      ← Rare
6 days      1-2     1-2%      ← Very rare
7-13 days   50-70   50-70%    ← Most common
14+ days    20-30   20-30%    ← Good spacing
```

**NEW (Hard Constraint):**
```
Gap Size    Count   Percentage
2 days      0       0%        ✅ ELIMINATED
3 days      0       0%        ✅ ELIMINATED
4 days      0       0%        ✅ ELIMINATED
5 days      0       0%        ✅ ELIMINATED
6 days      0       0%        ✅ ELIMINATED
7-13 days   60-80   60-80%    ← Increased
14+ days    20-40   20-40%    ← Similar
```

### Block Quality (Should Remain Similar)

**Singleton Rate:**
- OLD: 0-2% (massive penalties)
- NEW: 0-2% (same penalties maintained)
- **Expected Change:** None

**Block Size Distribution:**
- OLD: 3-4 night blocks ~80%, 2-night ~15%, singletons ~5%
- NEW: 3-4 night blocks ~80%, 2-night ~15%, singletons ~5%
- **Expected Change:** None (bonuses unchanged)

### Weekend Continuity (Should Remain High)

**Fri-Sat-Sun Blocks:**
- OLD: 85-95% of weekends
- NEW: 85-95% of weekends
- **Expected Change:** None (bonuses unchanged)

### Fairness (Should Remain Balanced)

**WTE-Adjusted Variance:**
- OLD: Max load variance ≤15%
- NEW: Max load variance ≤15%
- **Expected Change:** None (fairness weight unchanged)

## Potential Risks & Mitigation

### Risk 1: Infeasibility
**Symptom:** CP-SAT returns INFEASIBLE status
**Probability:** Low-Moderate (10-30% chance)
**Impact:** Solve fails completely

**Causes:**
- Too few doctors for 7-day minimum gaps
- Rest constraints + gap constraints = no valid solutions
- COMET weeks + unit nights = over-constrained

**Mitigation:**
1. **Relax to 5-day minimum:**
   ```python
   for gap_days in range(2, 6):  # Allow 5+ day gaps
   ```
2. **Add locum coverage** for peak periods
3. **Revert to soft penalties** if persistent

### Risk 2: Over-Clustering
**Symptom:** Doctors idle for weeks, then work intensely
**Probability:** Low (5-10% chance)
**Impact:** Poor rotation patterns

**Causes:**
- Hard constraint forces wide gaps
- Fairness weight too low to balance
- Not enough "spacing bonus" incentive

**Mitigation:**
1. **Increase spacing bonuses** (lines 1813-1852):
   ```python
   # Increase bonus for long gaps
   if days_since_last >= 28:
       spacing_bonus = 15000  # Double current bonus
   ```
2. **Increase fairness weight** (line 1874):
   ```python
   objective_terms.append(max_load * -200)  # Stronger balance
   ```

### Risk 3: Early Stopping Quality Loss
**Symptom:** Visible imperfections in roster (poor fairness, broken continuity)
**Probability:** Low (5-10% chance)
**Impact:** Suboptimal but acceptable roster

**Causes:**
- 5% gap too aggressive for complex rosters
- Solver stopped before finding better patterns
- Trade-offs between objectives not fully explored

**Mitigation:**
1. **Reduce gap limit to 2%:**
   ```python
   cp_solver.parameters.relative_gap_limit = 0.02
   ```
2. **Increase timeout:** Give more time to explore
3. **Monitor objective value:** If stuck at plateau, stopping is good

## Success Criteria

### Must Have (Critical):
- ✅ **Solve completes** (not infeasible)
- ✅ **Zero gaps <7 days** (hard constraint working)
- ✅ **Solve time ≤5 minutes per stage** (performance gain achieved)

### Should Have (High Priority):
- ✅ **Zero singletons** (block quality maintained)
- ✅ **90%+ weekend continuity** (Fri-Sat-Sun blocks)
- ✅ **WTE-adjusted fairness ≤15% variance** (balanced workload)

### Nice to Have (Medium Priority):
- ✅ **50%+ gaps ≥14 days** (good spacing beyond minimum)
- ✅ **80%+ blocks are 3-4 nights** (optimal block sizes)
- ✅ **Solve time ≤3 minutes per stage** (better than expected)

## Benchmarking Plan

### Phase 1: Quick Validation (5 minutes)
```bash
# Test with small roster (1 month)
python scripts/solve_sample.py
```
**Check:**
- Does it solve? (not infeasible)
- Any gaps <7 days? (should be zero)
- Time compared to before? (should be faster)

### Phase 2: Full Test (30 minutes)
```bash
# Test with full 6-month roster via UI
# Navigate to: http://localhost:8000/medical_rota_ui.html
# Click "Generate Rota" with 5-minute timeout
```
**Measure:**
- Total solve time for all 6 stages
- Gap distribution (export CSV, analyze)
- Singleton count
- Weekend continuity percentage
- Fairness metrics (max/min load variance)

### Phase 3: Quality Comparison (1 hour)
**Run Both Approaches:**
1. Current branch (hard constraints)
2. Previous commit (soft penalties)

**Compare Side-by-Side:**
| Metric | Hard (New) | Soft (Old) | Winner |
|--------|-----------|-----------|--------|
| Solve time | ? | ? | ? |
| Gaps <7d | ? | ? | Hard (should be 0) |
| Singletons | ? | ? | Tie (both ~0) |
| Weekend % | ? | ? | Tie (both ~90%) |
| Fairness | ? | ? | Tie (both ~15%) |

### Phase 4: Stress Test (2 hours)
**Edge Cases:**
- Minimal doctors (6 registrars for 6-month roster)
- Maximal COMET weeks (every other week)
- Mixed WTE (0.6, 0.8, 1.0 all present)
- Long roster (9-12 months)

**Goal:** Find breaking point, validate mitigation strategies

## Monitoring During Solve

### Console Output to Watch:
```
✅ GOOD SIGNS:
   "Added NNNN HARD gap constraints"  ← Constraints active
   "Search space dramatically reduced"  ← Pruning working
   "Found solution #N"  ← Making progress
   "Solver finished: OPTIMAL"  ← Best result
   "Solver finished: FEASIBLE"  ← Good result

⚠️ WARNING SIGNS:
   "NO VARIABLES - This night has ZERO eligible doctors!"
   → Check rest constraints, may need locums
   
   "INFEASIBLE MODEL"
   → Hard constraint too strict, relax to 5 days
   
   "Found solution #1" (then no more)
   → Stuck at local optimum, may need more time

❌ FAILURE SIGNS:
   "Solver finished: INFEASIBLE"
   → No solution exists, must relax constraints
   
   "Solver finished: MODEL_INVALID"
   → Bug in code, report issue
```

## Rollback Decision Tree

```
Did solver complete?
├─ NO → Infeasible
│   ├─ Relax to 5-day minimum
│   ├─ If still fails → Revert to soft penalties
│   └─ If still fails → Add locums/more doctors
│
└─ YES → Check quality
    ├─ Any gaps <7 days?
    │   └─ YES → Bug! Hard constraint not working
    │
    ├─ Singleton rate >5%?
    │   └─ YES → Adjust block bonuses (different issue)
    │
    ├─ Weekend continuity <80%?
    │   └─ YES → Adjust weekend bonuses (different issue)
    │
    ├─ Fairness variance >20%?
    │   └─ YES → Increase fairness weight
    │
    └─ Solve time >8 minutes?
        ├─ YES → Increase stopping to 10%
        └─ NO → Success! ✅
```

## Next Steps

1. **Test current implementation:**
   ```bash
   python scripts/solve_sample.py
   ```

2. **Monitor solve output** for signs of success/failure

3. **Analyze results:**
   - Gap distribution (should be 0 gaps <7 days)
   - Solve time (should be 2-5 min for unit nights)
   - Overall quality (singletons, weekends, fairness)

4. **Adjust if needed:**
   - If infeasible → Relax to 5-day minimum
   - If too slow → Increase to 10% stopping
   - If quality issues → Decrease to 2% stopping

5. **Document findings** for future optimization decisions
