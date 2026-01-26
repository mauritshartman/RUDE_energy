from datetime import date, datetime as dt, timedelta, timezone


def log(msg):
    ts_msg = f'{dt.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} {msg}'
    print(ts_msg)
