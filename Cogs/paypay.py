import discord
from discord import ui
from discord.ext import commands
from discord import app_commands
import json
import os
import re
import uuid
from utils import is_owner, OWNER_ID
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

class ReceiveLinkView(ui.View):
    """
    送信者が「許可する」を押した場合にのみ、オーナーが自動受け取りを実行するView。
    - 送信者のDiscord IDを保持し、送信者本人のみ「許可」「拒否」を押せる
    - 許可後はオーナーのPayPayアカウントで自動受け取りを実行
    """

    def __init__(self, link_url: str, link_info: dict, sender_id: int):
        super().__init__(timeout=300)
        self.link_url = link_url
        self.link_info = link_info
        self.sender_id = sender_id  # リンクを貼った人のDiscord ID
        self.received = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """送信者本人だけボタンを操作できる"""
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
        if self.received:
            await interaction.response.send_message(
                "⚠️ このリンクはすでに処理済みです。",
                ephemeral=True
            )
            return

        await interaction.response.defer()

        # オーナーのPayPayアカウント情報を取得
        paypay_data = load_paypay_data()
        owner_id_str = str(OWNER_ID)

        if owner_id_str not in paypay_data:
            await interaction.followup.send(
                "⚠️ オーナーのPayPayアカウントが登録されていません。`/paypayログイン` で登録が必要です。",
                ephemeral=True
            )
            return

        user_paypay = paypay_data[owner_id_str]
        phone     = user_paypay.get("phone")
        password  = user_paypay.get("password")
        user_uuid = user_paypay.get("uuid")

        is_passcode = self.link_info.get("payload", {}).get("pendingP2PInfo", {}).get("isSetPasscode", False)
        if is_passcode:
            await interaction.followup.send(
                "⚠️ このリンクにはパスコードが設定されているため自動受け取りできません。",
                ephemeral=True
            )
            return

        # 受け取り実行
        result = await paypayu.link_rev(self.link_url, phone, password, user_uuid)

        if result is True:
            self.received = True
            self._disable_all()
            button.label = "✅ 受け取り済み"
            button.style = discord.ButtonStyle.secondary
            await interaction.message.edit(view=self)
            await interaction.followup.send(
                "✅ 受け取りが完了しました！",
                ephemeral=True
            )
        elif result == "LOGINERR":
            self._disable_all()
            await interaction.message.edit(view=self)
            await interaction.followup.send(
                "❌ PayPayへのログインに失敗しました。オーナーは `/paypayログイン` で再登録してください。",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                "❌ 受け取りに失敗しました。リンクの有効期限切れ、またはすでに受け取られた可能性があります。",
                ephemeral=True
            )

    @ui.button(label="❌ 拒否する", style=discord.ButtonStyle.danger)
    async def deny_button(self, interaction: discord.Interaction, button: ui.Button):
        if self.received:
            await interaction.response.send_message(
                "⚠️ このリンクはすでに処理済みです。",
                ephemeral=True
            )
            return

        self.received = True
        self._disable_all()
        button.label = "❌ 拒否済み"
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            "受け取りを拒否しました。",
            ephemeral=True
        )

def build_link_embed(link_url: str, link_info: dict) -> discord.Embed:
    """check_link のレスポンスからPayPayリンク情報Embedを生成する"""
    payload = link_info.get("payload", {})
    p2p_info = payload.get("pendingP2PInfo", {})
    message_data = payload.get("message", {}).get("data", {})
    
    # 金額情報
    amount = p2p_info.get("amount", 0)
    
    # subWalletSplit からマネーとマネーライトの内訳を取得
    sub_wallet_split = message_data.get("subWalletSplit", {})
    sender_emoney = sub_wallet_split.get("senderEmoneyAmount", 0)      # マネー
    sender_prepaid = sub_wallet_split.get("senderPrepaidAmount", 0)    
    sender_display_name = p2p_info.get("userDisplayName", "不明")
    if not sender_display_name or sender_display_name == "不明":
        sender_info = payload.get("sender", {})
        sender_display_name = sender_info.get("displayName", "不明")
    
    sender_photo_url = p2p_info.get("imageUrl", None)
    if not sender_photo_url:
        sender_info = payload.get("sender", {})
        sender_photo_url = sender_info.get("photoUrl", None)
    
    order_id = p2p_info.get("orderId", message_data.get("orderId", "不明"))
    expired_at = p2p_info.get("expiredAt", "")
    if expired_at:
        expired_at = expired_at.replace("T", " ").replace("Z", "")[:19]
    else:
        expired_at = "不明"
    is_passcode = p2p_info.get("isSetPasscode", False)
    passcode_status = "あり" if is_passcode else "なし"
    order_status = message_data.get("status", "PENDING")
    status = "受け取り待ち" if order_status == "PENDING" else "受け取り済み"
    
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
`{passcode_status}` / `{status}` / `{expired_at}`
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

