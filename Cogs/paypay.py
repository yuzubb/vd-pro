import discord

from discord import ui

from discord.ext import commands

from discord import app_commands

import json

import os

import re

import uuid

from utils import is_allowed, OWNER_ID

import paypayu



PAYPAY_DATA_FILE = "paypay_data.json"

VENDING_DATA_FILE = "vending_data.json"

PAYPAY_LINK_PATTERN = re.compile(r'https://pay\.paypay\.ne\.jp/[A-Za-z0-9]+')



def load_vending_data():

    if os.path.exists(VENDING_DATA_FILE):

        try:

            with open(VENDING_DATA_FILE, "r", encoding="utf-8") as f:

                return json.load(f)

        except json.JSONDecodeError:

            print(f"Error: {VENDING_DATA_FILE} のJSON形式が不正です。")

            return {}

    return {}



def save_vending_data(data):

    with open(VENDING_DATA_FILE, "w", encoding="utf-8") as f:

        json.dump(data, f, indent=4, ensure_ascii=False)



def load_paypay_data():

    if os.path.exists(PAYPAY_DATA_FILE):

        with open(PAYPAY_DATA_FILE, "r", encoding="utf-8") as f:

            return json.load(f)

    return {}



def save_paypay_data(data):

    with open(PAYPAY_DATA_FILE, "w", encoding="utf-8") as f:

        json.dump(data, f, indent=4, ensure_ascii=False)





def build_link_embed(link_url: str, link_info: dict) -> discord.Embed:

    payload = link_info.get("payload", {})

    p2p_info = payload.get("pendingP2PInfo", {})

    message_data = payload.get("message", {}).get("data", {})



    amount = p2p_info.get("amount", 0)



    sub_wallet_split = message_data.get("subWalletSplit", {})

    sender_emoney = sub_wallet_split.get("senderEmoneyAmount", 0)

    sender_prepaid = sub_wallet_split.get("senderPrepaidAmount", 0)



    sender_display_name = p2p_info.get("userDisplayName", "不明")

    if not sender_display_name or sender_display_name == "不明":

        sender_display_name = payload.get("sender", {}).get("displayName", "不明")



    sender_photo_url = p2p_info.get("imageUrl") or payload.get("sender", {}).get("photoUrl")



    order_id = p2p_info.get("orderId", message_data.get("orderId", "不明"))



    expired_at = p2p_info.get("expiredAt", "")

    if expired_at:

        expired_at = expired_at.replace("T", " ").replace("Z", "")[:19]

    else:

        expired_at = "不明"



    is_passcode = p2p_info.get("isSetPasscode", False)

    passcode_status = "あり" if is_passcode else "なし"



    if sender_emoney > 0 and sender_prepaid > 0:

        amount_display = f"```総合: ¥{amount:,}``` ```マネー: ¥{sender_emoney:,}``` ```マネーライト: ¥{sender_prepaid:,}```"

    elif sender_emoney > 0:

        amount_display = f"```総合: ¥{amount:,}``` ```マネー: ¥{sender_emoney:,}```"

    else:

        amount_display = f"```総合: ¥{amount:,}``` ```マネーライト: ¥{sender_prepaid:,}```"



    description = f"""**送信者**

```{sender_display_name}```

**金額**

{amount_display}

**注文ID**

```{order_id}```

**パスワード / ステータス / 有効期限**

`{passcode_status}` / `受け取り待ち` / `{expired_at}`

**リンク**

<{link_url}>"""



    embed = discord.Embed(

        title="PayPayリンク検出",

        description=description,

        color=discord.Color.green()

    )

    if sender_photo_url:

        embed.set_thumbnail(url=sender_photo_url)



    return embed





