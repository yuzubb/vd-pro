import discord
from discord.ext import commands
from discord import app_commands, ui
import json
import os
import uuid
from utils import is_allowed

SEMI_VENDING_FILE = "semi_vending_data.json"


# ──────────────────────────────────────────
#  JSON ユーティリティ
# ──────────────────────────────────────────

def load_data() -> dict:
    if os.path.exists(SEMI_VENDING_FILE):
        with open(SEMI_VENDING_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}


def save_data(data: dict):
    with open(SEMI_VENDING_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


# ──────────────────────────────────────────
#  パネルEmbedを構築するヘルパー
# ──────────────────────────────────────────

def build_panel_embed(panel: dict) -> discord.Embed:
    embed = discord.Embed(
        title=f"🛒 {panel['panel_name']}",
        color=discord.Color.blue()
    )
    embed.add_field(name="料金", value=f"`¥{panel.get('price', 0):,}`", inline=True)

    embed.add_field(
        name="購入方法",
        value="下の「購入する」ボタンを押してPayPayリンクと購入数を入力してください。",
        inline=False
    )
    embed.set_footer(text="roru2026.")

    image_url = panel.get("image_url")
    if image_url:
        embed.set_image(url=image_url)

    return embed


# ──────────────────────────────────────────
#  パネルメッセージをDiscord上で更新するヘルパー
# ──────────────────────────────────────────

async def _refresh_panel(guild: discord.Guild, panel_id: str, data: dict) -> bool:
    panel = data.get(panel_id)
    if not panel:
        return False
    channel = guild.get_channel(panel.get("channel_id", 0))
    if not channel:
        return False
    try:
        msg = await channel.fetch_message(panel["message_id"])
        embed = build_panel_embed(panel)
        await msg.edit(embed=embed, view=SemiVendingView(panel_id))
        return True
    except Exception as e:
        print(f"パネル更新エラー: {e}")
        return False


# ──────────────────────────────────────────
#  購入ボタンView（永続化）
# ──────────────────────────────────────────

class SemiVendingView(ui.View):
    def __init__(self, panel_id: str):
        super().__init__(timeout=None)
        self.panel_id = panel_id

        btn = ui.Button(
            label="🛒 購入する",
            style=discord.ButtonStyle.primary,
            custom_id=f"semi_buy_{panel_id}"
        )
        btn.callback = self.on_buy
        self.add_item(btn)

    async def on_buy(self, interaction: discord.Interaction):
        data = load_data()
        panel = data.get(self.panel_id, {})
        if not panel.get("products"):
            await interaction.response.send_message(
                "❌ 商品がないため購入できません。詳細は鯖主にお問い合わせください。",
                ephemeral=True
            )
            return
        await interaction.response.send_modal(SemiVendingPurchaseModal(self.panel_id))


# ──────────────────────────────────────────
#  /半自販機 ── Step1: チャンネル選択View
#  チャンネル選択後にモーダルを開く
# ──────────────────────────────────────────

class SemiVendingChannelSelectView(ui.View):
    def __init__(self, image_url: str | None):
        super().__init__(timeout=120)
        self.image_url = image_url

    @ui.select(
        cls=ui.ChannelSelect,
        placeholder="リクエスト通知チャンネルを選択してください",
        channel_types=[discord.ChannelType.text]
    )
    async def channel_select(self, interaction: discord.Interaction, select: ui.ChannelSelect):
        notify_channel = select.values[0]
        await interaction.response.send_modal(
            SemiVendingCreateModal(self.image_url, notify_channel.id)
        )


# ──────────────────────────────────────────
#  /半自販機 ── Step2: パネル作成モーダル
#  フィールド: パネル名 / 料金
#  image・notify_channel_id は外から受け取る
# ──────────────────────────────────────────

class SemiVendingCreateModal(ui.Modal, title="半自販機パネル作成"):
    def __init__(self, image_url: str | None, notify_channel_id: int):
        super().__init__(timeout=300)
        self.image_url = image_url
        self.notify_channel_id = notify_channel_id

    panel_name = ui.TextInput(
        label="パネル名",
        placeholder="例: デジタルコンテンツショップ",
        required=True,
        max_length=50
    )

    price_input = ui.TextInput(
        label="料金（円）",
        placeholder="例: 1000",
        required=True,
        max_length=10
    )

    async def on_submit(self, interaction: discord.Interaction):
        # 料金バリデーション
        price_raw = self.price_input.value.strip()
        if not price_raw.isdigit() or int(price_raw) < 1:
            await interaction.response.send_message("❌ 料金は1以上の整数を入力してください。", ephemeral=True)
            return

        notify_channel = interaction.guild.get_channel(self.notify_channel_id)
        if not notify_channel:
            await interaction.response.send_message("❌ 選択されたチャンネルが見つかりません。", ephemeral=True)
            return

        data = load_data()
        panel_id = str(interaction.id)

        data[panel_id] = {
            "panel_name": self.panel_name.value.strip(),
            "price": int(price_raw),
            "guild_id": interaction.guild.id,
            "owner_id": interaction.user.id,
            "notify_channel_id": notify_channel.id,
            "channel_id": interaction.channel.id,
            "message_id": None,
            "image_url": self.image_url,
            "products": {},   # {prod_id: {name, content}}
            "orders": {}
        }
        save_data(data)

        embed = build_panel_embed(data[panel_id])
        view = SemiVendingView(panel_id)

        await interaction.response.send_message(
            f"✅ 半自販機パネルを設置しました。通知先: {notify_channel.mention}\n`/半自販機商品追加` で商品を追加してください。",
            ephemeral=True
        )
        msg = await interaction.channel.send(embed=embed, view=view)

        data[panel_id]["message_id"] = msg.id
        save_data(data)


# ──────────────────────────────────────────
#  /半自販機商品追加 ── 商品追加モーダル
#  フィールド: 商品一覧（改行区切り） / 承認後DM内容
# ──────────────────────────────────────────

class SemiVendingAddProductModal(ui.Modal, title="商品追加"):
    def __init__(self, panel_id: str):
        super().__init__(timeout=300)
        self.panel_id = panel_id

    products_input = ui.TextInput(
        label="追加する商品（1行1商品・承認後DMに送信）",
        style=discord.TextStyle.long,
        placeholder="例:\nhttps://example.com/itemA\nhttps://example.com/itemB\nクーポンコード: XXXX",
        required=True,
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        lines = [l.strip() for l in self.products_input.value.strip().splitlines() if l.strip()]
        if not lines:
            await interaction.response.send_message("❌ 商品を1つ以上入力してください。", ephemeral=True)
            return

        data = load_data()
        panel = data.get(self.panel_id)
        if not panel:
            await interaction.response.send_message("❌ パネルが見つかりません。", ephemeral=True)
            return

        added = []
        for item in lines:
            prod_id = str(uuid.uuid4())[:8]
            panel.setdefault("products", {})[prod_id] = {
                "name": item,
                "content": item
            }
            added.append(f"・`{item}`")

        save_data(data)

        updated = await _refresh_panel(interaction.guild, self.panel_id, data)
        result = "✅ 以下の商品を追加しました：\n" + "\n".join(added)
        if not updated:
            result += "\n⚠️ パネルの自動更新に失敗しました。"
        await interaction.response.send_message(result, ephemeral=True)


# ──────────────────────────────────────────
#  購入モーダル（購入ボタン押下後）
# ──────────────────────────────────────────

class SemiVendingPurchaseModal(ui.Modal, title="購入情報を入力"):
    def __init__(self, panel_id: str):
        super().__init__(timeout=300)
        self.panel_id = panel_id

    paypay_link = ui.TextInput(
        label="PayPay送金リンク",
        placeholder="https://pay.paypay.ne.jp/...",
        required=True,
        max_length=300
    )

    quantity = ui.TextInput(
        label="購入したい数",
        placeholder="例: 1",
        required=True,
        max_length=5
    )

    async def on_submit(self, interaction: discord.Interaction):
        qty_raw = self.quantity.value.strip()
        if not qty_raw.isdigit() or int(qty_raw) < 1:
            await interaction.response.send_message("❌ 購入数は1以上の整数を入力してください。", ephemeral=True)
            return

        qty = int(qty_raw)
        paypay = self.paypay_link.value.strip()

        data = load_data()
        panel = data.get(self.panel_id)
        if not panel:
            await interaction.response.send_message("❌ このパネルのデータが見つかりません。", ephemeral=True)
            return

        notify_channel_id = panel.get("notify_channel_id")
        if not notify_channel_id:
            await interaction.response.send_message(
                "❌ 通知チャンネルが設定されていません。管理者にお問い合わせください。", ephemeral=True
            )
            return

        notify_channel = interaction.guild.get_channel(notify_channel_id)
        if not notify_channel:
            await interaction.response.send_message("❌ 通知チャンネルが見つかりません。管理者にお問い合わせください。", ephemeral=True)
            return

        products = panel.get("products", {})
        prod_list_str = "\n".join(f"・{p['name']}" for p in products.values()) if products else "（商品未設定）"

        # ⑨ 在庫数チェック（在庫が足りない場合は注文を受け付けない）
        stock_count = len(products)
        if stock_count < qty:
            await interaction.response.send_message(
                f"❌ 在庫が不足しています。\nご希望数: {qty}個 / 現在の在庫: {stock_count}個",
                ephemeral=True
            )
            return

        price = panel.get("price", 0)
        total = price * qty

        order_id = str(uuid.uuid4())[:8]
        panel.setdefault("orders", {})[order_id] = {
            "buyer_id": interaction.user.id,
            "buyer_name": str(interaction.user),
            "price": price,
            "quantity": qty,
            "total": total,
            "paypay_link": paypay,
            "status": "pending",
            "panel_name": panel["panel_name"]
        }
        save_data(data)

        # 通知チャンネルへのリクエストパネル
        notify_embed = discord.Embed(title="🛍️ 新しい購入リクエスト", color=discord.Color.orange())
        notify_embed.add_field(name="注文ID", value=f"`{order_id}`", inline=False)
        notify_embed.add_field(
            name="依頼者",
            value=f"{interaction.user.mention}（{interaction.user.name}）",
            inline=False
        )
        notify_embed.add_field(name="パネル名", value=f"`{panel['panel_name']}`", inline=True)
        notify_embed.add_field(name="購入数", value=f"`{qty}個`", inline=True)
        notify_embed.add_field(name="合計金額", value=f"`¥{total:,}`", inline=True)
        notify_embed.add_field(name="取扱商品", value=prod_list_str, inline=False)
        notify_embed.add_field(name="PayPay送金リンク", value=paypay, inline=False)
        notify_embed.set_footer(text="roru2026.")

        approve_view = SemiVendingApproveView(self.panel_id, order_id)
        await notify_channel.send(embed=notify_embed, view=approve_view)

        await interaction.response.send_message(
            "✅ 購入リクエストを送信しました。管理者が確認後、商品をお届けします。",
            ephemeral=True
        )


# ──────────────────────────────────────────
#  承認View（管理者向け通知に付くボタン）
# ──────────────────────────────────────────

class SemiVendingApproveView(ui.View):
    def __init__(self, panel_id: str, order_id: str):
        super().__init__(timeout=None)
        self.panel_id = panel_id
        self.order_id = order_id

        btn = ui.Button(
            label="✅ 承認",
            style=discord.ButtonStyle.green,
            custom_id=f"semi_approve_{panel_id}_{order_id}"
        )
        btn.callback = self.on_approve
        self.add_item(btn)

    async def on_approve(self, interaction: discord.Interaction):
        data = load_data()
        order = data.get(self.panel_id, {}).get("orders", {}).get(self.order_id)
        if not order:
            await interaction.response.send_message("❌ 注文データが見つかりません。", ephemeral=True)
            return
        if order.get("status") == "approved":
            await interaction.response.send_message("⚠️ この注文はすでに承認済みです。", ephemeral=True)
            return

        confirm_embed = discord.Embed(
            title="⚠️ 本当に承認しますか？",
            description="承認を押すと依頼者に商品が発送されます。",
            color=discord.Color.yellow()
        )
        confirm_embed.set_footer(text="roru2026.")
        await interaction.response.send_message(
            embed=confirm_embed,
            view=SemiVendingConfirmView(self.panel_id, self.order_id),
            ephemeral=True
        )


# ──────────────────────────────────────────
#  承認確認View（はい / いいえ）
# ──────────────────────────────────────────

class SemiVendingConfirmView(ui.View):
    def __init__(self, panel_id: str, order_id: str):
        super().__init__(timeout=60)
        self.panel_id = panel_id
        self.order_id = order_id

    @ui.button(label="はい", style=discord.ButtonStyle.green)
    async def confirm_yes(self, interaction: discord.Interaction, button: ui.Button):
        data = load_data()
        panel = data.get(self.panel_id)
        if not panel:
            await interaction.response.send_message("❌ パネルデータが見つかりません。", ephemeral=True)
            return

        order = panel.get("orders", {}).get(self.order_id)
        if not order:
            await interaction.response.send_message("❌ 注文データが見つかりません。", ephemeral=True)
            return
        if order.get("status") == "approved":
            await interaction.response.send_message("⚠️ この注文はすでに承認済みです。", ephemeral=True)
            return

        # ③ 商品リストを購入数分取り出してDMに送る（承認時に在庫を消費するよう修正）
        products = panel.get("products", {})
        # 在庫キーのリストを取得
        prod_keys = list(products.keys())
        qty = order.get("quantity", 1)

        # 実在庫数チェック
        if len(prod_keys) < qty:
            await interaction.response.send_message(
                f"❌ 在庫が不足しています。\n必要数: {qty}個 / 現在の在庫: {len(prod_keys)}個\n在庫を補充してから再度承認してください。",
                ephemeral=True
            )
            return

        # qty 個分のキーを取り出し
        keys_to_send = prod_keys[:qty]
        items_to_send = [products[k]["content"] for k in keys_to_send if products[k].get("content")]
        product_content = "\n".join(items_to_send) if items_to_send else "（商品内容が設定されていません）"

        buyer = interaction.guild.get_member(order["buyer_id"])
        if not buyer:
            try:
                buyer = await interaction.client.fetch_user(order["buyer_id"])
            except Exception:
                buyer = None

        sent_ok = False
        if buyer:
            try:
                dm_embed = discord.Embed(title="📦 商品をお届けします", color=discord.Color.green())
                dm_embed.add_field(name="パネル名", value=f"`{panel['panel_name']}`", inline=False)
                dm_embed.add_field(name="購入数", value=f"`{order['quantity']}個`", inline=True)
                dm_embed.add_field(name="合計金額", value=f"`¥{order.get('total', 0):,}`", inline=True)
                dm_embed.add_field(name="商品内容", value=product_content, inline=False)
                dm_embed.set_footer(text="roru2026.")
                await buyer.send(embed=dm_embed)
                sent_ok = True
            except discord.Forbidden:
                pass

        order["status"] = "approved"
        # ③ 発送した商品を在庫から削除して保存
        for k in keys_to_send:
            panel["products"].pop(k, None)
        save_data(data)

        # ログチャンネルに実績を出力
        log_channel_id = panel.get("log_channel_id")
        if log_channel_id:
            log_channel = interaction.guild.get_channel(log_channel_id)
            if log_channel:
                log_embed = discord.Embed(title="📊 購入実績", color=discord.Color.green())
                log_embed.add_field(name="パネル名", value=f"`{panel['panel_name']}`", inline=True)
                log_embed.add_field(name="購入者", value=f"{buyer.mention if buyer else order['buyer_name']}", inline=True)
                log_embed.add_field(name="購入数", value=f"`{order['quantity']}個`", inline=True)
                log_embed.add_field(name="料金", value=f"`¥{order.get('total', 0):,}`", inline=True)
                log_embed.set_footer(text="roru2026.")
                try:
                    await log_channel.send(embed=log_embed)
                except Exception:
                    pass

        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)

        if sent_ok:
            await interaction.response.send_message(
                f"✅ 承認完了！{buyer.mention if buyer else '依頼者'} のDMに商品を発送しました。",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "⚠️ 承認しましたが、依頼者のDMが開放されていないため送れませんでした。手動で対応してください。",
                ephemeral=True
            )

    @ui.button(label="いいえ", style=discord.ButtonStyle.red)
    async def confirm_no(self, interaction: discord.Interaction, button: ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.send_message("❌ 承認をキャンセルしました。", ephemeral=True)


# ──────────────────────────────────────────
#  Cog
# ──────────────────────────────────────────

class SemiVendingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        data = load_data()
        for panel_id, panel in data.items():
            self.bot.add_view(SemiVendingView(panel_id))
            for order_id, order in panel.get("orders", {}).items():
                if order.get("status") == "pending":
                    self.bot.add_view(SemiVendingApproveView(panel_id, order_id))

    async def panel_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        data = load_data()
        # ④ オーナーチェックを追加（同サーバー他人のパネルが候補に出るバグを修正）
        return [
            app_commands.Choice(name=p.get("panel_name", "名称未設定"), value=pid)
            for pid, p in data.items()
            if p.get("guild_id") == interaction.guild.id
            and p.get("owner_id") == interaction.user.id
            and current.lower() in p.get("panel_name", "").lower()
        ][:25]

    # ── /半自販機 ──
    @app_commands.command(name="半自販機", description="半自販機パネルを設置します")
    @is_allowed()
    @app_commands.describe(image="パネルに表示する画像（任意）")
    async def semi_vending(
        self,
        interaction: discord.Interaction,
        image: discord.Attachment | None = None
    ):
        image_url = image.url if image else None
        view = SemiVendingChannelSelectView(image_url)
        await interaction.response.send_message(
            "**Step 1/2**　リクエスト通知チャンネルを選択してください：",
            view=view,
            ephemeral=True
        )

    # ── /半自販機商品追加 ──
    @app_commands.command(name="半自販機商品追加", description="半自販機パネルに商品を追加します")
    @is_allowed()
    @app_commands.describe(panel="商品を追加するパネル")
    @app_commands.autocomplete(panel=panel_autocomplete)
    async def semi_vending_add_product(
        self,
        interaction: discord.Interaction,
        panel: str
    ):
        data = load_data()
        panel_data = data.get(panel)
        if not panel_data or panel_data.get("guild_id") != interaction.guild.id or panel_data.get("owner_id") != interaction.user.id:
            await interaction.response.send_message("❌ 指定されたパネルが見つかりません。", ephemeral=True)
            return
        await interaction.response.send_modal(SemiVendingAddProductModal(panel))

    # ── /半自販機商品削除 ──
    @app_commands.command(name="半自販機商品削除", description="半自販機パネルから商品を削除します")
    @is_allowed()
    @app_commands.describe(panel="対象のパネル")
    @app_commands.autocomplete(panel=panel_autocomplete)
    async def semi_vending_remove_product(
        self,
        interaction: discord.Interaction,
        panel: str
    ):
        data = load_data()
        panel_data = data.get(panel)
        if not panel_data or panel_data.get("guild_id") != interaction.guild.id or panel_data.get("owner_id") != interaction.user.id:
            await interaction.response.send_message("❌ 指定されたパネルが見つかりません。", ephemeral=True)
            return

        products = panel_data.get("products", {})
        if not products:
            await interaction.response.send_message("❌ このパネルには商品がありません。", ephemeral=True)
            return

        options = []
        for pid, p in products.items():
            label = p["name"][:100].strip() or f"商品 ({pid})"
            options.append(discord.SelectOption(label=label, value=pid))
        options = options[:25]

        class RemoveSelect(ui.Select):
            def __init__(self_inner):
                super().__init__(
                    placeholder="削除する商品を選んでください",
                    options=options,
                    min_values=1,
                    max_values=1
                )

            async def callback(self_inner, inter: discord.Interaction):
                prod_id = self_inner.values[0]
                prod_name = panel_data["products"].get(prod_id, {}).get("name", "不明")
                del panel_data["products"][prod_id]
                save_data(data)
                updated = await _refresh_panel(inter.guild, panel, data)
                result = f"✅ 商品「{prod_name[:50]}」を削除しました。"
                if not updated:
                    result += "\n⚠️ パネルの自動更新に失敗しました。"
                await inter.response.send_message(result, ephemeral=True)

        class RemoveView(ui.View):
            def __init__(self_inner):
                super().__init__(timeout=60)
                self_inner.add_item(RemoveSelect())

        try:
            await interaction.response.send_message(
                f"削除する商品を選んでください（{len(options)}件）：",
                view=RemoveView(),
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ 商品一覧の表示に失敗しました: {e}", ephemeral=True
            )

    # ── /半自販機ログ出力 ──
    @app_commands.command(name="半自販機ログ出力", description="購入実績を出力するログチャンネルをサーバー全体で設定します")
    @is_allowed()
    @app_commands.describe(channel="実績を出力するチャンネル")
    async def semi_vending_log(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel
    ):
        data = load_data()
        guild_id = interaction.guild.id

        updated = 0
        all_approved = []
        for panel in data.values():
            if panel.get("guild_id") != guild_id:
                continue
            panel["log_channel_id"] = channel.id
            updated += 1
            all_approved.extend(
                o for o in panel.get("orders", {}).values()
                if o.get("status") == "approved"
            )

        if updated == 0:
            await interaction.response.send_message(
                "❌ このサーバーに半自販機パネルが見つかりません。", ephemeral=True
            )
            return

        save_data(data)

        await interaction.response.send_message(
            f"✅ ログチャンネルを {channel.mention} に設定しました。（{updated}件のパネルに適用）\n"
            "今後の購入承認時に実績が自動出力されます。",
            ephemeral=True
        )

        if all_approved:
            total_qty = sum(o.get("quantity", 0) for o in all_approved)
            total_amt = sum(o.get("total", 0) for o in all_approved)
            summary_embed = discord.Embed(title="📊 半自販機 購入実績サマリー", color=discord.Color.green())
            summary_embed.add_field(name="累計取引件数", value=f"`{len(all_approved)}件`", inline=True)
            summary_embed.add_field(name="累計購入数", value=f"`{total_qty}個`", inline=True)
            summary_embed.add_field(name="累計売上", value=f"`¥{total_amt:,}`", inline=True)
            summary_embed.set_footer(text="roru2026.")
            await channel.send(embed=summary_embed)

    # ── /半自販機作成済みパネル設置 ──
    @app_commands.command(name="半自販機作成済みパネル設置", description="作成済みの半自販機パネルを現在のチャンネルに再設置します")
    @is_allowed()
    @app_commands.describe(panel="再設置するパネル")
    @app_commands.autocomplete(panel=panel_autocomplete)
    async def semi_vending_reinstall(
        self,
        interaction: discord.Interaction,
        panel: str
    ):
        data = load_data()
        panel_data = data.get(panel)
        if not panel_data or panel_data.get("guild_id") != interaction.guild.id:
            await interaction.response.send_message("❌ 指定されたパネルが見つかりません。", ephemeral=True)
            return

        embed = build_panel_embed(panel_data)
        view = SemiVendingView(panel)

        await interaction.response.send_message(
            f"✅ 「{panel_data['panel_name']}」を再設置しました。", ephemeral=True
        )
        msg = await interaction.channel.send(embed=embed, view=view)

        # channel_id と message_id を新しい設置先に更新
        panel_data["channel_id"] = interaction.channel.id
        panel_data["message_id"] = msg.id
        save_data(data)

    # ── /半自販機パネル完全削除 ──
    @app_commands.command(name="半自販機パネル完全削除", description="作成済みの半自販機パネルをデータごと完全に削除します")
    @is_allowed()
    @app_commands.describe(panel="削除するパネル")
    @app_commands.autocomplete(panel=panel_autocomplete)
    async def semi_vending_delete_panel(
        self,
        interaction: discord.Interaction,
        panel: str
    ):
        data = load_data()
        panel_data = data.get(panel)
        if not panel_data or panel_data.get("guild_id") != interaction.guild.id:
            await interaction.response.send_message("❌ 指定されたパネルが見つかりません。", ephemeral=True)
            return

        panel_name = panel_data.get("panel_name", "不明")

        # Discord上のパネルメッセージも削除
        channel = interaction.guild.get_channel(panel_data.get("channel_id", 0))
        if channel and panel_data.get("message_id"):
            try:
                msg = await channel.fetch_message(panel_data["message_id"])
                await msg.delete()
            except Exception:
                pass  # 既に削除済み等は無視

        del data[panel]
        save_data(data)

        await interaction.response.send_message(
            f"✅ 「{panel_name}」を完全に削除しました。", ephemeral=True
        )

    # ── /半自販機一覧 ──
    @app_commands.command(name="半自販機一覧", description="このサーバーの半自販機一覧を表示します")
    @is_allowed()
    async def semi_vending_list(self, interaction: discord.Interaction):
        data = load_data()
        # ③ 自分が作成したパネルのみ表示（他ユーザーのパネルが見えるバグを修正）
        panels = [
            (pid, p) for pid, p in data.items()
            if p.get("guild_id") == interaction.guild.id
            and p.get("owner_id") == interaction.user.id
        ]

        if not panels:
            await interaction.response.send_message("❌ このサーバーに半自販機パネルが見つかりません。", ephemeral=True)
            return

        embed = discord.Embed(title="🛒 半自販機一覧", color=discord.Color.blue())
        for pid, p in panels:
            orders = p.get("orders", {})
            pending = sum(1 for o in orders.values() if o.get("status") == "pending")
            approved = sum(1 for o in orders.values() if o.get("status") == "approved")
            embed.add_field(
                name=p.get("panel_name", "不明"),
                value=(
                    f"料金: `¥{p.get('price', 0):,}`\n"
                    f"商品数: `{len(p.get('products', {}))}種類`\n"
                    f"未対応: `{pending}件` / 承認済み: `{approved}件`"
                ),
                inline=True
            )
        embed.set_footer(text="roru2026.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(SemiVendingCog(bot))
