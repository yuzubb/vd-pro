import discord
from discord import app_commands, ui
from discord.ext import commands
from discord.ui import Button, View, Select
import aiohttp
from bs4 import BeautifulSoup
import os
import io
import json
import urllib.parse
import asyncio
import paypayu
from utils import is_allowed, is_owner, safe_respond

# ==========================================
# 設定
# ==========================================
BASE_URL = os.getenv("MANGA_BASE_URL", "https://momon-ga.com")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

MANGA_PRICE = 50                                  # 閲覧料金（円）
PAYPAY_DATA_FILE  = "paypay_data.json"            # vd-pro 共通
MANGA_OWNER_FILE  = "stock_files/manga_paypay_owner.json"
MANGA_PANEL_FILE  = "stock_files/manga_panels.json"


# ==========================================
# データ管理
# ==========================================

def _ensure_dir(path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)


def load_paypay_data() -> dict:
    if os.path.exists(PAYPAY_DATA_FILE):
        with open(PAYPAY_DATA_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}


def load_manga_owner() -> dict:
    if os.path.exists(MANGA_OWNER_FILE):
        with open(MANGA_OWNER_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}


def save_manga_owner(data: dict):
    _ensure_dir(MANGA_OWNER_FILE)
    with open(MANGA_OWNER_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def load_manga_panels() -> list:
    if os.path.exists(MANGA_PANEL_FILE):
        with open(MANGA_PANEL_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
    return []


def save_manga_panels(data: list):
    _ensure_dir(MANGA_PANEL_FILE)
    with open(MANGA_PANEL_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


# ==========================================
# スクレイピング・データ取得
# ==========================================

async def search_manga(query: str) -> list[dict]:
    """タイトル検索を行い、最大25件を返す"""
    encoded = urllib.parse.quote(query)
    url = f"{BASE_URL}/?s={encoded}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return []
            soup = BeautifulSoup(await resp.text(), "html.parser")

    results = []
    for item in soup.select(".post-list > a"):
        span = item.find("span")
        if span:
            title = span.get_text(strip=True)
        else:
            img = item.find("img")
            title = img.get("alt", "").strip() if img else "無題の作品"

        href = item.get("href")
        if title and href:
            results.append({"title": title, "url": href})

    return results[:25]


async def get_pages(manga_url: str) -> list[str]:
    """作品ページからすべての漫画画像URLを取得する"""
    async with aiohttp.ClientSession() as session:
        async with session.get(manga_url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return []
            soup = BeautifulSoup(await resp.text(), "html.parser")

    area = soup.select_one(".main-area") or soup
    pages = []
    for img in area.find_all("img"):
        src = img.get("data-src") or img.get("src", "")
        if not src:
            continue
        sl = src.lower()
        if any(ext in sl for ext in [".jpg", ".jpeg", ".png", ".webp"]):
            if not any(kw in sl for kw in ["logo", "icon", "avatar"]):
                if src not in pages:
                    pages.append(src)

    return pages


# ==========================================
# Embed ビルダー
# ==========================================

def make_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📚 漫画ビューア",
        description=(
            "漫画を検索して閲覧できます。\n\n"
            "🔍 **検索は無料**\n"
            f"📖 **閲覧は ¥{MANGA_PRICE}（1回ごと）**\n\n"
            "下のボタンを押して漫画を検索してください。"
        ),
        color=0x2B2D31,
    )
    embed.set_footer(text="roru2026.")
    return embed


# ==========================================
# UI コンポーネント
# ==========================================

class MangaReaderView(View):
    """漫画ページめくりビュー（ephemeral 専用）"""

    def __init__(self, pages: list[str], title: str):
        super().__init__(timeout=300)
        self.pages = pages
        self.title = title
        self.current_page = 0
        self._refresh_buttons()

    def _refresh_buttons(self):
        self.prev_btn.disabled = self.current_page == 0
        self.next_btn.disabled = self.current_page >= len(self.pages) - 1

    def _make_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=self.title,
            description=f"ページ: **{self.current_page + 1}** / {len(self.pages)}",
            color=0x2B2D31,
        )
        embed.set_image(url=self.pages[self.current_page])
        embed.set_footer(text="roru2026.")
        return embed

    @discord.ui.button(label="◀ 前へ", style=discord.ButtonStyle.secondary, row=0)
    async def prev_btn(self, interaction: discord.Interaction, button: Button):
        self.current_page = max(0, self.current_page - 1)
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self._make_embed(), view=self)

    @discord.ui.button(label="次へ ▶", style=discord.ButtonStyle.primary, row=0)
    async def next_btn(self, interaction: discord.Interaction, button: Button):
        self.current_page = min(len(self.pages) - 1, self.current_page + 1)
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self._make_embed(), view=self)

    @discord.ui.button(label="終了", style=discord.ButtonStyle.danger, row=0)
    async def close_btn(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(content="❌ 閲覧を終了しました。", embeds=[], view=None)
        self.stop()


class MangaPaymentModal(ui.Modal, title="PayPay 支払い"):
    """PayPayリンクを受け取り、受け取り処理後に漫画を開くモーダル"""

    link_input = ui.TextInput(
        label="PayPay 送金リンク",
        placeholder="https://pay.paypay.ne.jp/XXXXXXXXXX",
        required=True,
    )
    password_input = ui.TextInput(
        label="パスコード（設定されている場合のみ）",
        placeholder="パスコードがある場合のみ入力",
        required=False,
        max_length=4,
    )

    def __init__(self, manga_url: str, manga_title: str):
        super().__init__()
        self.manga_url   = manga_url
        self.manga_title = manga_title

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        link     = self.link_input.value.strip()
        passcode = self.password_input.value.strip() or None

        # ── リンク検証 ──
        check = await paypayu.check_link(link)
        if not check:
            return await interaction.followup.send(
                "❌ 無効な PayPay リンクです。有効なリンクを貼り付けてください。",
                ephemeral=True,
            )

        p2p = check.get("payload", {}).get("pendingP2PInfo", {})
        amount = p2p.get("amount", 0)
        if amount != MANGA_PRICE:
            return await interaction.followup.send(
                f"❌ リンクの金額（¥{amount}）が正しくありません。¥{MANGA_PRICE} のリンクを送ってください。",
                ephemeral=True,
            )

        if p2p.get("isSetPasscode") and not passcode:
            return await interaction.followup.send(
                "⚠️ このリンクにはパスコードが設定されています。パスコード欄に入力してください。",
                ephemeral=True,
            )

        # ── PayPay 受け取り ──
        owner_data = load_manga_owner()
        owner_id   = owner_data.get("owner_id")
        if not owner_id:
            return await interaction.followup.send(
                "❌ 管理者が PayPay アカウントを設定していません。`/manga支払い設定` で設定が必要です。",
                ephemeral=True,
            )

        pp_info = load_paypay_data().get(str(owner_id))
        if not pp_info:
            return await interaction.followup.send(
                "❌ PayPay アカウント情報が見つかりません。管理者に連絡してください。",
                ephemeral=True,
            )

        result = await paypayu.link_rev(
            link,
            pp_info["phone"],
            pp_info["password"],
            pp_info["uuid"],
            passcode,
        )

        if result == "LOGINERR":
            return await interaction.followup.send(
                "❌ PayPay ログインエラーが発生しました。管理者に連絡してください。",
                ephemeral=True,
            )
        if not result:
            return await interaction.followup.send(
                "❌ PayPay リンクの受け取りに失敗しました。有効期限切れまたは使用済みの可能性があります。",
                ephemeral=True,
            )

        # ── 漫画読み込み ──
        await interaction.followup.send(
            f"✅ **¥{MANGA_PRICE} の支払いを確認しました！**\n「{self.manga_title}」を読み込んでいます...",
            ephemeral=True,
        )

        pages = await get_pages(self.manga_url)
        if not pages:
            return await interaction.followup.send(
                "⚠️ 漫画画像の取得に失敗しました。URLが正しいか確認してください。",
                ephemeral=True,
            )

        view = MangaReaderView(pages, self.manga_title)
        await interaction.followup.send(embed=view._make_embed(), view=view, ephemeral=True)


class MangaPaymentView(View):
    """支払いボタンを表示するビュー"""

    def __init__(self, manga_url: str, manga_title: str):
        super().__init__(timeout=300)
        self.manga_url   = manga_url
        self.manga_title = manga_title

    @discord.ui.button(label=f"💴 {MANGA_PRICE}円を支払って読む", style=discord.ButtonStyle.success)
    async def pay_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(
            MangaPaymentModal(self.manga_url, self.manga_title)
        )

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.danger)
    async def cancel_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(content="❌ キャンセルしました。", embeds=[], view=None)
        self.stop()


