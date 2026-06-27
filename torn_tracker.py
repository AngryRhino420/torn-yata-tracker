import json
import os
import statistics
from datetime import datetime, timedelta

import gspread
import requests

# === PATH SETUP ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "tracker_state.json")
CREDS_FILE = os.path.join(BASE_DIR, "google-service-account.json")

# === CONFIG ===
SHEET_URL = "https://docs.google.com/spreadsheets/d/1txgKmKuLZB3iGpsLG8U-j_Z5gfyMdr_lKXNfNZNI2es/edit?gid=0#gid=0"
YATA_URL = "https://yata.yt/api/v1/travel/export/"

TRACKED = {
    "uni": {"country": "UK", "item_name": "Xanax", "item_id": 206},
    "jap": {"country": "Japan", "item_name": "Xanax", "item_id": 206},
}

TRAVEL_TIMES = {
    "UK": timedelta(hours=1, minutes=47),
    "Japan": timedelta(hours=2, minutes=22),
}

# prediction sheet column order
PREDICTION_HEADERS = [
    "prediction_time",
    "country",
    "item_name",
    "last_restock",
    "median_interval",
    "predicted_next_restock",
    "actual_next_restock",
    "error_minutes",
    "travel_time",
    "leave_by_time",
]

# === GOOGLE SHEETS SETUP ===
import os
import json
import gspread

credentials = json.loads(
os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
)

client = gspread.service_account_from_dict(credentials)

sh = gc.open_by_url(SHEET_URL)
ws = sh.sheet1
prediction_ws = sh.worksheet("prediction")


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def get_live_data():
    response = requests.get(YATA_URL, timeout=20)
    response.raise_for_status()
    return response.json()


def find_xanax(country_data):
    for item in country_data["stocks"]:
        if item["name"].lower() == "xanax":
            return item
    return None


def fmt_dt(dt_obj):
    return dt_obj.strftime("%Y-%m-%d %H:%M:%S")


def parse_dt(dt_string):
    return datetime.strptime(str(dt_string).strip(), "%Y-%m-%d %H:%M:%S")


def fmt_td(td):
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    return f"{hours:02d}:{minutes:02d}"


def append_event(
    event_time,
    event_type,
    code,
    country,
    item_id,
    item_name,
    previous_qty,
    current_qty,
    yata_update,
    source,
    notes,
):
    row = [
        event_time,
        event_type,
        code,
        country,
        str(item_id),
        item_name,
        str(previous_qty) if previous_qty is not None else "",
        str(current_qty),
        yata_update,
        source,
        notes,
    ]
    ws.append_row(row)


def get_restock_rows(country, item_name):
    rows = ws.get_all_records()
    restock_rows = []

    for row in rows:
        row_event_type = str(row.get("event_type", "")).strip().lower()
        row_country = str(row.get("country", "")).strip().lower()
        row_item_name = str(row.get("item_name", "")).strip().lower()
        row_event_time = str(row.get("event_time", "")).strip()

        if (
            row_event_type == "restock"
            and row_country == country.strip().lower()
            and row_item_name == item_name.strip().lower()
            and row_event_time
        ):
            restock_rows.append(row)

    restock_rows.sort(key=lambda r: parse_dt(r["event_time"]))
    return restock_rows


def resolve_previous_prediction(country, item_name, actual_restock_time):
    records = prediction_ws.get_all_records()

    last_open_index = None
    last_open_row = None

    for idx, row in enumerate(records, start=2):  # row 1 is headers
        row_country = str(row.get("country", "")).strip().lower()
        row_item = str(row.get("item_name", "")).strip().lower()
        actual_value = str(row.get("actual_next_restock", "")).strip()
        predicted_value = str(row.get("predicted_next_restock", "")).strip()

        if (
            row_country == country.strip().lower()
            and row_item == item_name.strip().lower()
            and predicted_value
            and not actual_value
        ):
            last_open_index = idx
            last_open_row = row

    if last_open_index is None:
        print(f"No open prediction to resolve for {country} {item_name}")
        return

    predicted_dt = parse_dt(last_open_row["predicted_next_restock"])
    error_minutes = round((actual_restock_time - predicted_dt).total_seconds() / 60, 2)

    # Column G = actual_next_restock, Column H = error_minutes
    prediction_ws.update(
        range_name=f"G{last_open_index}:H{last_open_index}",
        values=[[fmt_dt(actual_restock_time), str(error_minutes)]]
    )

    print(
        f"Resolved prediction for {country} {item_name} "
        f"with actual={fmt_dt(actual_restock_time)} error_minutes={error_minutes}"
    )


def append_prediction(country, item_name):
    restock_rows = get_restock_rows(country, item_name)

    if len(restock_rows) < 2:
        print(f"Not enough restock history to predict for {country} {item_name}")
        return

    restock_times = [parse_dt(r["event_time"]) for r in restock_rows]
    intervals = []

    for i in range(1, len(restock_times)):
        intervals.append(restock_times[i] - restock_times[i - 1])

    median_interval = statistics.median(intervals)
    last_restock = restock_times[-1]
    predicted_next_restock = last_restock + median_interval

    minute = predicted_next_restock.minute
    quarter_options = [0, 15, 30, 45]
    closest_quarter = min(quarter_options, key=lambda q: abs(minute - q))
    predicted_next_restock = predicted_next_restock.replace(
        minute=closest_quarter, second=0, microsecond=0
    )

    travel_time = TRAVEL_TIMES[country]
    leave_by_time = predicted_next_restock - travel_time
    prediction_time = datetime.now()

    prediction_row = [
        fmt_dt(prediction_time),
        country,
        item_name,
        fmt_dt(last_restock),
        str(median_interval),
        fmt_dt(predicted_next_restock),
        "",
        "",
        fmt_td(travel_time),
        fmt_dt(leave_by_time),
    ]

    prediction_ws.append_row(prediction_row)
    print(f"Prediction row added for {country} {item_name}")


def main():
    state = load_state()
    data = get_live_data()
    now_str = fmt_dt(datetime.now())

    for code, meta in TRACKED.items():
        country_data = data["stocks"][code]
        xanax = find_xanax(country_data)

        if not xanax:
            continue

        current_qty = int(xanax["quantity"])
        yata_update = fmt_dt(datetime.fromtimestamp(country_data["update"]))
        previous_qty = state.get(code, {}).get("quantity")

        print(f"Checking {meta['country']} ({code})")
        print("Previous quantity:", previous_qty)
        print("Current quantity: ", current_qty)

        if previous_qty is None:
            print("First run for this country; storing state only.")

        elif previous_qty == 0 and current_qty > 0:
            append_event(
                now_str,
                "restock",
                code,
                meta["country"],
                meta["item_id"],
                meta["item_name"],
                previous_qty,
                current_qty,
                yata_update,
                "live_yata",
                "",
            )
            print("Restock event logged.")

            actual_restock_dt = parse_dt(now_str)
            resolve_previous_prediction(meta["country"], meta["item_name"], actual_restock_dt)
            append_prediction(meta["country"], meta["item_name"])

        elif previous_qty > 0 and current_qty == 0:
            append_event(
                now_str,
                "depletion",
                code,
                meta["country"],
                meta["item_id"],
                meta["item_name"],
                previous_qty,
                current_qty,
                yata_update,
                "live_yata",
                "",
            )
            print("Depletion event logged.")

        else:
            print("No event.")

        state[code] = {
            "quantity": current_qty,
            "yata_update": yata_update,
        }

    save_state(state)
    print("Done.")


if __name__ == "__main__":
    main()
