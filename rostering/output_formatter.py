"""
Enhanced output generation with colored tabular format, statistics, and breach reporting.
"""

import pandas as pd
import datetime as dt
from typing import Dict, List, Tuple
from rostering.models import ProblemInput, SolveResult, ShiftType, SHIFT_DEFINITIONS

# Color mapping for different shift types
SHIFT_COLORS = {
    ShiftType.NIGHT_REG: "#FF0000",      # Red
    ShiftType.NIGHT_SHO: "#FF0000",      # Red  
    ShiftType.COMET_NIGHT: "#800000",    # Maroon
    ShiftType.LONG_DAY_REG: "#00FF00",   # Green
    ShiftType.LONG_DAY_SHO: "#00FF00",   # Green
    ShiftType.COMET_DAY: "#800080",      # Purple
    ShiftType.SHORT_DAY: "#FFFF00",      # Yellow
    ShiftType.CPD: "#FFA500",            # Orange
    ShiftType.REG_TRAINING: "#0000FF",   # Blue
    ShiftType.SHO_TRAINING: "#0000FF",   # Blue
    ShiftType.UNIT_TRAINING: "#0000FF",  # Blue
    ShiftType.INDUCTION: "#808080",      # Gray
    ShiftType.LTFT: "#FFFFFF",           # White
    ShiftType.LEAVE: "#ADD8E6",          # Light blue
    ShiftType.STUDY_LEAVE: "#90EE90",    # Light green
    ShiftType.OFF: "#FFFFFF",            # White
}

def generate_enhanced_output(result: SolveResult, problem: ProblemInput, solver_values=None) -> Dict:
    """Generate enhanced output with statistics and colored formatting."""
    
    if not result.success:
        return {"error": result.message}
    
    days = list(pd.date_range(problem.config.start_date, problem.config.end_date))
    people = problem.people
    
    # Generate tabulated rota with colors and flags
    rota_table = generate_rota_table(result.roster, days, people)
    
    # Calculate daily staffing levels
    daily_staffing = calculate_daily_staffing(result.roster, days, people)
    
    # Calculate individual doctor statistics
    doctor_stats = calculate_doctor_statistics(result.roster, days, people, problem)
    
    # Generate breach report
    breach_report = generate_breach_report(result.breaches, result.constraint_violations)
    
    # Create Excel/HTML output with formatting
    formatted_output = create_formatted_output(rota_table, daily_staffing, doctor_stats, days, people)
    
    return {
        "rota_table": rota_table,
        "daily_staffing": daily_staffing,
        "doctor_stats": doctor_stats,
        "breach_report": breach_report,
        "formatted_output": formatted_output,
        "summary": result.summary
    }


def generate_rota_table(roster: Dict[str, Dict[str, str]], days: List[dt.date], people: List) -> pd.DataFrame:
    """Generate main rota table with proper formatting."""
    
    # Create base DataFrame
    rota_data = {}
    date_flags = {}
    
    for day in days:
        day_str = day.strftime('%Y-%m-%d')
        rota_data[day_str] = {}
        
        # Add day flags
        flags = []
        if day.weekday() >= 5:  # Weekend
            flags.append("WE")
        if is_bank_holiday(day):  # You'd implement this check
            flags.append("BH") 
        if is_school_holiday(day):  # You'd implement this check
            flags.append("SH")
        date_flags[day_str] = " ".join(flags)
        
        # Fill shifts for each person
        day_roster = roster.get(day_str, {})
        for person in people:
            shift_code = day_roster.get(person.id, "OFF")
            rota_data[day_str][person.id] = shift_code
    
    # Convert to DataFrame
    df = pd.DataFrame(rota_data).T  # Transpose so dates are rows
    
    # Add date flags column
    df.insert(0, 'Flags', [date_flags.get(d, "") for d in df.index])
    
    # Add daily staffing column
    df.insert(1, 'Day Staff', [calculate_day_staff_count(roster.get(d, {})) for d in df.index])
    
    return df


def calculate_daily_staffing(roster: Dict[str, Dict[str, str]], days: List[dt.date], people: List) -> Dict[str, int]:
    """Calculate number of day-time clinicians per day."""
    daily_counts = {}
    
    day_shifts = [ShiftType.LONG_DAY_REG, ShiftType.LONG_DAY_SHO, ShiftType.SHORT_DAY, ShiftType.COMET_DAY]
    
    for day in days:
        day_str = day.strftime('%Y-%m-%d')
        day_roster = roster.get(day_str, {})
        
        count = 0
        for person in people:
            shift = day_roster.get(person.id, "OFF")
            if shift in day_shifts:
                count += 1
        
        daily_counts[day_str] = count
    
    return daily_counts


