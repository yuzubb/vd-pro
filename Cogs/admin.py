import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import sys

ALLOWED_USERS_FILE = "allowed_users.json"
SERVER_ALLOW_FILE = "server_allow_data.json"


def load_allowed_users() -> list[int]:
    if os.path.exists(ALLOWED_USERS_FILE):
        with open(ALLOWED_USERS_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f).get("allowed_ids", [])
            except json.JSONDecodeError:
                return []
    return []


def save_allowed_users(ids: list[int]):
    with open(ALLOWED_USERS_FILE, "w", encoding="utf-8") as f:
        json.dump({"allowed_ids": ids}, f, indent=4, ensure_ascii=False)


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


async def is_owner(interaction: discord.Interaction) -> bool:
    return await interaction.client.is_owner(interaction.user)


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── 権限チェック共通 ──────────────────────────────────────────
    async def owner_check(self, interaction: discord.Interaction) -> bool:
        if not await is_owner(interaction):
            await interaction.response.send_message(
                "❌ このコマンドはオーナーのみ使用できます。",
                ephemeral=True
            )
            return False
        return True

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  再起動
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    @app_commands.command(name="restart", description="【オーナー限定】Botを再起動します")
    async def restart(self, interaction: discord.Interaction):
        if not await self.owner_check(interaction):
            return
        await interaction.response.send_message("🔄 再起動します...", ephemeral=True)
        await self.bot.close()
        os.execv(sys.executable, [sys.executable] + sys.argv)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  許可ユーザー管理
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    @app_commands.command(name="user_add", description="【オーナー限定】許可ユーザーを追加します")
    @app_commands.describe(user="追加するユーザー")
    async def user_add(self, interaction: discord.Interaction, user: discord.User):
        if not await self.owner_check(interaction):
            return

        ids = load_allowed_users()
        if user.id in ids:
            await interaction.response.send_message(
                f"⚠️ {user.mention}（`{user.id}`）はすでに許可ユーザーです。",
                ephemeral=True
            )
            return

        ids.append(user.id)
        save_allowed_users(ids)
        await interaction.response.send_message(
            f"✅ {user.mention}（`{user.id}`）を許可ユーザーに追加しました。",
            ephemeral=True
        )

    @app_commands.command(name="user_remove", description="【オーナー限定】許可ユーザーを削除します")
    @app_commands.describe(user="削除するユーザー")
    async def user_remove(self, interaction: discord.Interaction, user: discord.User):
        if not await self.owner_check(interaction):
            return

        ids = load_allowed_users()
        if user.id not in ids:
            await interaction.response.send_message(
                f"⚠️ {user.mention}（`{user.id}`）は許可ユーザーではありません。",
                ephemeral=True
            )
            return

        ids.remove(user.id)
        save_allowed_users(ids)
        await interaction.response.send_message(
            f"🗑️ {user.mention}（`{user.id}`）を許可ユーザーから削除しました。",
            ephemeral=True
        )

    @app_commands.command(name="user_list", description="【オーナー限定】許可ユーザー一覧を表示します")
    async def user_list(self, interaction: discord.Interaction):
        if not await self.owner_check(interaction):
            return

        ids = load_allowed_users()
        if not ids:
            await interaction.response.send_message(
                "📋 許可ユーザーはまだいません。",
                ephemeral=True
            )
            return

        lines = []
        for uid in ids:
            user = self.bot.get_user(uid)
            if user:
                lines.append(f"• {user.mention}（`{uid}`）")
            else:
                lines.append(f"• 不明なユーザー（`{uid}`）")

        embed = discord.Embed(
            title="📋 許可ユーザー一覧",
            description="\n".join(lines),
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"合計: {len(ids)}人")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  許可サーバー管理
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    @app_commands.command(name="server_add", description="【オーナー限定】許可サーバーを追加します")
    @app_commands.describe(server_id="追加するサーバーID")
    async def server_add(self, interaction: discord.Interaction, server_id: str):
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

        guilds = load_allowed_guilds()
        if any(g["guild_id"] == gid for g in guilds):
            await interaction.response.send_message(
                f"⚠️ サーバーID `{gid}` はすでに許可済みです。",
                ephemeral=True
            )
            return

        guild_obj = self.bot.get_guild(gid)
        guild_name = guild_obj.name if guild_obj else "不明なサーバー"

        guilds.append({"guild_id": gid, "guild_name": guild_name})
        save_allowed_guilds(guilds)
        await interaction.response.send_message(
            f"✅ **{guild_name}**（`{gid}`）を許可サーバーに追加しました。",
            ephemeral=True
        )

    @app_commands.command(name="server_remove", description="【オーナー限定】許可サーバーを削除します")
    @app_commands.describe(server_id="削除するサーバーID")
    async def server_remove(self, interaction: discord.Interaction, server_id: str):
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

        guilds = load_allowed_guilds()
        new_guilds = [g for g in guilds if g["guild_id"] != gid]

        if len(new_guilds) == len(guilds):
            await interaction.response.send_message(
                f"⚠️ サーバーID `{gid}` は許可リストにありません。",
                ephemeral=True
            )
            return

        save_allowed_guilds(new_guilds)
        await interaction.response.send_message(
            f"🗑️ サーバーID `{gid}` を許可サーバーから削除しました。",
            ephemeral=True
        )

    @app_commands.command(name="server_list", description="【オーナー限定】許可サーバー一覧を表示します")
    async def server_list(self, interaction: discord.Interaction):
        if not await self.owner_check(interaction):
            return

        guilds = load_allowed_guilds()
        if not guilds:
            await interaction.response.send_message(
                "📋 許可サーバーはまだありません。",
                ephemeral=True
            )
            return

        lines = []
        for g in guilds:
            gid = g["guild_id"]
            stored_name = g.get("guild_name", "不明")
            guild_obj = self.bot.get_guild(gid)
            name = guild_obj.name if guild_obj else stored_name
            lines.append(f"• **{name}**（`{gid}`）")

        embed = discord.Embed(
            title="📋 許可サーバー一覧",
            description="\n".join(lines),
            color=discord.Color.green()
        )
        embed.set_footer(text=f"合計: {len(guilds)}サーバー")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
