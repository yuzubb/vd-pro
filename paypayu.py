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
            "iosMinimumVersion":  "3.45.0",
            "androidMinimumVersion": "3.45.0"
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

        headers = {
            "Accept":        "application/json, text/plain, */*",
            'User-Agent':    ua.set(),
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {access_token}"
        }

        now_jst = datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=9))
        ).strftime('%Y-%m-%dT%H:%M:%S+0900')


        payload = {
            "client_uuid":           client_uuid,
            "requestAt":             now_jst,
            "amount":                amount,
            "theme":                 "default-sendmoney",
            "requestId":             str(uuid_module.uuid4()),
            "iosMinimumVersion":     "3.45.0",
            "androidMinimumVersion": "3.45.0"
        }

        if passcode:
            payload["passcode"] = passcode

        # 正しいエンドポイントが不明なため複数試す
        endpoints = [
            "https://www.paypay.ne.jp/app/v2/p2p-api/createP2PSendMoneyLink",
            "https://www.paypay.ne.jp/app/v1/p2p-api/createP2PSendMoneyLink",
            "https://www.paypay.ne.jp/app/v1/p2p-api/createMoneyDistributionLink",
        ]

        data = None
        for endpoint in endpoints:
            try:
                async with session.post(
                    endpoint, json=payload, headers=headers, proxy=PROXY_URL
                ) as resp:
                    if resp.status == 404:
                        print(f"CREATE_LINK_404: {endpoint}")
                        continue
                    resp.raise_for_status()
                    data = await resp.json()
                    print(f"CREATE_LINK_HIT: {endpoint}")
                    break
            except aiohttp.ClientError as e:
                print(f"CREATE_LINK_EXC ({endpoint}): {e}")
                continue

        if data is None:
            return False

        if data.get("header", {}).get("resultCode") != "S0000":
            print(f"CREATE_LINK_ERR: {data}")
            return False

        code = data["payload"].get("verificationCode")
        if not code:
            return False

        return {
            "url":    f"https://pay.paypay.ne.jp/{code}",
            "amount": amount
        }
