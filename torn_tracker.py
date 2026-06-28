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


CET = ZoneInfo(
    "Europe/Berlin"
)


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


    json_key = os.environ.get(
        "GOOGLE_SERVICE_ACCOUNT_JSON"
    )


    if not json_key:

        raise Exception(
            "Missing GOOGLE_SERVICE_ACCOUNT_JSON"
        )



    with open(
        "google.json",
        "w"
    ) as f:

        f.write(json_key)



    SCOPES = [

        "https://www.googleapis.com/auth/spreadsheets",

        "https://www.googleapis.com/auth/drive"

    ]



    credentials = Credentials.from_service_account_file(

        "google.json",

        scopes=SCOPES

    )



    client = gspread.authorize(
        credentials
    )



    return client.open_by_url(
        SHEET_URL
    )





book = google_sheet()



events_sheet = book.worksheet(
    "events"
)


prediction_sheet = book.worksheet(
    "prediction"
)


state_sheet = book.worksheet(
    "state"
)





# ==========================
# DISCORD
# ==========================


def discord(message):


    hook = os.environ.get(
        "DISCORD_WEBHOOK_URL"
    )


    if hook:


        requests.post(

            hook,

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



    return {


        row["country"]:
        int(row["quantity"])


        for row in rows

    }






def save_state(country, quantity):


    rows = state_sheet.get_all_records()



    for index,row in enumerate(rows,start=2):


        if row["country"] == country:


            state_sheet.update_cell(

                index,

                2,

                quantity

            )


            return







# ==========================
# YATA
# ==========================


def get_yata():


    r = requests.get(

        YATA_URL,

        timeout=20

    )


    r.raise_for_status()


    return r.json()





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
# LEARNING
# ==========================


def get_previous_prediction(country):


    rows = prediction_sheet.get_all_records()


    latest=None



    for row in rows:


        if row["country"] == country:


            if row["actual_next_restock_cet"] == "":


                latest=row



    return latest






def update_prediction_error(country, actual):


    prediction = get_previous_prediction(
        country
    )


    if not prediction:

        return



    predicted=datetime.strptime(

        prediction["adjusted_predicted_next_restock_cet"],

        "%Y-%m-%d %H:%M:%S"

    ).replace(
        tzinfo=CET
    )



    error=int(

        (
            actual - predicted

        ).total_seconds()
        /
        60

    )



    rows=prediction_sheet.get_all_records()



    for index,row in enumerate(rows,start=2):


        if (

            row["country"]==country

            and

            row["actual_next_restock_cet"]==""

        ):



            prediction_sheet.update(

                f"H{index}:J{index}",

                [[

                    fmt(actual),

                    error,

                    error

                ]]

            )


            return






def learning_adjustment(country):


    rows = prediction_sheet.get_all_records()


    errors=[]



    for row in rows:


        if row["country"]==country:


            try:

                errors.append(

                    int(
                        row["adjusted_error_minutes"]
                    )

                )

            except:

                pass



    if len(errors)<3:

        return timedelta(0)



    avg = statistics.mean(errors)



    return timedelta(

        minutes=avg

    )







# ==========================
# PREDICT
# ==========================


def predict(country, info):


    rows = events_sheet.get_all_records()



    history=[]



    for row in rows:


        if (

            row["country"]==country

            and

            row["event_type"]=="restock"

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

        return None





    intervals=[]


    for i in range(1,len(history)):


        intervals.append(

            history[i]-history[i-1]

        )




    weighted_seconds=sum(

        interval.total_seconds()*(i+1)

        for i,interval in enumerate(intervals)

    ) / sum(

        range(
            1,
            len(intervals)+1
        )

    )



    weighted_interval=timedelta(

        seconds=weighted_seconds

    )



    last=history[-1]



    raw_prediction = (

        last

        +

        weighted_interval

    )



    correction = learning_adjustment(
        country
    )



    adjusted_prediction = (

        raw_prediction

        +

        correction

    )



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

            f"Learning correction {correction}"

        ]

    )




    return adjusted_prediction, leave_time







# ==========================
# MAIN
# ==========================


def main():


    print(

        "Tracker started",

        fmt(now())

    )



    state=load_state()



    yata=get_yata()




    for code,info in TRACKED.items():



        country_data = yata["stocks"].get(
            code
        )



        if not country_data:

            continue




        xanax=find_xanax(
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



        old=state.get(

            info["country"],

            0

        )




        # RESTOCK


        if old==0 and qty>0:



            actual=now()



            update_prediction_error(

                info["country"],

                actual

            )



            events_sheet.append_row(

                [

                    fmt(actual),

                    "restock",

                    code,

                    info["country"],

                    info["id"],

                    info["item"],

                    old,

                    qty,

                    fmt(actual),

                    "YATA",

                    ""

                ]

            )



            prediction=predict(

                info["country"],

                info

            )



            if prediction:


                next_time,leave=prediction



                discord(f"""

🔔 Xanax Restock Prediction

Country:
{info['country']}

Current stock:
{qty}

Expected next restock:
{fmt(next_time)}

Leave Torn City:
{fmt(leave)}

Model:
Adaptive learning enabled

""")


            else:


                discord(

                    f"🔔 Xanax restock detected {info['country']} ({qty})"

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
