import aiohttp
import datetime
import uuid as uuid_module
from useragent_changer import UserAgent

ua = UserAgent('iphone')

PROXY_URL = None


# ── ログイン共通処理 ───────────────────────────────────────────────────────────

async def _get_access_token(session: aiohttp.ClientSession, phoneNumber: str, password: str, client_uuid: str, referer: str) -> str | None:
    """ログインしてaccess_tokenを返す。失敗時はNone。"""
    payload = {
        "scope":          "SIGN_IN",
        "client_uuid":    client_uuid,
        "grant_type":     "password",
        "username":       phoneNumber,
        "password":       password,
        "add_otp_prefix": True,
        "language":       "ja"
    }
    headers = {
        'User-Agent':   ua.set(),
        'Accept':       'application/json, text/plain, */*',
        'Content-Type': 'application/json',
        'Origin':       'https://www.paypay.ne.jp',
        'Referer':      referer,
    }
    async with session.post(
        "https://www.paypay.ne.jp/app/v1/oauth/token",
        headers=headers, json=payload, proxy=PROXY_URL
    ) as resp:
        data = await resp.json()
        return data.get("access_token")


# ── 公開関数 ──────────────────────────────────────────────────────────────────

async def login(phoneNumber: str, password: str, uuid: str):
    headers = {
        'User-Agent':   ua.set(),
        'Accept':       'application/json, text/plain, */*',
        'Content-Type': 'application/json',
        'Origin':       'https://www.paypay.ne.jp',
        'Referer':      'https://www.paypay.ne.jp/app/account/sign-in',
    }
    payload = {
        "scope":          "SIGN_IN",
        "client_uuid":    uuid,
        "grant_type":     "password",
        "username":       phoneNumber,
        "password":       password,
        "add_otp_prefix": True,
        "language":       "ja"
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://www.paypay.ne.jp/app/v1/oauth/token",
            headers=headers, json=payload, proxy=PROXY_URL
        ) as resp:
            return await resp.json()


async def login_otp(set_uuid, otp, otpid, otp_pre):
    headers = {
        'User-Agent':   ua.set(),
        'Accept':       'application/json, text/plain, */*',
        'Content-Type': 'application/json',
        'Origin':       'https://www.paypay.ne.jp',
        'Referer':      'https://www.paypay.ne.jp/app/account/sign-in',
    }
    payload = {
        "scope":              "SIGN_IN",
        "client_uuid":        set_uuid,
        "grant_type":         "otp",
        "otp_prefix":         str(otp_pre),
        "otp":                otp,
        "otp_reference_id":   otpid,
        "username_type":      "MOBILE",
        "language":           "ja"
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://www.paypay.ne.jp/app/v1/oauth/token",
            headers=headers, json=payload, proxy=PROXY_URL
        ) as resp:
            data = await resp.json()
            try:
                if data["response_type"] == "ErrorResponse":
                    return "ERR"
            except KeyError:
                return "OK"


