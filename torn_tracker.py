import json
import os
import statistics
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
import gspread


CET = ZoneInfo("Europe/Berlin")

STATE_FILE = "tracker_state.json"

SHEET_URL = "https://docs.google.com/spreadsheets/d/1txgKmKuLZB3iGpsLG8U-j_Z5gfyMdr_lKXNfNZNI2es/edit?gid=0#gid=0"

YATA_URL = "https://yata.yt/api/v1/travel/export/"


TRACKED = {
    "uni": {
        "country": "UK",
        "item": "Xanax",
        "id": 206
    },

    "jap": {
        "country": "Japan",
        "item": "Xanax",
        "id":206
    }
}



def now():
    return datetime.now(CET)


def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")



def google_sheet():

    creds = os.environ.get(
        "GOOGLE_SERVICE_ACCOUNT_JSON"
    )

    if not creds:
        raise Exception(
            "Missing GOOGLE_SERVICE_ACCOUNT_JSON"
        )


    with open(
        "google.json",
        "w"
    ) as f:
        f.write(creds)


    client = gspread.service_account(
        "google.json"
    )

    return client.open_by_url(
        SHEET_URL
    )




sheet = google_sheet()

events = sheet.sheet1


try:
    prediction_sheet = sheet.worksheet(
        "prediction"
    )

except:

    prediction_sheet = sheet.add_worksheet(
        "prediction",
        1000,
        20
    )





def discord(message):

    hook = os.environ.get(
        "DISCORD_WEBHOOK_URL"
    )


    if hook:

        requests.post(
            hook,
            json={
                "content":message
            }
        )





def load_state():

    if os.path.exists(
        STATE_FILE
    ):

        return json.load(
            open(STATE_FILE)
        )

    return {}




def save_state(state):

    json.dump(
        state,
        open(
            STATE_FILE,
            "w"
        ),
        indent=2
    )





def get_yata():

    r=requests.get(
        YATA_URL,
        timeout=20
    )

    r.raise_for_status()

    return r.json()





def find_xanax(country):

    for item in country["stocks"]:

        if item["name"].lower()=="xanax":

            return item



    return None





def predict(country):

    rows = events.get_all_records()


    history=[]


    for row in rows:

        if (

            row.get("event_type")=="restock"

            and row.get("country")==country

        ):

            history.append(

                datetime.strptime(

                    row["event_time"],

                    "%Y-%m-%d %H:%M:%S"

                ).replace(
                    tzinfo=CET
                )

            )


    if len(history)<3:

        return



    intervals=[]


    for i in range(1,len(history)):

        intervals.append(
            history[i]-history[i-1]
        )



    median = statistics.median(
        intervals
    )


    next_time = history[-1]+median


    prediction_sheet.append_row(

        [

        fmt(now()),

        country,

        "Xanax",

        fmt(history[-1]),

        fmt(next_time)

        ]

    )





def main():

    print(
        "Tracker started",
        fmt(now())
    )


    discord(
        "🟢 Torn Xanax tracker running " + fmt(now())
    )



    state=load_state()


    data=get_yata()



    for code,info in TRACKED.items():


        xanax=find_xanax(
            data["stocks"][code]
        )


        qty=int(
            xanax["quantity"]
        )


        old=state.get(
            code
        )



        print(
            info["country"],
            "old:",
            old,
            "new:",
            qty
        )



        # first run

        if old is None:


            events.append_row(

            [

            fmt(now()),

            "startup",

            code,

            info["country"],

            info["id"],

            info["item"],

            "",

            qty

            ]

            )



        elif old==0 and qty>0:


            events.append_row(

            [

            fmt(now()),

            "restock",

            code,

            info["country"],

            info["id"],

            info["item"],

            old,

            qty

            ]

            )



            discord(

                f"🔔 Xanax restock {info['country']} {qty}"
            )


            predict(
                info["country"]
            )



        elif old>0 and qty==0:


            events.append_row(

            [

            fmt(now()),

            "depletion",

            code,

            info["country"],

            info["id"],

            info["item"],

            old,

            qty

            ]

            )



        state[code]=qty



    save_state(state)



    print(
        "Finished"
    )




if __name__=="__main__":

    main()