class MangaSelect(Select):
    """検索結果から作品を選択するセレクトメニュー"""

    def __init__(self, results: list[dict]):
        options = [
            discord.SelectOption(label=r["title"][:100], value=r["url"])
            for r in results
        ]
        super().__init__(placeholder="読みたい作品を選択してください...", options=options)

    async def callback(self, interaction: discord.Interaction):
        from utils import OWNER_ID  # 遅延インポートで循環参照を回避

        manga_url = self.values[0]
        selected_title = next(
            (o.label for o in self.options if o.value == manga_url), "無題"
        )

        # オーナーは支払いなしで直接閲覧
        if interaction.user.id == OWNER_ID:
            await interaction.response.defer(ephemeral=True)
            pages = await get_pages(manga_url)
            if not pages:
                return await interaction.followup.send(
                    "⚠️ 漫画画像の取得に失敗しました。", ephemeral=True
                )
            view = MangaReaderView(pages, selected_title)
            return await interaction.followup.send(
                embed=view._make_embed(), view=view, ephemeral=True
            )

        # 通常ユーザー: 支払い案内
        embed = discord.Embed(
            title="📖 漫画閲覧 — 支払い確認",
            color=0xF7A800,
        )
        embed.add_field(name="作品名",   value=f"**{selected_title}**", inline=False)
        embed.add_field(name="閲覧料金", value=f"**¥{MANGA_PRICE}**（1回限り）", inline=False)
        embed.add_field(
            name="支払い方法",
            value=(
                f"1. PayPay アプリで **¥{MANGA_PRICE} のリンク** を作成してください\n"
                f"2. 「💴 {MANGA_PRICE}円を支払って読む」ボタンを押す\n"
                "3. 表示されるフォームにリンクを貼り付けてください\n"
                "4. 支払い確認後、すぐに閲覧できます"
            ),
            inline=False,
        )
        embed.set_footer(text=f"⚠️ 支払いは1回の閲覧のみ有効です。次回また¥{MANGA_PRICE}が必要です。")

        view = MangaPaymentView(manga_url, selected_title)
        await interaction.response.edit_message(embed=embed, view=view)