def calculate_doctor_statistics(roster: Dict[str, Dict[str, str]], days: List[dt.date], people: List, problem: ProblemInput) -> Dict[str, Dict[str, float]]:
    """Calculate comprehensive statistics per doctor."""
    
    stats = {}
    total_weeks = len(days) / 7
    
    for person in people:
        person_stats = {
            "total_hours": 0,
            "avg_weekly_hours": 0,
            "long_days": 0,  # LD + CoMET Day
            "nights": 0,     # Night + CoMET Night  
            "weekends": 0,
            "unit_training": 0,
            "regional_training": 0,
            "leave_days": 0,
            "shifts_worked": 0
        }
        
        weekend_days_worked = set()
        
        for day in days:
            day_str = day.strftime('%Y-%m-%d')
            shift = roster.get(day_str, {}).get(person.id, "OFF")
            
            if shift != "OFF":
                # Count hours
                hours = SHIFT_DEFINITIONS.get(shift, {}).get("hours", 0)
                person_stats["total_hours"] += hours
                
                if hours > 0:
                    person_stats["shifts_worked"] += 1
                
                # Count shift types
                if shift in [ShiftType.LONG_DAY_REG, ShiftType.LONG_DAY_SHO, ShiftType.COMET_DAY]:
                    person_stats["long_days"] += 1
                
                if shift in [ShiftType.NIGHT_REG, ShiftType.NIGHT_SHO, ShiftType.COMET_NIGHT]:
                    person_stats["nights"] += 1
                
                if shift == ShiftType.UNIT_TRAINING:
                    person_stats["unit_training"] += 1
                
                if shift in [ShiftType.REG_TRAINING, ShiftType.SHO_TRAINING]:
                    person_stats["regional_training"] += 1
                
                if shift in [ShiftType.LEAVE, ShiftType.STUDY_LEAVE]:
                    person_stats["leave_days"] += 1
                
                # Count weekends (if working either Saturday or Sunday)
                if day.weekday() >= 5:  # Weekend day
                    # Find the weekend this day belongs to
                    if day.weekday() == 5:  # Saturday
                        weekend_start = day
                    else:  # Sunday
                        weekend_start = day - dt.timedelta(days=1)
                    weekend_days_worked.add(weekend_start)
        
        person_stats["weekends"] = len(weekend_days_worked)
        person_stats["avg_weekly_hours"] = person_stats["total_hours"] / total_weeks if total_weeks > 0 else 0
        
        stats[person.id] = person_stats
    
    return stats


def generate_breach_report(breaches: Dict[str, List[str]], violations: List[Dict[str, str]]) -> Dict:
    """Generate detailed breach and constraint violation report."""
    
    report = {
        "summary": {},
        "details": [],
        "by_category": {}
    }
    
    # Count breaches by category
    for category, breach_list in breaches.items():
        report["summary"][category] = len(breach_list)
        report["by_category"][category] = breach_list
    
    # Add detailed violations
    report["details"] = violations
    
    # Calculate severity scores
    severity_weights = {
        "hard_constraints": 10,
        "firm_constraints": 5, 
        "preferences": 1
    }
    
    total_severity = 0
    for category, count in report["summary"].items():
        weight = severity_weights.get(category, 1)
        total_severity += count * weight
    
    report["total_severity_score"] = total_severity
    
    return report


def create_formatted_output(rota_table: pd.DataFrame, daily_staffing: Dict, doctor_stats: Dict, 
                          days: List[dt.date], people: List) -> Dict:
    """Create formatted output for display (HTML/Excel compatible)."""
    
    # Create HTML version with colors
    html_output = create_html_rota(rota_table, doctor_stats)
    
    # Create Excel version
    excel_output = create_excel_rota(rota_table, doctor_stats)
    
    # Create summary tables
    summary_tables = {
        "staffing_summary": create_staffing_summary(daily_staffing),
        "doctor_summary": create_doctor_summary(doctor_stats, people),
        "shift_distribution": create_shift_distribution(doctor_stats)
    }
    
    return {
        "html": html_output,
        "excel": excel_output,
        "summaries": summary_tables
    }


