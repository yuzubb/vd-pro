import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import sys
import subprocess

ALLOWED_USERS_FILE = "stock_files/allowed_users.json"
SERVER_ALLOW_FILE = "server_allow_data.json"


# ── JSON ヘルパー ─────────────────────────────────────────────────

def load_allowed_users() -> list[dict]:
    """
    allowed_users.json の中身:
    {
        "allowed_ids": [
            {"user_id": 123456, "guild_id": 789012},
            ...
        ]
    }
    """
    if os.path.exists(ALLOWED_USERS_FILE):
        with open(ALLOWED_USERS_FILE, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                entries = data.get("allowed_ids", [])
                # 旧フォーマット（int のリスト）に対応
                result = []
                for e in entries:
                    if isinstance(e, int):
                        result.append({"user_id": e, "guild_id": None})
                    else:
                        result.append(e)
                return result
            except json.JSONDecodeError:
                return []
    return []


def save_allowed_users(entries: list[dict]):
    with open(ALLOWED_USERS_FILE, "w", encoding="utf-8") as f:
        json.dump({"allowed_ids": entries}, f, indent=4, ensure_ascii=False)


def load_allowed_guilds() -> list[dict]:
    if os.path.exists(SERVER_ALLOW_FILE):
        with open(SERVER_ALLOW_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f).get("allowed_guilds", [])
            except json.JSONDecodeError:
                return []
    return []


def save_allowed_guilds(guilds: list[dict]):
    with open(SERVER_ALLOW_FILE, "w", encoding="utf-8") as f:
        json.dump({"allowed_guilds": guilds}, f, indent=4, ensure_ascii=False)


# ── Cog ──────────────────────────────────────────────────────────

class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def owner_check(self, interaction: discord.Interaction) -> bool:
        if not await interaction.client.is_owner(interaction.user):
            await interaction.response.send_message(
                "❌ このコマンドはオーナーのみ使用できます。",
                ephemeral=True
            )
            return False
        return True

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  /再起動
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    @app_commands.command(name="再起動", description="【オーナー限定】Botを再起動します")
    async def restart(self, interaction: discord.Interaction):
        if not await self.owner_check(interaction):
            return

        await interaction.response.send_message("🔄 再起動します...", ephemeral=True)

        # 新しいプロセスを独立して起動してから現プロセスを終了する。
        # os.execv は現プロセスを完全に置き換えるため他のセッションごと落ちることがある。
        # subprocess.Popen で子プロセスを切り離すことでその問題を回避する。
        subprocess.Popen(
            [sys.executable] + sys.argv,
            close_fds=True,
            start_new_session=True   # 親プロセスのセッションから切り離す
        )
        await self.bot.close()

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  /許可ユーザー追加 @ユーザー サーバーID
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    @app_commands.command(name="許可ユーザー追加", description="【オーナー限定】指定サーバーへの許可ユーザーを追加します")
    @app_commands.describe(
        user="追加するユーザー",
        server_id="使用を許可するサーバーのID"
    )
    async def user_add(self, interaction: discord.Interaction, user: discord.User, server_id: str):
        if not await self.owner_check(interaction):
            return

        try:
            gid = int(server_id)
        except ValueError:
            await interaction.response.send_message(
                "❌ サーバーIDは数値で入力してください。",
                ephemeral=True
            )
            return

        entries = load_allowed_users()

        # 同じ user_id + guild_id の組み合わせが既に存在するか確認
        already = any(
            e["user_id"] == user.id and e["guild_id"] == gid
            for e in entries
        )
        if already:
            await interaction.response.send_message(
                f"⚠️ {user.mention}（`{user.id}`）はすでにサーバー `{gid}` の許可ユーザーです。",
                ephemeral=True
            )
            return

        guild_obj = self.bot.get_guild(gid)
        guild_name = guild_obj.name if guild_obj else "不明なサーバー"

        entries.append({"user_id": user.id, "guild_id": gid})
        save_allowed_users(entries)

        await interaction.response.send_message(
            f"✅ {user.mention}（`{user.id}`）を **{guild_name}**（`{gid}`）の許可ユーザーに追加しました。",
            ephemeral=True
        )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  /許可ユーザー削除 @ユーザー
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    @app_commands.command(name="許可ユーザー削除", description="【オーナー限定】許可ユーザーを削除します（全サーバー分）")
    @app_commands.describe(user="削除するユーザー")
    async def user_remove(self, interaction: discord.Interaction, user: discord.User):
        if not await self.owner_check(interaction):
            return

        entries = load_allowed_users()
        new_entries = [e for e in entries if e["user_id"] != user.id]

        if len(new_entries) == len(entries):
            await interaction.response.send_message(
                f"⚠️ {user.mention}（`{user.id}`）は許可ユーザーに登録されていません。",
                ephemeral=True
            )
            return

        removed = len(entries) - len(new_entries)
        save_allowed_users(new_entries)

        await interaction.response.send_message(
            f"🗑️ {user.mention}（`{user.id}`）を許可ユーザーから削除しました。（{removed}件）",
            ephemeral=True
        )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  /許可ユーザー一覧
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    @app_commands.command(name="許可ユーザー一覧", description="【オーナー限定】許可ユーザーの一覧を表示します")
    async def user_list(self, interaction: discord.Interaction):
        if not await self.owner_check(interaction):
            return

        entries = load_allowed_users()
        if not entries:
            await interaction.response.send_message(
                "📋 許可ユーザーはまだいません。",
                ephemeral=True
            )
            return

        lines = []
        for e in entries:
            uid = e["user_id"]
            gid = e.get("guild_id")

            user_obj = self.bot.get_user(uid)
            user_str = user_obj.mention if user_obj else f"`{uid}`"

            if gid:
                guild_obj = self.bot.get_guild(gid)
                guild_str = f"**{guild_obj.name}**（`{gid}`）" if guild_obj else f"`{gid}`"
                lines.append(f"• {user_str} → {guild_str}")
            else:
                lines.append(f"• {user_str}（サーバー指定なし）")

        embed = discord.Embed(
            title="📋 許可ユーザー一覧",
            description="\n".join(lines),
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"合計: {len(entries)}件")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
