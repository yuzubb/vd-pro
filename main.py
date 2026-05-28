import discord
from discord.ext import commands
from discord import app_commands
import os
import traceback
import json
from dotenv import load_dotenv

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


# CommandTree をサブクラス化して interaction_check を正しくオーバーライドする
# @bot.tree.interaction_check デコレータはコルーチンを await しないバグがあるため使わない
class BotTree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            await interaction.response.send_message(
                "❌ このBOTはサーバー内でのみ使用できます。",
                ephemeral=True
            )
            return False

        if await self.client.is_owner(interaction.user):
            return True

        if not is_allowed_guild(interaction.guild.id):
            await interaction.response.send_message(
                "❌ このサーバーではBOTの使用が許可されていません。\n導入申請は https://discord.gg/jqZRDMpfQ までお問い合わせください。",
                ephemeral=True
            )
            return False

        return True


intents = discord.Intents.all()
bot = commands.Bot(
    command_prefix='$',
    intents=intents,
    help_command=None,
    tree_cls=BotTree,  # カスタムツリーを登録
)


async def load_cogs():
    for filename in os.listdir("./Cogs"):
        if filename.endswith(".py"):
            await bot.load_extension(f"Cogs.{filename[:-3]}")
    await bot.tree.sync()

bot.setup_hook = load_cogs


@bot.event
async def on_ready():
    print("Bot Is Ready.")
    await bot.change_presence(
        activity=discord.Game(name="Developer @roru2026."),
        status=discord.Status.idle
    )


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
        print(f"{interaction.user}によるコマンド({interaction.command.name})の実行がブロックされました。")
        return
    print(error)
    traceback.print_exc()


bot.run(token)
