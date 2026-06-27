import json
import os
import statistics
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import gspread
import requests

# === TIMEZONES ===
CET_TZ = ZoneInfo("Europe/Berlin")  # CET/CEST with DST handled [web:1202]
UTC_TZ = ZoneInfo("UTC")

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

PREDICTION_HEADERS = [
    "prediction_time_cet",
    "country",
    "item_name",
    "last_restock_cet",
    "weighted_interval",
    "raw_predicted_next_restock_cet",
    "adjusted_predicted_next_restock_cet",
    "actual_next_restock_cet",
    "raw_error_minutes",
    "adjusted_error_minutes",
    "travel_time",
    "leave_by_time_cet",
    "model_notes",
]


def get_gspread_client():
    if os.path.exists(CREDS_FILE):
        return gspread.service_account(filename=CREDS_FILE)

    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_json:
        raise RuntimeError(
            "Missing Google credentials. Expected either "
            f"'{CREDS_FILE}' file or 'GOOGLE_SERVICE_ACCOUNT_JSON' environment variable."
        )

    with open(CREDS_FILE, "w", encoding="utf-8") as f:
        f.write(creds_json)

    return gspread.service_account(filename=CREDS_FILE)


def send_discord_message(message):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("DISCORD_WEBHOOK_URL not set; skipping Discord notification.")
        return

    try:
        response = requests.post(
            webhook_url,
            json={"content": message},
            timeout=20,
        )
        if response.status_code not in (200, 204):
            print(f"Discord webhook failed: {response.status_code} {response.text}")
        else:
            print("Discord notification sent.")
    except Exception as e:
        print(f"Discord notification error: {e}")


# === GOOGLE SHEETS SETUP ===
gc = get_gspread_client()
sh = gc.open_by_url(SHEET_URL)
ws = sh.sheet1
prediction_ws = sh.worksheet("prediction")


def ensure_prediction_headers():
    current_headers = prediction_ws.row_values(1)
    if current_headers != PREDICTION_HEADERS:
        prediction_ws.clear()
        prediction_ws.update("A1:M1", [PREDICTION_HEADERS])
        print("Prediction sheet headers set to CET-based schema.")


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


def to_cet_from_timestamp(ts: float) -> datetime:
    """
    Convert a Unix timestamp (assumed UTC/Torn-time) to timezone-aware CET datetime.
    """
    dt_utc = datetime.fromtimestamp(ts, tz=UTC_TZ)
    return dt_utc.astimezone(CET_TZ)


def now_cet() -> datetime:
    return datetime.now(CET_TZ)


def fmt_dt(dt_obj: datetime) -> str:
    """
    Format timezone-aware CET datetime as a string without timezone suffix,
    so the sheet stores consistent CET wall time.
    """
    return dt_obj.astimezone(CET_TZ).strftime("%Y-%m-%d %H:%M:%S")


def parse_cet(dt_string: str) -> datetime:
    """
    Parse a stored CET-formatted string and attach CET timezone.
    """
    naive = datetime.strptime(str(dt_string).strip(), "%Y-%m-%d %H:%M:%S")
    return naive.replace(tzinfo=CET_TZ)


def fmt_td(td: timedelta) -> str:
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    return f"{hours:02d}:{minutes:02d}"


def weighted_median_timedelta(timedeltas):
    if not timedeltas:
        raise ValueError("No timedeltas provided")

    weighted_seconds = []
    for i, td in enumerate(timedeltas, start=1):
        seconds = int(td.total_seconds())
        weighted_seconds.extend([seconds] * i)

    median_seconds = statistics.median(weighted_seconds)
    return timedelta(seconds=median_seconds)


