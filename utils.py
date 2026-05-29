import discord
from discord import app_commands
import json
import os
from dotenv import load_dotenv

load_dotenv()

ALLOWED_USERS_FILE = "stock_files/allowed_users.json"

# BOTオーナーのDiscord ID（.envのOWNER_IDから読み込む）
_owner_id_raw = os.getenv("OWNER_ID")
OWNER_ID = int(_owner_id_raw) if _owner_id_raw else 0
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


async def safe_respond(interaction: discord.Interaction, *args, **kwargs):
    """
    interaction.response.is_done() が True の場合（既にack済み）は
    followup.send にフォールバックする。
    404 Unknown interaction（タイムアウト）は静かに無視する。
    """
    try:
        if interaction.response.is_done():
            await interaction.followup.send(*args, **kwargs)
        else:
            await interaction.response.send_message(*args, **kwargs)
    except discord.NotFound:
        # interaction が期限切れ（3秒超過）—ログだけ出して無視
        print(f"[warn] interaction expired: {getattr(interaction.command, 'name', '?')}")
    except discord.HTTPException as e:
        if e.code == 40060:
            # 既にack済み → followup で再送
            try:
                await interaction.followup.send(*args, **kwargs)
            except Exception:
                pass
        else:
            raise


def is_allowed():
    async def predicate(interaction: discord.Interaction) -> bool:
        # DM は常に拒否
        if interaction.guild is None:
            await safe_respond(interaction, "❌ このBOTはサーバー内でのみ使用できます。", ephemeral=True)
            return False

        # BOT所有者は常に許可
        if await interaction.client.is_owner(interaction.user):
            return True

        # 許可ユーザーはサーバーに関係なく通す（ギルドチェックより先に判定）
        allowed_ids = load_allowed_users()
        if interaction.user.id in allowed_ids:
            return True

        # 許可サーバーかどうかチェック
        if not is_allowed_guild(interaction.guild.id):
            await safe_respond(
                interaction,
                "❌ このサーバーではBOTの使用が許可されていません。\n導入申請は https://discord.gg/cmYmnedX7h までお問い合わせください。",
                ephemeral=True
            )
            return False

        # 許可サーバー内だがユーザー権限なし
        await safe_respond(interaction, "🚫 あなたはこのBotの機能を利用する権限がありません。", ephemeral=True)
        return False

    return app_commands.check(predicate)
