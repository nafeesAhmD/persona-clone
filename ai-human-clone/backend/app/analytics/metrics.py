from datetime import date, datetime, timedelta

def parse_range(
    range_str: str | None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[datetime, datetime]:
    now = datetime.utcnow().date()
    if range_str == "today" or range_str is None:
        start = datetime(now.year, now.month, now.day)
        end = start + timedelta(days=1)
    elif range_str == "yesterday":
        y = now - timedelta(days=1)
        start = datetime(y.year, y.month, y.day)
        end = datetime(now.year, now.month, now.day)
    elif range_str == "7d":
        start = datetime(now.year, now.month, now.day) - timedelta(days=7)
        end = datetime(now.year, now.month, now.day) + timedelta(days=1)
    elif range_str == "30d":
        start = datetime(now.year, now.month, now.day) - timedelta(days=30)
        end = datetime(now.year, now.month, now.day) + timedelta(days=1)
    elif range_str == "90d":
        start = datetime(now.year, now.month, now.day) - timedelta(days=90)
        end = datetime(now.year, now.month, now.day) + timedelta(days=1)
    elif range_str == "custom" and start_date and end_date:
        start = datetime(start_date.year, start_date.month, start_date.day)
        end = datetime(end_date.year, end_date.month, end_date.day) + timedelta(days=1)
    else:
        start = datetime(now.year, now.month, now.day) - timedelta(days=30)
        end = datetime(now.year, now.month, now.day) + timedelta(days=1)
    return start, end