class ApproveLinkView(ui.View):

    """

    リンクを貼った送信者だけが操作できるView。

    許可→オーナーのPayPayで自動受け取り / 拒否→キャンセル

    """



    def __init__(self, link_url: str, link_info: dict, sender_id: int):

        super().__init__(timeout=300)

        self.link_url = link_url

        self.link_info = link_info

        self.sender_id = sender_id

        self.done = False



    async def interaction_check(self, interaction: discord.Interaction) -> bool:

        if interaction.user.id != self.sender_id:

            await interaction.response.send_message(

                "❌ このボタンはリンクを送信した本人のみ操作できます。",

                ephemeral=True

            )

            return False

        return True



    def _disable_all(self):

        for item in self.children:

            item.disabled = True



    @ui.button(label="✅ 受け取りを許可する", style=discord.ButtonStyle.success)

    async def approve_button(self, interaction: discord.Interaction, button: ui.Button):

        if self.done:

            await interaction.response.send_message("⚠️ すでに処理済みです。", ephemeral=True)

            return



        await interaction.response.defer()



        paypay_data = load_paypay_data()

        owner_id_str = str(OWNER_ID)



        if owner_id_str not in paypay_data:

            await interaction.followup.send(

                "⚠️ オーナーのPayPayアカウントが未登録です。`/paypayログイン` で登録してください。",

                ephemeral=True

            )

            return



        is_passcode = self.link_info.get("payload", {}).get("pendingP2PInfo", {}).get("isSetPasscode", False)

        if is_passcode:

            await interaction.followup.send(

                "⚠️ パスコード付きリンクは自動受け取りできません。",

                ephemeral=True

            )

            return



        user_paypay = paypay_data[owner_id_str]

        result = await paypayu.link_rev(

            self.link_url,

            user_paypay.get("phone"),

            user_paypay.get("password"),

            user_paypay.get("uuid")

        )



        self.done = True

        self._disable_all()



        if result is True:

            button.label = "✅ 受け取り済み"

            button.style = discord.ButtonStyle.secondary

            await interaction.message.edit(view=self)

            await interaction.followup.send("✅ 受け取りが完了しました！", ephemeral=True)

        elif result == "LOGINERR":

            await interaction.message.edit(view=self)

            await interaction.followup.send(

                "❌ PayPayログインに失敗しました。オーナーは `/paypayログイン` で再登録してください。",

                ephemeral=True

            )

        else:

            await interaction.message.edit(view=self)

            await interaction.followup.send(

                "❌ 受け取りに失敗しました。リンクの有効期限切れ、またはすでに受け取られた可能性があります。",

                ephemeral=True

            )



    @ui.button(label="❌ 拒否する", style=discord.ButtonStyle.danger)

    async def deny_button(self, interaction: discord.Interaction, button: ui.Button):

        if self.done:

            await interaction.response.send_message("⚠️ すでに処理済みです。", ephemeral=True)

            return



        self.done = True

        self._disable_all()

        button.label = "❌ 拒否済み"

        await interaction.response.edit_message(view=self)

        await interaction.followup.send("受け取りを拒否しました。", ephemeral=True)





class OTPView(ui.View):

    def __init__(self, phone, password, set_uuid, otpid, otp_pre):

        super().__init__(timeout=300)

        self.phone = phone

        self.password = password

        self.set_uuid = set_uuid

        self.otpid = otpid

        self.otp_pre = otp_pre



    @ui.button(label="OTPコードを入力する", style=discord.ButtonStyle.primary)

    async def enter_otp(self, interaction: discord.Interaction, button: ui.Button):

        modal = OTPModal(self.phone, self.password, self.set_uuid, self.otpid, self.otp_pre)

        await interaction.response.send_modal(modal)





class OTPModal(ui.Modal, title="PayPay OTP認証"):

    def __init__(self, phone, password, set_uuid, otpid, otp_pre):

        super().__init__(timeout=300)

        self.phone = phone

        self.password = password

        self.set_uuid = set_uuid

        self.otpid = otpid

        self.otp_pre = otp_pre



    otp_input = ui.TextInput(

        label="ワンタイムパスワード",

        placeholder="SMSに届いた4桁の認証コードを入力",

        min_length=4,

        max_length=4,

        required=True

    )



    async def on_submit(self, interaction: discord.Interaction):

        await interaction.response.defer(ephemeral=True)



        otp_result = await paypayu.login_otp(self.set_uuid, self.otp_input.value, self.otpid, self.otp_pre)



        if otp_result == "OK":

            paypay_data = load_paypay_data()

            user_id_str = str(interaction.user.id)



            paypay_data[user_id_str] = {

                "phone": self.phone,

                "password": self.password,

                "uuid": self.set_uuid

            }

            save_paypay_data(paypay_data)



            vending_data = load_vending_data()

            updated_count = 0



            for vm_id, vm_data in vending_data.items():

                if str(vm_data.get("owner_id")) == user_id_str and vm_data.get("paypay_id") is None:

                    vm_data["paypay_id"] = user_id_str

                    updated_count += 1



            if updated_count > 0:

                save_vending_data(vending_data)



            embed = discord.Embed(

                title="PayPay登録完了",

                description="PayPayアカウント情報の登録が完了しました。",

                color=discord.Color.green()

            )

            await interaction.followup.send(embed=embed, ephemeral=True)



        elif otp_result == "ERR":

            embed = discord.Embed(

                title="PayPayログインエラー",

                description="OTPコードが正しくありません。",

                color=discord.Color.red()

            )

            await interaction.followup.send(embed=embed, ephemeral=True)



        else:

            print(f"OTP結果: {otp_result}")

            embed = discord.Embed(

                title="PayPayログインエラー",

                description="開発者にお問い合わせください。",

                color=discord.Color.orange()

            )

            await interaction.followup.send(embed=embed, ephemeral=True)





