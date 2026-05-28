import discord
from discord.ext import commands
from discord import app_commands, ui
import json
import os
from utils import is_allowed

CURRENCY_FILE = "currency_data.json"


# ──────────────────────────────────────────
#  JSON ユーティリティ
# ──────────────────────────────────────────

def load_currency_data() -> dict:
    if os.path.exists(CURRENCY_FILE):
        with open(CURRENCY_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}


def save_currency_data(data: dict):
    with open(CURRENCY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def get_balance(guild_id: int, user_id: int) -> int:
    data = load_currency_data()
    return data.get(str(guild_id), {}).get(str(user_id), 0)


def set_balance(guild_id: int, user_id: int, amount: int):
    data = load_currency_data()
    gid = str(guild_id)
    uid = str(user_id)
    if gid not in data:
        data[gid] = {}
    data[gid][uid] = amount
    save_currency_data(data)


# ──────────────────────────────────────────
#  /サーバー内通貨確認  ─ 確認パネル設置
# ──────────────────────────────────────────

class BalanceCheckView(ui.View):
    """永続パネル用 View（timeout=None で再起動後も動く）"""
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(
        label="💰 残高を確認する",
        style=discord.ButtonStyle.primary,
        custom_id="currency_check_balance"
    )
    async def check_balance(self, interaction: discord.Interaction, button: ui.Button):
        balance = get_balance(interaction.guild.id, interaction.user.id)
        embed = discord.Embed(
            description=f"💰 あなたのサーバー通貨は **{balance:,} pt** です",
            color=discord.Color.gold()
        )
        embed.set_footer(text="roru2026.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ──────────────────────────────────────────
#  /サーバー内通貨チャージ  ─ UserSelect → Modal
# ──────────────────────────────────────────

class ChargeAmountModal(ui.Modal, title="チャージ額の入力"):
    def __init__(self, target: discord.Member):
        super().__init__(timeout=300)
        self.target = target
        self.amount_input = ui.TextInput(
            label=f"{target.display_name} にチャージする額（pt）",
            placeholder="例: 500",
            required=True,
            max_length=10
        )
        self.add_item(self.amount_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.amount_input.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ 数字を入力してください。", ephemeral=True)
            return

        if amount <= 0:
            await interaction.response.send_message("❌ 1以上の数値を入力してください。", ephemeral=True)
            return

        current = get_balance(interaction.guild.id, self.target.id)
        new_balance = current + amount
        set_balance(interaction.guild.id, self.target.id, new_balance)

        embed = discord.Embed(
            title="✅ チャージ完了",
            color=discord.Color.green()
        )
        embed.add_field(name="対象ユーザー", value=self.target.mention, inline=True)
        embed.add_field(name="チャージ額", value=f"{amount:,} pt", inline=True)
        embed.add_field(name="チャージ後残高", value=f"{new_balance:,} pt", inline=True)
        embed.set_footer(text="roru2026.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


class ChargeUserSelectView(ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        select = ui.UserSelect(
            placeholder="チャージするユーザーを選択してください",
            min_values=1,
            max_values=1
        )
        select.callback = self.user_selected
        self.add_item(select)

    async def user_selected(self, interaction: discord.Interaction):
        target = interaction.data["resolved"]["members"]
        # UserSelect から Member を取得
        user_id = list(interaction.data["values"])[0]
        member = interaction.guild.get_member(int(user_id))
        if member is None:
            await interaction.response.send_message("❌ ユーザーが見つかりませんでした。", ephemeral=True)
            return
        modal = ChargeAmountModal(member)
        await interaction.response.send_modal(modal)


# ──────────────────────────────────────────
#  /サーバー内通貨引き出し  ─ UserSelect → Modal
# ──────────────────────────────────────────

class WithdrawAmountModal(ui.Modal, title="引き出し額の入力"):
    def __init__(self, target: discord.Member):
        super().__init__(timeout=300)
        self.target = target
        self.amount_input = ui.TextInput(
            label=f"{target.display_name} から引き出す額（pt）",
            placeholder="例: 200",
            required=True,
            max_length=10
        )
        self.add_item(self.amount_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.amount_input.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ 数字を入力してください。", ephemeral=True)
            return

        if amount <= 0:
            await interaction.response.send_message("❌ 1以上の数値を入力してください。", ephemeral=True)
            return

        current = get_balance(interaction.guild.id, self.target.id)
        if amount > current:
            await interaction.response.send_message(
                f"❌ 残高が不足しています。現在の残高: **{current:,} pt**", ephemeral=True
            )
            return

        new_balance = current - amount
        set_balance(interaction.guild.id, self.target.id, new_balance)

        embed = discord.Embed(
            title="✅ 引き出し完了",
            color=discord.Color.orange()
        )
        embed.add_field(name="対象ユーザー", value=self.target.mention, inline=True)
        embed.add_field(name="引き出し額", value=f"{amount:,} pt", inline=True)
        embed.add_field(name="引き出し後残高", value=f"{new_balance:,} pt", inline=True)
        embed.set_footer(text="roru2026.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


class WithdrawUserSelectView(ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        select = ui.UserSelect(
            placeholder="引き出すユーザーを選択してください",
            min_values=1,
            max_values=1
        )
        select.callback = self.user_selected
        self.add_item(select)

    async def user_selected(self, interaction: discord.Interaction):
        user_id = list(interaction.data["values"])[0]
        member = interaction.guild.get_member(int(user_id))
        if member is None:
            await interaction.response.send_message("❌ ユーザーが見つかりませんでした。", ephemeral=True)
            return
        modal = WithdrawAmountModal(member)
        await interaction.response.send_modal(modal)


# ──────────────────────────────────────────
#  /サーバー内通貨確認owner  ─ UserSelect → 残高表示
# ──────────────────────────────────────────

class OwnerCheckUserSelectView(ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        select = ui.UserSelect(
            placeholder="確認するユーザーを選択してください",
            min_values=1,
            max_values=1
        )
        select.callback = self.user_selected
        self.add_item(select)

    async def user_selected(self, interaction: discord.Interaction):
        user_id = list(interaction.data["values"])[0]
        member = interaction.guild.get_member(int(user_id))
        if member is None:
            await interaction.response.send_message("❌ ユーザーが見つかりませんでした。", ephemeral=True)
            return

        balance = get_balance(interaction.guild.id, member.id)
        embed = discord.Embed(
            title="💰 残高照会",
            color=discord.Color.gold()
        )
        embed.add_field(name="ユーザー", value=member.mention, inline=True)
        embed.add_field(name="残高", value=f"{balance:,} pt", inline=True)
        embed.set_footer(text="roru2026.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ──────────────────────────────────────────
#  Cog 本体
# ──────────────────────────────────────────

class CurrencyCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # 永続 View を登録（再起動後のボタンを復活させる）
        bot.add_view(BalanceCheckView())

    # ── /サーバー内通貨確認 ──────────────────
    @app_commands.command(
        name="サーバー内通貨確認",
        description="残高確認パネルをチャンネルに設置します"
    )
    @is_allowed()
    async def currency_panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="💰 サーバー内通貨",
            description="下のボタンを押すと、あなたの残高を確認できます。",
            color=discord.Color.gold()
        )
        embed.set_footer(text="roru2026.")
        await interaction.response.send_message(embed=embed, view=BalanceCheckView())

    # ── /サーバー内通貨チャージ ──────────────
    @app_commands.command(
        name="サーバー内通貨チャージ",
        description="指定ユーザーにサーバー内通貨をチャージします（許可ユーザー専用）"
    )
    @is_allowed()
    async def currency_charge(self, interaction: discord.Interaction):
        embed = discord.Embed(
            description="💳 通貨をチャージするユーザーを選んでください",
            color=discord.Color.blue()
        )
        embed.set_footer(text="roru2026.")
        await interaction.response.send_message(
            embed=embed, view=ChargeUserSelectView(), ephemeral=True
        )

    # ── /サーバー内通貨引き出し ──────────────
    @app_commands.command(
        name="サーバー内通貨引き出し",
        description="指定ユーザーからサーバー内通貨を引き出します（許可ユーザー専用）"
    )
    @is_allowed()
    async def currency_withdraw(self, interaction: discord.Interaction):
        embed = discord.Embed(
            description="💸 通貨を引き出すユーザーを選んでください",
            color=discord.Color.orange()
        )
        embed.set_footer(text="roru2026.")
        await interaction.response.send_message(
            embed=embed, view=WithdrawUserSelectView(), ephemeral=True
        )

    # ── /サーバー内通貨確認owner ─────────────
    @app_commands.command(
        name="サーバー内通貨確認owner",
        description="指定ユーザーの残高を確認します（許可ユーザー専用）"
    )
    @is_allowed()
    async def currency_check_owner(self, interaction: discord.Interaction):
        embed = discord.Embed(
            description="🔍 確認するユーザーを選択してください",
            color=discord.Color.purple()
        )
        embed.set_footer(text="roru2026.")
        await interaction.response.send_message(
            embed=embed, view=OwnerCheckUserSelectView(), ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(CurrencyCog(bot))
