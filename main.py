import discord
from discord.ext import commands
from discord import app_commands
import os
import traceback
import json
from dotenv import load_dotenv
from utils import safe_respond

load_dotenv()
token = os.getenv('TOKEN')

SERVER_ALLOW_FILE = "server_allow_data.json"

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
    allowed = load_allowed_guilds()
    return guild_id in allowed


class BotTree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        try:
            if not interaction.guild:
                await safe_respond(
                    interaction,
                    "❌ このBOTはサーバー内でのみ使用できます。",
                    ephemeral=True
                )
                return False

            if await self.client.is_owner(interaction.user):
                return True

            if not is_allowed_guild(interaction.guild.id):
                await safe_respond(
                    interaction,
                    "❌ このサーバーではBOTの使用が許可されていません。\n導入申請は https://discord.gg/jqZRDMpfQ までお問い合わせください。",
                    ephemeral=True
                )
                return False

            return True
        except discord.NotFound:
            return False


intents = discord.Intents.all()
bot = commands.Bot(
    command_prefix='$',
    intents=intents,
    help_command=None,
    tree_cls=BotTree,
)


async def load_cogs():
    for filename in os.listdir("./Cogs"):
        if filename.endswith(".py"):
            await bot.load_extension(f"Cogs.{filename[:-3]}")

bot.setup_hook = load_cogs


@bot.event
async def on_ready():
    print("Bot Is Ready.")
    await bot.change_presence(
        activity=discord.Game(name="Developer @roru2026."),
        status=discord.Status.idle
    )

    # Botが参加している全ギルドへ即時同期
    synced_guilds = []
    for guild in bot.guilds:
        try:
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
            synced_guilds.append(guild.id)
        except Exception as e:
            print(f"[Sync] Guild {guild.id} の同期に失敗: {e}")

    print(f"[Sync] {len(synced_guilds)}件のギルドにスラッシュコマンドを同期しました: {synced_guilds}")

    # グローバル同期（反映に最大1時間かかる場合あり）
    await bot.tree.sync()
    print("[Sync] グローバル同期完了")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if not message.guild:
        return

    if await bot.is_owner(message.author):
        await bot.process_commands(message)
        return

    if not is_allowed_guild(message.guild.id):
        return

    await bot.process_commands(message)


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        if interaction.command:
            print(f"{interaction.user}によるコマンド({interaction.command.name})の実行がブロックされました。")
        return
    if isinstance(error, app_commands.CommandNotFound):
        print(f"CommandNotFound (未同期の可能性): {error}")
        return
    print(error)
    traceback.print_exc()


bot.run(token)
