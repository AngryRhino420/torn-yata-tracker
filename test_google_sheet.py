import gspread

SHEET_URL = "https://docs.google.com/spreadsheets/d/1txgKmKuLZB3iGpsLG8U-j_Z5gfyMdr_lKXNfNZNI2es/edit?gid=0#gid=0"

gc = gspread.service_account(filename="google-service-account.json")
sh = gc.open_by_url(SHEET_URL)
ws = sh.sheet1

row = [
    "2026-06-21 15:10:00",
    "test",
    "uni",
    "UK",
    "206",
    "Xanax",
    "0",
    "0",
    "2026-06-21 15:10:00",
    "python_test",
    "connection test"
]

ws.append_row(row)
print("Success: test row added to Google Sheet")