class PaypayCog(commands.Cog):

    def __init__(self, bot):

        self.bot = bot

        if not os.path.exists(PAYPAY_DATA_FILE):

            save_paypay_data({})



    @commands.Cog.listener()

    async def on_message(self, message: discord.Message):

        if message.author.bot:

            return



        matches = PAYPAY_LINK_PATTERN.findall(message.content)

        if not matches:

            return



        for link_url in matches:

            link_info = await paypayu.check_link(link_url)

            if not link_info:

                continue



            embed = build_link_embed(link_url, link_info)

            view = ApproveLinkView(

                link_url=link_url,

                link_info=link_info,

                sender_id=message.author.id

            )

            await message.channel.send(embed=embed, view=view)



    @app_commands.command(name="paypayログアウト", description="ログイン中のPayPayアカウントからログアウトします")

    @is_allowed()

    async def paypay_logout(self, interaction: discord.Interaction):

        await interaction.response.defer(ephemeral=True)



        paypay_data = load_paypay_data()

        user_id_str = str(interaction.user.id)



        if user_id_str not in paypay_data:

            embed = discord.Embed(

                title="PayPayログアウト",

                description="ログイン中のPayPayアカウントが見つかりません。",

                color=discord.Color.orange()

            )

            await interaction.followup.send(embed=embed, ephemeral=True)

            return



        del paypay_data[user_id_str]

        save_paypay_data(paypay_data)



        embed = discord.Embed(

            title="✅ PayPayログアウト完了",

            description="PayPayアカウントからログアウトしました。",

            color=discord.Color.green()

        )

        await interaction.followup.send(embed=embed, ephemeral=True)



    @app_commands.command(name="paypayログイン", description="PayPayアカウントにログインします")

    @is_allowed()

    @app_commands.describe(phone="電話番号", password="パスワード")

    async def paypay_register(self, interaction: discord.Interaction, phone: str, password: str):

        await interaction.response.defer(ephemeral=True)



        set_uuid = str(uuid.uuid4())

        result = await paypayu.login(phone, password, set_uuid)



        print(f"PayPayログインレスポンス: {result}")



        if result.get("response_type") == "ErrorResponse":

            embed = discord.Embed(

                title="PayPayログインエラー",

                description="```ログイン情報とパスワードが一致していません。\n情報を正しく入力してください。```",

                color=0xff3333

            )

            await interaction.followup.send(embed=embed, ephemeral=True)

            return



        if "otp_reference_id" not in result:

            embed = discord.Embed(

                title="PayPayログインエラー",

                description=f"```予期しないレスポンスが返されました。\n{result}```",

                color=0xff3333

            )

            await interaction.followup.send(embed=embed, ephemeral=True)

            return



        otpid = result["otp_reference_id"]

        otp_pre = result["otp_prefix"]



        embed = discord.Embed(

            title="SMS認証",

            description="SMSに届いた認証コードを入力するために、下のボタンを押してください。",

            color=discord.Color.blue()

        )



        view = OTPView(phone, password, set_uuid, otpid, otp_pre)

        await interaction.followup.send(embed=embed, view=view, ephemeral=True)





async def setup(bot):

    await bot.add_cog(PaypayCog(bot))

ENDOFFILE
