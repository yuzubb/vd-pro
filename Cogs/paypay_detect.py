import discord
from discord.ext import commands
import re
import asyncio
from paypayu import check_link

# PayPayリンクの正規表現
PAYPAY_LINK_PATTERN = re.compile(
    r"https://pay\.paypay\.ne\.jp/([A-Za-z0-9]+)"
)

# 承認待ちセッションを管理: message_id -> {link_info, sender_id, code}
pending_sessions: dict[int, dict] = {}


class ApproveView(discord.ui.View):
    """送信者だけが操作できる承認/拒否ボタン"""

    def __init__(self, sender_id: int, code: str, link_info: dict):
        super().__init__(timeout=300)  # 5分でタイムアウト
        self.sender_id = sender_id
        self.code = code
        self.link_info = link_info
        self.result: bool | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # 送信者本人かチェック
        if interaction.user.id != self.sender_id:
            await interaction.response.send_message(
                "❌ このボタンは送信者本人のみ操作できます。",
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="✅ 受け取りを許可する", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.result = True
        self.stop()

        # ボタンを無効化して更新
        for item in self.children:
            item.disabled = True

        payload = self.link_info.get("payload", {})
        pending = payload.get("pendingP2PInfo", {})
        amount = pending.get("amount", "不明")
        sender_name = payload.get("message", {}).get("senderName", "不明")

        embed = discord.Embed(
            title="✅ 受け取りを許可しました",
            description=(
                f"送信者 **{sender_name}** が受け取りを許可しました。\n"
                f"金額: **¥{amount}**\n\n"
                f"受取人はリンクから受け取ってください。\n"
                f"[リンクを開く](https://pay.paypay.ne.jp/{self.code})"
            ),
            color=discord.Color.green()
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="❌ 拒否する", style=discord.ButtonStyle.danger)
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.result = False
        self.stop()

        for item in self.children:
            item.disabled = True

        embed = discord.Embed(
            title="❌ 受け取りを拒否しました",
            description="送信者がこのリンクの受け取りを拒否しました。",
            color=discord.Color.red()
        )
        await interaction.response.edit_message(embed=embed, view=self)


class PayPayDetect(commands.Cog):
    """メッセージ内のPayPayリンクを検出し、送信者に受け取り許可を求める"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Bot自身のメッセージは無視
        if message.author.bot:
            return

        # PayPayリンクを検索
        match = PAYPAY_LINK_PATTERN.search(message.content)
        if not match:
            return

        code = match.group(1)

        # リンク情報を取得
        link_info = await check_link(code)
        if not link_info:
            # 無効・受取済み・キャンセル済みは無視
            return

        payload = link_info.get("payload", {})
        pending = payload.get("pendingP2PInfo", {})
        amount = pending.get("amount", "不明")
        sender_name = payload.get("message", {}).get("senderName", "不明")
        has_password = pending.get("isSetPasscode", False)

        # 有効期限
        expire_date = pending.get("expiredAt", "")
        if expire_date:
            try:
                from datetime import datetime, timezone, timedelta
                dt = datetime.fromisoformat(expire_date.replace("Z", "+00:00"))
                jst = dt.astimezone(timezone(timedelta(hours=9)))
                expire_str = jst.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                expire_str = expire_date
        else:
            expire_str = "不明"

        embed = discord.Embed(
            title="💸 PayPayリンク検出",
            color=discord.Color.gold()
        )
        embed.add_field(name="送信者", value=sender_name, inline=False)
        embed.add_field(name="金額", value=f"¥{amount}", inline=True)
        embed.add_field(name="パスワード", value="あり" if has_password else "なし", inline=True)
        embed.add_field(name="ステータス", value="受け取り待ち", inline=True)
        embed.add_field(name="有効期限", value=expire_str, inline=False)
        embed.add_field(
            name="リンク",
            value=f"[https://pay.paypay.ne.jp/{code}](https://pay.paypay.ne.jp/{code})",
            inline=False
        )
        embed.set_footer(text=f"送信者 ({message.author.display_name}) が受け取りを許可するか選んでください")

        view = ApproveView(
            sender_id=message.author.id,
            code=code,
            link_info=link_info
        )

        sent = await message.reply(embed=embed, view=view)

        # タイムアウト時の処理
        await view.wait()
        if view.result is None:
            # タイムアウト
            for item in view.children:
                item.disabled = True
            timeout_embed = discord.Embed(
                title="⏰ タイムアウト",
                description="時間内に操作されなかったため、このセッションは終了しました。",
                color=discord.Color.light_grey()
            )
            try:
                await sent.edit(embed=timeout_embed, view=view)
            except discord.NotFound:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(PayPayDetect(bot))
