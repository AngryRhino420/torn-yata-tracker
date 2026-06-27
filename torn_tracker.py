import json
import os
import statistics
from datetime import datetime, timedelta
from collections import Counter
from zoneinfo import ZoneInfo

import requests
import gspread



CET = ZoneInfo("Europe/Berlin")
UTC = ZoneInfo("UTC")



STATE_FILE = "tracker_state.json"



SHEET_URL = "https://docs.google.com/spreadsheets/d/1txgKmKuLZB3iGpsLG8U-j_Z5gfyMdr_lKXNfNZNI2es/edit"



YATA_URL = "https://yata.yt/api/v1/travel/export/"



TRACKED = {

    "uni":
    {
        "country":"UK",
        "item":"Xanax"
    },


    "jap":
    {
        "country":"Japan",
        "item":"Xanax"
    }

}



TRAVEL = {

    "UK": timedelta(hours=1,minutes=47),

    "Japan": timedelta(hours=2,minutes=22)

}



HEADERS = [

"prediction_time",

"country",

"item",

"last_restock",

"prediction",

"leave_by",

"actual",

"error"

]





def google():

    data=os.environ.get(
        "GOOGLE_SERVICE_ACCOUNT_JSON"
    )

    if not data:

        raise Exception(
            "Missing Google secret"
        )


    with open(
        "google.json",
        "w"
    ) as f:

        f.write(data)



    return gspread.service_account(
        "google.json"
    )





gc=google()

sheet=gc.open_by_url(
    SHEET_URL
)


events=sheet.sheet1



try:

    predictions=sheet.worksheet(
        "prediction"
    )

except:

    predictions=sheet.add_worksheet(
        "prediction",
        1000,
        10
    )





def discord(msg):

    url=os.environ.get(
        "DISCORD_WEBHOOK_URL"
    )

    if url:

        requests.post(
            url,
            json={"content":msg}
        )





def now():

    return datetime.now(CET)



def fmt(t):

    return t.strftime(
        "%Y-%m-%d %H:%M:%S"
    )





def load():

    if os.path.exists(
        STATE_FILE
    ):

        return json.load(
            open(STATE_FILE)
        )

    return {}




def save(x):

    json.dump(
        x,
        open(
            STATE_FILE,
            "w"
        ),
        indent=2
    )





def yata():

    r=requests.get(
        YATA_URL
    )

    r.raise_for_status()

    return r.json()





def xanax(country):

    for x in country["stocks"]:

        if x["name"].lower()=="xanax":

            return x





def restocks(country):

    rows=events.get_all_records()

    result=[]


    for r in rows:

        if (

            r["event_type"]=="restock"

            and r["country"]==country

        ):

            result.append(

                datetime.strptime(

                    r["event_time"],

                    "%Y-%m-%d %H:%M:%S"

                ).replace(
                    tzinfo=CET
                )

            )


    return sorted(result)





def predict(country):

    history=restocks(country)


    if len(history)<3:

        return



    intervals=[]


    for i in range(1,len(history)):

        intervals.append(
            history[i]-history[i-1]
        )



    interval=statistics.median(
        intervals
    )



    prediction=history[-1]+interval



    leave=prediction-TRAVEL[country]



    predictions.append_row(

        [

        fmt(now()),

        country,

        "Xanax",

        fmt(history[-1]),

        fmt(prediction),

        fmt(leave),

        "",

        ""

        ]

    )





def main():


    data=yata()


    state=load()



    for key,item in TRACKED.items():


        stock=xanax(
            data["stocks"][key]
        )


        qty=int(
            stock["quantity"]
        )


        old=state.get(
            key,
            {}
        ).get(
            "qty"
        )



        if old==0 and qty>0:


            events.append_row(

            [

            fmt(now()),

            "restock",

            key,

            item["country"],

            206,

            "Xanax",

            old,

            qty

            ]

            )



            discord(

            f"🔔 Xanax restock\n{item['country']}\nStock: {qty}"

            )



            predict(
                item["country"]
            )



        if old and qty==0:


            discord(

            f"⚠ Xanax depleted\n{item['country']}"

            )



        state[key]={

            "qty":qty

        }



    save(state)






if __name__=="__main__":

    main()
