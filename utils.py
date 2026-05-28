import discord
from discord import app_commands
import json
import os

ALLOWED_USERS_FILE = "allowed_users.json"
SERVER_ALLOW_FILE = "server_allow_data.json"

def load_allowed_users():
    if os.path.exists(ALLOWED_USERS_FILE):
        with open(ALLOWED_USERS_FILE, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                return data.get("allowed_ids", [])
            except json.JSONDecodeError:
                return []
    return []

def load_allowed_guilds():
    if os.path.exists(SERVER_ALLOW_FILE):
        with open(SERVER_ALLOW_FILE, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                return [g["guild_id"] for g in data.get("allowed_guilds", [])]
            except json.JSONDecodeError:
                return []
    return []

def is_allowed_guild(guild_id: int) -> bool:
    return guild_id in load_allowed_guilds()

def is_allowed():
    async def predicate(interaction: discord.Interaction) -> bool:
        # DM は常に拒否
        if interaction.guild is None:
            await interaction.response.send_message("❌ このBOTはサーバー内でのみ使用できます。", ephemeral=True)
            return False

        # BOT所有者は常に許可
        if await interaction.client.is_owner(interaction.user):
            return True

        # 許可ユーザーはサーバーに関係なく通す（ギルドチェックより先に判定）
        allowed_ids = load_allowed_users()
        if interaction.user.id in allowed_ids:
            return True

        # 上記に該当しない場合は許可サーバーかどうかチェック
        if not is_allowed_guild(interaction.guild.id):
            await interaction.response.send_message(
                "❌ このサーバーではBOTの使用が許可されていません。\n導入申請は https://discord.gg/cmYmnedX7h までお問い合わせください。",
                ephemeral=True
            )
            return False

        # 許可サーバー内だがユーザー権限なし
        await interaction.response.send_message("🚫 あなたはこのBotの機能を利用する権限がありません。", ephemeral=True)
        return False

    return app_commands.check(predicate)