async def check_link(cd: str):
    if "https://" in cd:
        cd = cd.replace("https://pay.paypay.ne.jp/", "")

    headers = {
        "Accept":       "application/json, text/plain, */*",
        'User-Agent':   ua.set(),
        "Content-Type": "application/json"
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(
                f"https://www.paypay.ne.jp/app/v2/p2p-api/getP2PLinkInfo?verificationCode={cd}",
                headers=headers, proxy=PROXY_URL
            ) as resp:
                resp.raise_for_status()
                link_info = await resp.json()
        except aiohttp.ClientError as e:
            print(f"API_REQ_EXC: {e}")
            return False

    if link_info.get("header", {}).get("resultCode") != "S0000":
        return False

    if link_info.get("payload", {}).get("orderStatus") == "PENDING":
        return link_info
    return False


async def link_rev(cd: str, phoneNumber: str, password: str, uuid: str, link_password: str = None):
    if "https://" in cd:
        cd = cd.replace("https://pay.paypay.ne.jp/", "")

    async with aiohttp.ClientSession() as session:
        base_headers = {
            "Accept":       "application/json, text/plain, */*",
            'User-Agent':   ua.set(),
            "Content-Type": "application/json"
        }

        try:
            async with session.get(
                f"https://www.paypay.ne.jp/app/v2/p2p-api/getP2PLinkInfo?verificationCode={cd}",
                headers=base_headers, proxy=PROXY_URL
            ) as resp:
                resp.raise_for_status()
                link_info = await resp.json()

            if link_info.get("payload", {}).get("orderStatus") != "PENDING":
                return False

            if link_info.get("payload", {}).get("pendingP2PInfo", {}).get("isSetPasscode") and link_password is None:
                return False

        except aiohttp.ClientError as e:
            print(f"LINK_REQ_EXC: {e}")
            return False

        access_token = await _get_access_token(
            session, phoneNumber, password, uuid,
            referer="https://pay.paypay.ne.jp/" + cd
        )
        if not access_token:
            return "LOGINERR"

        base_headers["Authorization"] = f"Bearer {access_token}"

        now_jst = datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=9))
        ).strftime('%Y-%m-%dT%H:%M:%S+0900')

        receive_payload = {
            "verificationCode":   cd,
            "client_uuid":        uuid,
            "requestAt":          now_jst,
            "requestId":          link_info["payload"]["message"]["data"]["requestId"],
            "orderId":            link_info["payload"]["message"]["data"]["orderId"],
            "senderMessageId":    link_info["payload"]["message"]["messageId"],
            "senderChannelUrl":   link_info["payload"]["message"]["chatRoomId"],
            "iosMinimumVersion":  "5.52.0",
            "androidMinimumVersion": "5.52.0"
        }

        if link_password:
            receive_payload["passcode"] = link_password

        try:
            async with session.post(
                "https://www.paypay.ne.jp/app/v2/p2p-api/acceptP2PSendMoneyLink",
                json=receive_payload, headers=base_headers, proxy=PROXY_URL
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data.get("header", {}).get("resultCode") == "S0000"

        except aiohttp.ClientError as e:
            print(f"REVERR: {e}")
            return False


async def create_link(phoneNumber: str, password: str, client_uuid: str, amount: int, passcode: str = None) -> dict | str:
    """
    送金リンクを作成する。
    戻り値:
        成功 → {"url": "https://pay.paypay.ne.jp/...", "amount": amount}
        ログイン失敗 → "LOGINERR"
        作成失敗 → False
    """
    async with aiohttp.ClientSession() as session:
        access_token = await _get_access_token(
            session, phoneNumber, password, client_uuid,
            referer="https://www.paypay.ne.jp/app/cashier/send-money"
        )
        if not access_token:
            return "LOGINERR"

        now_jst = datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=9))
        ).strftime('%Y-%m-%dT%H:%M:%S+0900')

        headers = {
            "Host":              "app4.paypay.ne.jp",
            "Client-Version":    "5.52.0",
            "System-Locale":     "ja",
            "User-Agent":        "PaypayApp/5.52.0 CFNetwork/3826.400.120 Darwin/24.3.0",
            "Network-Status":    "WIFI",
            "Device-Name":       "iPhone16,2",
            "Client-Os-Type":    "IOS",
            "Client-Mode":       "NORMAL",
            "Client-Type":       "PAYPAYAPP",
            "Accept-Language":   "ja-jp",
            "Timezone":          "Asia/Tokyo",
            "Accept":            "*/*",
            "Client-Uuid":       client_uuid,
            "Client-Os-Version": "18.3.2",
            "Content-Type":      "application/json",
            "Authorization":     f"Bearer {access_token}"
        }

        payload = {
            "androidMinimumVersion": "5.52.0",
            "requestId":             str(uuid_module.uuid4()).upper(),
            "requestAt":             now_jst,
            "theme":                 "default-sendmoney",
            "amount":                int(amount),
            "iosMinimumVersion":     "5.52.0"
        }

        if passcode:
            payload["passcode"] = passcode

        try:
            async with session.post(
                "https://app4.paypay.ne.jp/bff/v2/executeP2PSendMoneyLink",
                json=payload,
                headers=headers,
                params={"payPayLang": "ja"},
                proxy=PROXY_URL
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

            if data.get("header", {}).get("resultCode") != "S0000":
                print(f"CREATE_LINK_ERR: {data}")
                return False

            # verificationCode を取得してURLを組み立て
            code = (
                data.get("payload", {}).get("verificationCode")
                or data.get("payload", {}).get("linkCode")
            )
            if not code:
                print(f"CREATE_LINK_NO_CODE: {data}")
                return False

            return {
                "url":    f"https://pay.paypay.ne.jp/{code}",
                "amount": amount
            }

        except aiohttp.ClientError as e:
            print(f"CREATE_LINK_EXC: {e}")
            return False