def create_html_rota(rota_table: pd.DataFrame, doctor_stats: Dict) -> str:
    """Create HTML version of rota with color coding."""
    
    html = "<table border='1' style='border-collapse: collapse;'>"
    
    # Header row
    html += "<tr><th>Date</th><th>Flags</th><th>Day Staff</th>"
    for col in rota_table.columns[2:]:  # Skip Flags and Day Staff
        html += f"<th>{col}</th>"
    html += "</tr>"
    
    # Data rows
    for date_str, row in rota_table.iterrows():
        html += f"<tr><td>{date_str}</td>"
        html += f"<td>{row['Flags']}</td>"
        html += f"<td>{row['Day Staff']}</td>"
        
        for person_id in rota_table.columns[2:]:
            shift = row[person_id]
            color = SHIFT_COLORS.get(shift, "#FFFFFF")
            html += f"<td style='background-color: {color};'>{shift}</td>"
        
        html += "</tr>"
    
    html += "</table>"
    
    # Add doctor statistics table
    html += "<br><h3>Doctor Statistics</h3>"
    html += create_doctor_stats_html(doctor_stats)
    
    return html


def create_doctor_stats_html(doctor_stats: Dict) -> str:
    """Create HTML table for doctor statistics."""
    
    html = "<table border='1' style='border-collapse: collapse;'>"
    html += "<tr><th>Doctor</th><th>Avg Weekly Hours</th><th>Long Days</th><th>Nights</th><th>Weekends</th><th>Unit Training</th><th>Regional Training</th></tr>"
    
    for doctor_id, stats in doctor_stats.items():
        html += f"<tr>"
        html += f"<td>{doctor_id}</td>"
        html += f"<td>{stats['avg_weekly_hours']:.1f}</td>"
        html += f"<td>{stats['long_days']}</td>"
        html += f"<td>{stats['nights']}</td>"
        html += f"<td>{stats['weekends']}</td>"
        html += f"<td>{stats['unit_training']}</td>"
        html += f"<td>{stats['regional_training']}</td>"
        html += f"</tr>"
    
    html += "</table>"
    return html


# Helper functions
def calculate_day_staff_count(day_roster: Dict[str, str]) -> int:
    """Count daytime clinical staff for a single day."""
    day_shifts = [ShiftType.LONG_DAY_REG, ShiftType.LONG_DAY_SHO, ShiftType.SHORT_DAY, ShiftType.COMET_DAY]
    return sum(1 for shift in day_roster.values() if shift in day_shifts)


def is_bank_holiday(day: dt.date) -> bool:
    """Check if day is a bank holiday - implement based on problem.config.bank_holidays."""
    # This would be implemented to check against the configured bank holidays
    return False


def is_school_holiday(day: dt.date) -> bool:
    """Check if day is a school holiday - implement based on problem.config.school_holidays."""
    # This would be implemented to check against Nottinghamshire school holidays
    return False


def create_staffing_summary(daily_staffing: Dict) -> pd.DataFrame:
    """Create summary of daily staffing levels."""
    return pd.DataFrame(list(daily_staffing.items()), columns=['Date', 'Day_Staff'])


def create_doctor_summary(doctor_stats: Dict, people: List) -> pd.DataFrame:
    """Create summary table of doctor statistics."""
    rows = []
    for person in people:
        stats = doctor_stats.get(person.id, {})
        rows.append({
            'Doctor': person.name,
            'Grade': person.grade,
            'WTE': person.wte,
            'Avg_Weekly_Hours': stats.get('avg_weekly_hours', 0),
            'Long_Days': stats.get('long_days', 0),
            'Nights': stats.get('nights', 0),
            'Weekends': stats.get('weekends', 0)
        })
    return pd.DataFrame(rows)


def create_shift_distribution(doctor_stats: Dict) -> Dict:
    """Create summary of shift distribution across all doctors."""
    total_stats = {
        'total_long_days': sum(stats.get('long_days', 0) for stats in doctor_stats.values()),
        'total_nights': sum(stats.get('nights', 0) for stats in doctor_stats.values()),
        'total_weekends': sum(stats.get('weekends', 0) for stats in doctor_stats.values()),
        'avg_weekly_hours': sum(stats.get('avg_weekly_hours', 0) for stats in doctor_stats.values()) / len(doctor_stats) if doctor_stats else 0
    }
    return total_stats


def create_excel_rota(rota_table: pd.DataFrame, doctor_stats: Dict) -> str:
    """Create Excel-compatible CSV with doctor stats appended."""
    # For now, return CSV format - could be enhanced to actual Excel with formatting
    csv_content = rota_table.to_csv()
    
    # Add doctor stats
    stats_df = pd.DataFrame(doctor_stats).T
    csv_content += "\n\nDoctor Statistics:\n" + stats_df.to_csv()
    
    return csv_content