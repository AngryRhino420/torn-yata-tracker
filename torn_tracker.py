import os
import statistics
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
import gspread
from google.oauth2.service_account import Credentials


# ==========================
# CONFIG
# ==========================

CET = ZoneInfo("Europe/Berlin")


SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1txgKmKuLZB3iGpsLG8U-j_Z5gfyMdr_lKXNfNZNI2es/edit"
)


YATA_URL = (
    "https://yata.yt/api/v1/travel/export/"
)



TRACKED = {


    "uni": {

        "country": "UK",
        "item": "Xanax",
        "id": 206,
        "travel": 20

    },


    "jap": {

        "country": "Japan",
        "item": "Xanax",
        "id": 206,
        "travel": 30

    }


}



# ==========================
# TIME
# ==========================


def now():

    return datetime.now(CET)



def fmt(dt):

    return dt.strftime(
        "%Y-%m-%d %H:%M:%S"
    )



# ==========================
# GOOGLE SHEETS
# ==========================


def google_sheet():


    creds_json = os.environ.get(
        "GOOGLE_SERVICE_ACCOUNT_JSON"
    )


    if not creds_json:

        raise Exception(
            "Missing GOOGLE_SERVICE_ACCOUNT_JSON"
        )



    with open(
        "google.json",
        "w"
    ) as f:

        f.write(
            creds_json
        )



    credentials = Credentials.from_service_account_file(
        "google.json"
    )


    client = gspread.authorize(
        credentials
    )


    return client.open_by_url(
        SHEET_URL
    )




sheet = google_sheet()



events_sheet = sheet.worksheet(
    "events"
)


prediction_sheet = sheet.worksheet(
    "prediction"
)


state_sheet = sheet.worksheet(
    "state"
)



# ==========================
# DISCORD
# ==========================


def discord(message):


    webhook = os.environ.get(
        "DISCORD_WEBHOOK_URL"
    )


    if webhook:


        requests.post(

            webhook,

            json={
                "content": message
            },

            timeout=10

        )





# ==========================
# STATE
# ==========================


def load_state():


    rows = state_sheet.get_all_records()


    result = {}


    for row in rows:


        result[
            row["country"]
        ] = int(
            row["quantity"]
        )


    return result




def save_state(country, qty):


    rows = state_sheet.get_all_records()



    for index,row in enumerate(rows, start=2):


        if row["country"] == country:


            state_sheet.update_cell(

                index,

                2,

                qty

            )

            return





# ==========================
# YATA
# ==========================


def get_yata():

    response = requests.get(

        YATA_URL,

        timeout=20

    )


    response.raise_for_status()


    return response.json()





def find_xanax(country):


    for item in country.get(
        "stocks",
        []
    ):


        if item.get(
            "name",
            ""
        ).lower()=="xanax":


            return item



    return None




# ==========================
# PREDICTION
# ==========================


def predict(country, info):


    rows = events_sheet.get_all_records()


    restocks=[]



    for row in rows:


        if (

            row["event_type"]=="restock"

            and row["country"]==country

        ):


            restocks.append(

                datetime.strptime(

                    row["event_time"],

                    "%Y-%m-%d %H:%M:%S"

                ).replace(
                    tzinfo=CET
                )

            )



    if len(restocks)<3:

        return None




    intervals=[]



    for i in range(1,len(restocks)):


        intervals.append(

            restocks[i]-restocks[i-1]

        )




    weighted_seconds = sum(

        x.total_seconds()*(i+1)

        for i,x in enumerate(intervals)

    ) / sum(

        range(
            1,
            len(intervals)+1
        )

    )



    weighted_interval = timedelta(

        seconds=weighted_seconds

    )



    last = restocks[-1]



    raw_prediction = (
        last
        +
        weighted_interval
    )



    adjusted_prediction = raw_prediction




    leave_time = (

        adjusted_prediction

        -
        timedelta(
            minutes=info["travel"]
        )

    )



    prediction_sheet.append_row(

        [

            fmt(now()),

            country,

            info["item"],

            fmt(last),

            str(weighted_interval),

            fmt(raw_prediction),

            fmt(adjusted_prediction),

            "",

            "",

            "",

            info["travel"],

            fmt(leave_time),

            "Weighted interval model"

        ]

    )



    return {

        "next": adjusted_prediction,

        "leave": leave_time

    }





# ==========================
# MAIN
# ==========================


def main():


    print(
        "Tracker running",
        fmt(now())
    )



    state = load_state()



    data = get_yata()



    for code,info in TRACKED.items():



        country_data = data["stocks"].get(
            code
        )



        if not country_data:

            continue




        xanax = find_xanax(
            country_data
        )



        if not xanax:

            continue



        qty=int(

            xanax.get(
                "quantity",
                0
            )

        )



        old = state.get(

            info["country"],

            0

        )



        print(

            info["country"],

            old,

            qty

        )



        # RESTOCK

        if old==0 and qty>0:



            events_sheet.append_row(

                [

                    fmt(now()),

                    "restock",

                    code,

                    info["country"],

                    info["id"],

                    info["item"],

                    old,

                    qty,

                    fmt(now()),

                    "YATA",

                    ""

                ]

            )



            prediction = predict(

                info["country"],

                info

            )



            if prediction:


                discord(

f"""
🔔 Xanax Restock Prediction

Country:
{info['country']}

Current stock:
{qty}

Next expected restock:
{fmt(prediction['next'])}

Leave Torn City:
{fmt(prediction['leave'])}

Travel time:
{info['travel']} minutes
"""

                )


            else:


                discord(

                    f"🔔 Xanax restock detected: {info['country']} ({qty})"

                )



        # DEPLETION


        elif old>0 and qty==0:



            events_sheet.append_row(

                [

                    fmt(now()),

                    "depletion",

                    code,

                    info["country"],

                    info["id"],

                    info["item"],

                    old,

                    qty,

                    fmt(now()),

                    "YATA",

                    ""

                ]

            )



        save_state(

            info["country"],

            qty

        )



    print(
        "Finished"
    )





if __name__=="__main__":

    main()
