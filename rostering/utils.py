import datetime as dt
from dateutil.rrule import rrule, DAILY

def date_list(start: dt.date, end: dt.date):
    return [d.date() for d in rrule(DAILY, dtstart=start, until=end)]
