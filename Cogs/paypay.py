import discord
from discord import ui
from discord.ext import commands
from discord import app_commands
import json
import os
import uuid
from utils import is_allowed
import paypayu

PAYPAY_DATA_FILE = "paypay_data.json"
VENDING_DATA_FILE = "vending_data.json"

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