import gspread
from datetime import datetime, timedelta
import statistics

SERVICE_ACCOUNT_FILE = "google-service-account.json"
SPREADSHEET_NAME = "torn_yata_tracker"
EVENTS_WORKSHEET_NAME = "Sheet1"      # change if needed
PREDICTION_WORKSHEET_NAME = "prediction"

TARGET_COUNTRIES = ["Japan", "UK"]
TARGET_ITEM = "Xanax"

TRAVEL_TIMES = {
    "Japan": timedelta(hours=2, minutes=22),
    "UK": timedelta(hours=1, minutes=47),
}


def parse_dt(value):
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def fmt_dt(value):
    return value.strftime("%Y-%m-%d %H:%M:%S")


def fmt_td(td):
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    return f"{hours:02d}:{minutes:02d}"


gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
spreadsheet = gc.open(SPREADSHEET_NAME)

events_ws = spreadsheet.worksheet(EVENTS_WORKSHEET_NAME)
prediction_ws = spreadsheet.worksheet(PREDICTION_WORKSHEET_NAME)

rows = events_ws.get_all_records()

for target_country in TARGET_COUNTRIES:
    filtered = []

    for row in rows:
        country_value = str(row.get("country", "")).strip().lower()
        item_value = str(row.get("item_name", "")).strip().lower()
        event_value = str(row.get("event_type", "")).strip().lower()
        time_value = str(row.get("event_time", "")).strip()

        target_country_value = target_country.strip().lower()
        target_item_value = TARGET_ITEM.strip().lower()

        if (
            event_value == "restock"
            and country_value == target_country_value
            and item_value == target_item_value
            and time_value
        ):
            filtered.append(row)

    filtered.sort(key=lambda r: parse_dt(r["event_time"]))

    print("--------------------------------------------------")
    print("Country:", target_country)
    print("Item:", TARGET_ITEM)

    if len(filtered) < 2:
        print("Not enough restock data yet.")
        continue

    restock_times = [parse_dt(r["event_time"]) for r in filtered]

    intervals = []
    for i in range(1, len(restock_times)):
        intervals.append(restock_times[i] - restock_times[i - 1])

    median_interval = statistics.median(intervals)
    last_restock = restock_times[-1]
    predicted_next = last_restock + median_interval

    minute = predicted_next.minute
    quarter_options = [0, 15, 30, 45]
    closest_quarter = min(quarter_options, key=lambda q: abs(minute - q))
    predicted_next = predicted_next.replace(minute=closest_quarter, second=0, microsecond=0)

    travel_time = TRAVEL_TIMES[target_country]
    leave_by_time = predicted_next - travel_time

    prediction_time = datetime.now()

    print("Restocks found:", len(restock_times))
    print("Last restock:", last_restock)
    print("Median interval:", median_interval)
    print("Predicted next restock:", predicted_next)
    print("Travel time:", fmt_td(travel_time))
    print("Leave by time:", leave_by_time)

    prediction_row = [
        fmt_dt(prediction_time),
        target_country,
        TARGET_ITEM,
        fmt_dt(last_restock),
        str(median_interval),
        fmt_dt(predicted_next),
        "",
        "",
        fmt_td(travel_time),
        fmt_dt(leave_by_time),
    ]

    prediction_ws.append_row(prediction_row)
    print("Prediction row added to sheet.")