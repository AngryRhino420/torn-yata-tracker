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

        "country":"UK",
        "item":"Xanax",
        "id":206,
        "travel":20

    },


    "jap": {

        "country":"Japan",
        "item":"Xanax",
        "id":206,
        "travel":30

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
# GOOGLE
# ==========================


def google_sheet():


    json_key = os.environ.get(
        "GOOGLE_SERVICE_ACCOUNT_JSON"
    )


    if not json_key:

        raise Exception(
            "Missing Google credentials"
        )


    with open(
        "google.json",
        "w"
    ) as f:

        f.write(json_key)



    creds = Credentials.from_service_account_file(
        "google.json"
    )


    client = gspread.authorize(
        creds
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


def discord(msg):


    hook = os.environ.get(
        "DISCORD_WEBHOOK_URL"
    )


    if hook:


        requests.post(

            hook,

            json={
                "content":msg
            },

            timeout=10

        )





# ==========================
# STATE
# ==========================


def load_state():


    rows = state_sheet.get_all_records()


    return {

        x["country"]:
        int(x["quantity"])

        for x in rows

    }





def save_state(country,qty):


    rows = state_sheet.get_all_records()


    for i,row in enumerate(rows,start=2):


        if row["country"]==country:


            state_sheet.update_cell(

                i,

                2,

                qty

            )

            return






# ==========================
# YATA
# ==========================


def get_yata():


    r=requests.get(

        YATA_URL,

        timeout=20

    )


    r.raise_for_status()


    return r.json()





def find_xanax(country):


    for x in country.get(
        "stocks",
        []
    ):


        if x.get(
            "name",
            ""
        ).lower()=="xanax":


            return x


    return None





# ==========================
# LEARNING ENGINE
# ==========================


def previous_prediction(country):


    rows = prediction_sheet.get_all_records()



    found=None



    for row in rows:


        if row["country"]==country:


            if row["actual_next_restock_cet"]=="":


                found=row



    return found






def update_prediction_accuracy(country, actual):


    pred = previous_prediction(
        country
    )


    if not pred:

        return



    predicted=datetime.strptime(

        pred["adjusted_predicted_next_restock_cet"],

        "%Y-%m-%d %H:%M:%S"

    ).replace(
        tzinfo=CET
    )



    error = int(

        (
            actual
            -
            predicted

        ).total_seconds()
        /
        60

    )



    rows=prediction_sheet.get_all_records()



    for i,row in enumerate(rows,start=2):


        if row["country"]==country and row["actual_next_restock_cet"]=="":



            prediction_sheet.update(

                f"H{i}:J{i}",

                [[

                    fmt(actual),

                    error,

                    error

                ]]

            )


            return






def learning_offset(country):


    rows=prediction_sheet.get_all_records()


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



    avg = statistics.mean(
        errors
    )



    return timedelta(

        minutes=avg

    )





# ==========================
# PREDICTION
# ==========================


def predict(country,info):


    rows=events_sheet.get_all_records()


    history=[]



    for r in rows:


        if (

            r["country"]==country

            and

            r["event_type"]=="restock"

        ):


            history.append(

                datetime.strptime(

                    r["event_time"],

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




    weighted = sum(

        x.total_seconds()*(i+1)

        for i,x in enumerate(intervals)

    ) / sum(

        range(
            1,
            len(intervals)+1
        )

    )



    interval=timedelta(

        seconds=weighted

    )



    last=history[-1]



    raw=last+interval



    correction = learning_offset(
        country
    )



    adjusted = raw + correction



    leave = adjusted - timedelta(

        minutes=info["travel"]

    )




    prediction_sheet.append_row(

        [

            fmt(now()),

            country,

            info["item"],

            fmt(last),

            str(interval),

            fmt(raw),

            fmt(adjusted),

            "",

            "",

            "",

            info["travel"],

            fmt(leave),

            f"Learning correction: {correction}"

        ]

    )



    return adjusted,leave





# ==========================
# MAIN
# ==========================


def main():


    print(
        "Running",
        fmt(now())
    )



    state=load_state()



    data=get_yata()



    for code,info in TRACKED.items():



        country_data=data["stocks"].get(
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



            update_prediction_accuracy(

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



            result=predict(

                info["country"],

                info

            )



            if result:


                nxt,leave=result


                discord(f"""

🔔 Xanax Restock Prediction

Country:
{info['country']}

Stock:
{qty}

Expected next:
{fmt(nxt)}

Leave Torn City:
{fmt(leave)}

Model:
Adaptive learning enabled

""")


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
        "Done"
    )





if __name__=="__main__":

    main()