class MangaSearchModal(ui.Modal, title="漫画検索"):
    """パネルから検索するためのモーダル"""

    query_input = ui.TextInput(
        label="タイトル",
        placeholder="検索したい漫画のタイトルを入力...",
        required=True,
        max_length=100,
    )

    async def on_submit(self, interaction: discord.Interaction):
        from utils import OWNER_ID

        await interaction.response.defer(ephemeral=True)
        results = await search_manga(self.query_input.value)

        if not results:
            return await interaction.followup.send(
                "❌ 該当する漫画が見つかりませんでした。", ephemeral=True
            )

        is_owner_user = interaction.user.id == OWNER_ID
        desc = (
            f"「{self.query_input.value}」の検索結果です。\n\n🆓 **オーナー権限：完全無料で閲覧できます**"
            if is_owner_user
            else f"「{self.query_input.value}」の検索結果です。\n以下から作品を選ぶと **¥{MANGA_PRICE}** で閲覧できます。\n\n🆓 検索は無料です"
        )
        embed = discord.Embed(title="🔍 検索結果", description=desc, color=0x2B2D31)

        view = View()
        view.add_item(MangaSelect(results))
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


class MangaPanelView(ui.View):
    """常設パネル用ビュー（timeout=None で Bot 再起動後も有効）"""

    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(
        label="🔍 漫画を検索する",
        style=discord.ButtonStyle.primary,
        custom_id="manga_panel:search_v2",
    )
    async def search_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(MangaSearchModal())


