import sys
import pandas as pd

def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    # Normalize date index if present in first column
    if df.columns[0] != 'date':
        df = df.rename(columns={df.columns[0]: 'date'})
    df['date'] = pd.to_datetime(df['date']).dt.date
    df = df.set_index('date')
    return df

# Count helper: returns (ld_sho, ld_reg, n_sho, n_reg, cmd, cmn, sd_total)
# Infer SHO/Reg by column headers (ids) not always available; we just count by shift code across all people columns.
# Locum columns in our output already explicit; target may not have them.
SHIFT_CODES = {"SD","LD","N","CMD","CMN","CPD","TREG","TSHO","TPCCU","IND","OFF"}

def count_cover(row: pd.Series):
    vals = [str(v).strip() for v in row.values]
    # Remove known locum columns from our roster if present
    vals = [v for k,v in row.items() if not str(k).startswith('LOC_')]
    ld = sum(1 for v in vals if v == 'LD')
    n  = sum(1 for v in vals if v == 'N')
    cmd = sum(1 for v in vals if v == 'CMD')
    cmn = sum(1 for v in vals if v == 'CMN')
    sd  = sum(1 for v in vals if v == 'SD')
    return ld, n, cmd, cmn, sd

def compare(ours: pd.DataFrame, target: pd.DataFrame):
    days = sorted(set(ours.index).intersection(set(target.index)))
    rows = []
    for d in days:
        ld_o, n_o, cmd_o, cmn_o, sd_o = count_cover(ours.loc[d])
        ld_t, n_t, cmd_t, cmn_t, sd_t = count_cover(target.loc[d])
        rows.append({
            'date': d.isoformat(),
            'ld_delta': ld_o - ld_t,
            'n_delta': n_o - n_t,
            'cmd_delta': cmd_o - cmd_t,
            'cmn_delta': cmn_o - cmn_t,
            'sd_delta': sd_o - sd_t,
        })
    return pd.DataFrame(rows)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python scripts/compare_to_csv.py <target_csv> [ours_csv=out/roster.csv]')
        sys.exit(2)
    target = load_csv(sys.argv[1])
    ours_path = sys.argv[2] if len(sys.argv) > 2 else 'out/roster.csv'
    ours = load_csv(ours_path)
    # Keep only overlapping dates
    common = ours.index.intersection(target.index)
    ours = ours.loc[common]
    target = target.loc[common]
    df = compare(ours, target)
    print(df.to_string(index=False))
