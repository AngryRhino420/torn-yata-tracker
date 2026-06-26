import requests

url = "https://yata.yt/api/v1/travel/export/"
data = requests.get(url, timeout=20).json()

for code in ["uni", "jap"]:
    country = data["stocks"][code]
    xanax = None

    for item in country["stocks"]:
        if item["name"].lower() == "xanax":
            xanax = item
            break

    if xanax:
        print("Country code:", code)
        print("Quantity:", xanax["quantity"])
        print("Cost:", xanax["cost"])
        print("YATA update:", country["update"])
        print("-----")