def remove_interval_outliers(intervals):
    if len(intervals) < 4:
        return intervals, []

    interval_seconds = sorted(td.total_seconds() for td in intervals)
    q1 = statistics.median(interval_seconds[: len(interval_seconds) // 2])
    q3 = statistics.median(interval_seconds[(len(interval_seconds) + 1) // 2 :])
    iqr = q3 - q1
    lower_bound = q1 - (1.5 * iqr)
    upper_bound = q3 + (1.5 * iqr)

    filtered = []
    removed = []

    for td in intervals:
        sec = td.total_seconds()
        if lower_bound <= sec <= upper_bound:
            filtered.append(td)
        else:
            removed.append(td)

    if not filtered:
        return intervals, []

    return filtered, removed


def append_event(
    event_time_cet: datetime,
    event_type,
    code,
    country,
    item_id,
    item_name,
    previous_qty,
    current_qty,
    yata_update_cet: datetime,
    source,
    notes,
):
    row = [
        fmt_dt(event_time_cet),
        event_type,
        code,
        country,
        str(item_id),
        item_name,
        str(previous_qty) if previous_qty is not None else "",
        str(current_qty),
        fmt_dt(yata_update_cet),
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

    restock_rows.sort(key=lambda r: parse_cet(r["event_time"]))
    print(f"Found {len(restock_rows)} restock rows for {country} {item_name}")
    return restock_rows


def resolve_previous_prediction(country, item_name, actual_restock_cet: datetime):
    records = prediction_ws.get_all_records()

    last_open_index = None
    last_open_row = None

    for idx, row in enumerate(records, start=2):
        row_country = str(row.get("country", "")).strip().lower()
        row_item = str(row.get("item_name", "")).strip().lower()
        actual_value = str(row.get("actual_next_restock_cet", "")).strip()
        adjusted_pred = str(row.get("adjusted_predicted_next_restock_cet", "")).strip()
        raw_pred = str(row.get("raw_predicted_next_restock_cet", "")).strip()

        if (
            row_country == country.strip().lower()
            and row_item == item_name.strip().lower()
            and adjusted_pred
            and raw_pred
            and not actual_value
        ):
            last_open_index = idx
            last_open_row = row

    if last_open_index is None:
        print(f"No open prediction to resolve for {country} {item_name}")
        return

    raw_dt = parse_cet(last_open_row["raw_predicted_next_restock_cet"])
    adjusted_dt = parse_cet(last_open_row["adjusted_predicted_next_restock_cet"])

    raw_error_minutes = round((actual_restock_cet - raw_dt).total_seconds() / 60, 2)
    adjusted_error_minutes = round((actual_restock_cet - adjusted_dt).total_seconds() / 60, 2)

    prediction_ws.update(
        range_name=f"H{last_open_index}:J{last_open_index}",
        values=[[fmt_dt(actual_restock_cet), str(raw_error_minutes), str(adjusted_error_minutes)]]
    )

    print(
        f"Resolved prediction for {country} {item_name} with "
        f"actual_cet={fmt_dt(actual_restock_cet)} "
        f"raw_error_minutes={raw_error_minutes} "
        f"adjusted_error_minutes={adjusted_error_minutes}"
    )


def find_best_time_bucket(restock_times_cet):
    quarter_buckets = [((dt.hour), (dt.minute // 15) * 15) for dt in restock_times_cet]
    weekdays = [dt.weekday() for dt in restock_times_cet]

    common_bucket = Counter(quarter_buckets).most_common(1)[0][0]
    common_weekday = Counter(weekdays).most_common(1)[0][0]

    return common_bucket, common_weekday


def append_prediction(country, item_name):
    restock_rows = get_restock_rows(country, item_name)

    if len(restock_rows) < 3:
        print(
            f"Not enough restock history to predict for {country} {item_name}. "
            f"Need at least 3 restock rows, found {len(restock_rows)}."
        )
        return

    restock_times = [parse_cet(r["event_time"]) for r in restock_rows]

    raw_intervals = [
        restock_times[i] - restock_times[i - 1]
        for i in range(1, len(restock_times))
    ]

    filtered_intervals, removed_outliers = remove_interval_outliers(raw_intervals)
    weighted_interval = weighted_median_timedelta(filtered_intervals)

    last_restock = restock_times[-1]
    raw_prediction = last_restock + weighted_interval

    common_bucket, common_weekday = find_best_time_bucket(restock_times)

    adjusted_prediction = raw_prediction.replace(
        hour=common_bucket[0],
        minute=common_bucket[1],
        second=0,
        microsecond=0,
    )

    while adjusted_prediction <= last_restock:
        adjusted_prediction += timedelta(days=1)

    if adjusted_prediction.weekday() != common_weekday:
        days_ahead = (common_weekday - adjusted_prediction.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        adjusted_prediction += timedelta(days=days_ahead)

    travel_time = TRAVEL_TIMES[country]
    leave_by_time = adjusted_prediction - travel_time
    prediction_time = now_cet()

    notes = (
        f"intervals={len(raw_intervals)}; "
        f"used={len(filtered_intervals)}; "
        f"outliers_removed={len(removed_outliers)}; "
        f"common_bucket={common_bucket}; "
        f"common_weekday={common_weekday}"
    )

    prediction_row = [
        fmt_dt(prediction_time),
        country,
        item_name,
        fmt_dt(last_restock),
        str(weighted_interval),
        fmt_dt(raw_prediction),
        fmt_dt(adjusted_prediction),
        "",
        "",
        "",
        fmt_td(travel_time),
        fmt_dt(leave_by_time),
        notes,
    ]

    prediction_ws.append_row(prediction_row)

    print(
        f"Prediction row added for {country} {item_name}: "
        f"raw_prediction_cet={fmt_dt(raw_prediction)}, "
        f"adjusted_prediction_cet={fmt_dt(adjusted_prediction)}, "
        f"weighted_interval={weighted_interval}, "
        f"removed_outliers={len(removed_outliers)}"
    )


def refresh_predictions_from_history():
    for _, meta in TRACKED.items():
        append_prediction(meta["country"], meta["item_name"])


def main():
    ensure_prediction_headers()

    state = load_state()
    data = get_live_data()
    now = now_cet()
    now_str = fmt_dt(now)

    send_discord_message(f"Torn YATA Tracker test run at {now_str} (CET)")

    for code, meta in TRACKED.items():
        country_data = data["stocks"][code]
        xanax = find_xanax(country_data)

        if not xanax:
            print(f"No Xanax found for {meta['country']} ({code})")
            continue

        current_qty = int(xanax["quantity"])

        yata_update_cet = to_cet_from_timestamp(country_data["update"])
        previous_qty = state.get(code, {}).get("quantity")

        print(f"Checking {meta['country']} ({code})")
        print("Previous quantity:", previous_qty)
        print("Current quantity:", current_qty)

        if previous_qty is None:
            print("First run for this country; storing state only.")

        elif previous_qty == 0 and current_qty > 0:
            append_event(
                now,
                "restock",
                code,
                meta["country"],
                meta["item_id"],
                meta["item_name"],
                previous_qty,
                current_qty,
                yata_update_cet,
                "live_yata",
                "",
            )
            print("Restock event logged (CET).")

            send_discord_message(
                f"🔔 Restock detected (CET)\n"
                f"Country: {meta['country']}\n"
                f"Item: {meta['item_name']}\n"
                f"Previous quantity: {previous_qty}\n"
                f"Current quantity: {current_qty}\n"
                f"Checked at (CET): {now_str}\n"
                f"YATA update (CET): {fmt_dt(yata_update_cet)}"
            )

            actual_restock_cet = now
            resolve_previous_prediction(meta["country"], meta["item_name"], actual_restock_cet)

        elif previous_qty > 0 and current_qty == 0:
            append_event(
                now,
                "depletion",
                code,
                meta["country"],
                meta["item_id"],
                meta["item_name"],
                previous_qty,
                current_qty,
                yata_update_cet,
                "live_yata",
                "",
            )
            print("Depletion event logged (CET).")

            send_discord_message(
                f"⚠️ Depletion detected (CET)\n"
                f"Country: {meta['country']}\n"
                f"Item: {meta['item_name']}\n"
                f"Previous quantity: {previous_qty}\n"
                f"Current quantity: {current_qty}\n"
                f"Checked at (CET): {now_str}\n"
                f"YATA update (CET): {fmt_dt(yata_update_cet)}"
            )

        else:
            print("No event.")

        state[code] = {
            "quantity": current_qty,
            "yata_update_cet": fmt_dt(yata_update_cet),
        }

    refresh_predictions_from_history()
    save_state(state)
    print("Done.")


if __name__ == "__main__":
    main()