# ==========================================
# Cog
# ==========================================

class MangaCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        """Bot 起動時にパネルの View を永続化登録"""
        self.bot.add_view(MangaPanelView())

    # ─── パネル更新ヘルパー ─────────────────────────────────────
    async def _update_all_panels(self):
        panels = load_manga_panels()
        alive  = []
        for loc in panels:
            try:
                ch  = self.bot.get_channel(loc["channel_id"]) or await self.bot.fetch_channel(loc["channel_id"])
                msg = await ch.fetch_message(loc["message_id"])
                await msg.edit(embed=make_panel_embed(), view=MangaPanelView())
                alive.append(loc)
            except Exception:
                pass  # 削除済みメッセージはリストから除外
        save_manga_panels(alive)

    # ─── /漫画 ── スラッシュ検索 ────────────────────────────────
    @app_commands.command(name="漫画", description="momon-ga.com から漫画を検索して閲覧します（閲覧は¥50）")
    @is_allowed()
    @app_commands.describe(query="検索したい漫画のタイトル")
    async def manga_search(self, interaction: discord.Interaction, query: str):
        from utils import OWNER_ID

        await interaction.response.defer(ephemeral=True)
        results = await search_manga(query)

        if not results:
            return await interaction.followup.send("❌ 該当する漫画が見つかりませんでした。", ephemeral=True)

        is_owner_user = interaction.user.id == OWNER_ID
        desc = (
            f"「{query}」の検索結果です。\n\n🆓 **オーナー権限：完全無料で閲覧できます**"
            if is_owner_user
            else f"「{query}」の検索結果です。\n以下から作品を選ぶと **¥{MANGA_PRICE}** で閲覧できます。\n\n🆓 検索は無料です"
        )
        embed = discord.Embed(title="🔍 検索結果", description=desc, color=0x2B2D31)

        view = View()
        view.add_item(MangaSelect(results))
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    # ─── /漫画パネル サブグループ ────────────────────────────────
    manga_panel = app_commands.Group(
        name="漫画パネル",
        description="漫画パネルの管理（設置・削除は管理者のみ）",
        default_permissions=discord.Permissions(administrator=True),
    )

    @manga_panel.command(name="set", description="このチャンネルに漫画検索パネルを設置します")
    async def panel_set(self, interaction: discord.Interaction):
        try:
            msg = await interaction.channel.send(embed=make_panel_embed(), view=MangaPanelView())
        except discord.Forbidden:
            return await safe_respond(interaction, "❌ チャンネルへの送信権限がありません。", ephemeral=True)

        panels = load_manga_panels()
        panels.append({
            "guild_id":   interaction.guild.id,
            "channel_id": interaction.channel.id,
            "message_id": msg.id,
        })
        save_manga_panels(panels)

        await safe_respond(
            interaction,
            f"✅ 漫画パネルを設置しました。チャンネル: {interaction.channel.mention}",
            ephemeral=True,
        )

    @manga_panel.command(name="remove", description="設置済みの漫画パネルを削除します")
    @app_commands.describe(message_id="削除するパネルのメッセージID（省略で全削除）")
    async def panel_remove(self, interaction: discord.Interaction, message_id: str = None):
        panels = load_manga_panels()
        if not panels:
            return await safe_respond(interaction, "❌ 設置されているパネルがありません。", ephemeral=True)

        removed   = 0
        remaining = []
        for loc in panels:
            if message_id is None or str(loc["message_id"]) == message_id:
                try:
                    ch  = self.bot.get_channel(loc["channel_id"]) or await self.bot.fetch_channel(loc["channel_id"])
                    msg = await ch.fetch_message(loc["message_id"])
                    await msg.delete()
                except Exception:
                    pass
                removed += 1
            else:
                remaining.append(loc)

        save_manga_panels(remaining)
        await safe_respond(interaction, f"✅ {removed}件のパネルを削除しました。", ephemeral=True)

    @manga_panel.command(name="update", description="設置済みの全パネルを最新の表示に更新します")
    async def panel_update(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self._update_all_panels()
        await interaction.followup.send("✅ パネルを更新しました。", ephemeral=True)

    @manga_panel.command(name="list", description="設置済みのパネル一覧を表示します")
    async def panel_list(self, interaction: discord.Interaction):
        panels = load_manga_panels()
        if not panels:
            return await safe_respond(interaction, "現在パネルは設置されていません。", ephemeral=True)

        lines = []
        for loc in panels:
            ch = self.bot.get_channel(loc["channel_id"])
            ch_str = ch.mention if ch else "ID:" + str(loc["channel_id"])
            msg_id = loc["message_id"]
            lines.append(f"• {ch_str} — メッセージID: `{msg_id}`")

        embed = discord.Embed(
            title="📋 設置済み漫画パネル一覧",
            description="\n".join(lines),
            color=0x2B2D31,
        )
        embed.set_footer(text="roru2026.")
        await safe_respond(interaction, embed=embed, ephemeral=True)

    # ─── /manga支払い設定 ────────────────────────────────────────
    @app_commands.command(
        name="manga支払い設定",
        description="漫画閲覧料金の受取 PayPay アカウントを設定します（オーナー専用）",
    )
    @is_owner()
    async def manga_paypay_setup(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        if uid not in load_paypay_data():
            return await safe_respond(
                interaction,
                "❌ PayPay アカウントが登録されていません。先に `/paypayログイン` で登録してください。",
                ephemeral=True,
            )

        save_manga_owner({"owner_id": uid})
        await safe_respond(
            interaction,
            f"✅ 漫画閲覧料金の受取 PayPay アカウントを設定しました。\n"
            f"ユーザー: {interaction.user.mention}\n閲覧料金: ¥{MANGA_PRICE}/回",
            ephemeral=True,
        )

    # ─── /html ── HTML ソース取得 ────────────────────────────────
    @app_commands.command(name="html", description="指定した URL の HTML ソースをファイルとして取得します")
    @is_allowed()
    @app_commands.describe(url="HTML を取得したい Web サイトの URL")
    async def get_html_source(self, interaction: discord.Interaction, url: str):
        await interaction.response.defer(ephemeral=True)

        if not (url.startswith("http://") or url.startswith("https://")):
            return await interaction.followup.send(
                "❌ 有効な URL（http:// または https:// から始まるもの）を入力してください。",
                ephemeral=True,
            )

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        return await interaction.followup.send(
                            f"❌ HTML の取得に失敗しました。ステータスコード: {resp.status}",
                            ephemeral=True,
                        )
                    html_text = await resp.text()
        except Exception as e:
            return await interaction.followup.send(f"❌ エラーが発生しました: {e}", ephemeral=True)

        parsed = urllib.parse.urlparse(url)
        domain   = parsed.netloc.replace(".", "_")
        filename = f"source_{domain or 'page'}.html"

        buf  = io.BytesIO(html_text.encode("utf-8"))
        file = discord.File(fp=buf, filename=filename)

        await interaction.followup.send(
            content=f"📄 **URL:** {url}\nHTML ソースをファイルとして出力しました。",
            file=file,
            ephemeral=True,
        )
        buf.close()


async def setup(bot: commands.Bot):
    await bot.add_cog(MangaCog(bot))
