import os
import json
import gspread

CREDS_FILE = "google-service-account.json"

if os.path.exists(CREDS_FILE):
    gc = gspread.service_account(filename=CREDS_FILE)
else:
    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_json:
        raise RuntimeError(
            "Missing Google credentials. Expected either "
            "'google-service-account.json' file or "
            "'GOOGLE_SERVICE_ACCOUNT_JSON' environment variable."
        )

    with open(CREDS_FILE, "w", encoding="utf-8") as f:
        f.write(creds_json)

    gc = gspread.service_account(filename=CREDS_FILE)