class PayPayOTPModal(ui.Modal, title="PayPay OTP認証"):
    def __init__(self, phone, password, set_uuid, otpid, otp_pre):
        super().__init__(timeout=120)
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
                description="OTPコードが正しくありません。もう一度 `/paypayログイン` からやり直してください。", 
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

        else:
            print(f"OTP Error: {otp_result}")
            embed = discord.Embed(
                title="⚠️ エラー", 
                description="開発者にお問い合わせください。", 
                color=discord.Color.orange()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)


class OTPConfirmView(ui.View):
    def __init__(self, phone, password, set_uuid, otpid, otp_pre):
        super().__init__(timeout=120)
        self.phone = phone
        self.password = password
        self.set_uuid = set_uuid
        self.otpid = otpid
        self.otp_pre = otp_pre

    @ui.button(label="認証コードを入力", style=discord.ButtonStyle.primary)
    async def input_otp(self, interaction: discord.Interaction, button: ui.Button):
        modal = PayPayOTPModal(self.phone, self.password, self.set_uuid, self.otpid, self.otp_pre)
        await interaction.response.send_modal(modal)


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
            view  = ReceiveLinkView(link_url=link_url, link_info=link_info, sender_id=message.author.id)

            await message.channel.send(embed=embed, view=view)

    @app_commands.command(name="paypayログイン", description="PayPayアカウントにログインします（オーナー専用）")
    @is_owner()
    @app_commands.describe(phone="電話番号", password="パスワード")
    async def paypay_register(self, interaction: discord.Interaction, phone: str, password: str):
        # 最初に応答がないことを確認
        if interaction.response.is_done():
            await interaction.followup.send("処理を開始します...", ephemeral=True)
        
        # deferしてタイムアウトを防ぐ
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.InteractionResponded:
            # 既に応答済みの場合はフォローアップを使用
            pass
        
        set_uuid = str(uuid.uuid4())
        result = await paypayu.login(phone, password, set_uuid)
        
        if result.get("response_type") == "ErrorResponse":
            embed = discord.Embed(
                title="PayPayログインエラー",
                description="```ログイン情報とパスワードが一致していません。\n情報を正しく入力してください。```",
                color=0xff3333
            )
            try:
                await interaction.followup.send(embed=embed, ephemeral=True)
            except:
                await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # OTP認証が必要な場合
        otpid = result.get("otp_reference_id")
        otp_pre = result.get("otp_prefix")
        
        if otpid and otp_pre:
            # 元の応答を削除（存在する場合）
            try:
                await interaction.delete_original_response()
            except:
                pass
            
            # ボタン付きのビューを送信
            view = OTPConfirmView(phone, password, set_uuid, otpid, otp_pre)
            await interaction.followup.send(
                "**OTP認証が必要です**\n\n"
                "SMSに届いた4桁の認証コードを入力してください。\n"
                "コードが届かない場合は、もう一度 `/paypayログイン` を実行してください。",
                view=view,
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                "予期せぬエラーが発生しました。もう一度お試しください。",
                ephemeral=True
            )

    @app_commands.command(name="paypay残高", description="PayPayの残高を確認します（オーナー専用）")
    @is_owner()
    async def paypay_balance(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        paypay_data = load_paypay_data()
        user_id_str = str(interaction.user.id)

        if user_id_str not in paypay_data:
            embed = discord.Embed(
                title="エラー",
                description="PayPayアカウントが登録されていません。`/paypayログイン` で登録してください。",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        user_paypay = paypay_data[user_id_str]
        phone     = user_paypay.get("phone")
        password  = user_paypay.get("password")
        user_uuid = user_paypay.get("uuid")

        if not phone or not password or not user_uuid:
            embed = discord.Embed(
                title="エラー",
                description="アカウント情報が不完全です。再登録してください。",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        result = await paypayu.get_balance_rev(phone, password, user_uuid)

        if result == "LOGINERR":
            embed = discord.Embed(
                title="エラー",
                description="ログインに失敗しました。OTP認証が必要な可能性があります。\nもう一度 `/paypayログイン` で再登録してください。",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        if not result:
            embed = discord.Embed(
                title="エラー",
                description="残高情報の取得に失敗しました。\n時間をおいて再度お試しください。",
                color=discord.Color.orange()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        money       = f"¥{result['money']:,}"
        money_light = f"¥{result['money_light']:,}"
        points      = f"{result['points']:,} pt"
        total       = f"¥{result['all_balance']:,}"

        description = f"""```yaml
マネー       : {money}
マネーライト : {money_light}
ポイント     : {points}
全残高       : {total}
```"""
        embed = discord.Embed(
            title="PayPay残高",
            description=description,
            color=discord.Color.green()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(PaypayCog(bot))
