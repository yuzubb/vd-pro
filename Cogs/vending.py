import discord
from discord.ext import commands
from discord import app_commands, ui
import json
import os
import uuid
import io
from utils import is_allowed
import paypayu
import random

VENDING_DATA_FILE = "vending_data.json"
PAYPAY_DATA_FILE = "paypay_data.json"
STOCK_DIR_BASE = "stock_files"
STOCK_NOTIFICATION_DATA_FILE = "stock_notification_data.json"
COUPON_DATA_FILE = "coupon_data.json"
ROLE_ASSIGNMENT_DATA_FILE = "role_assignment_data.json"

def load_json(file_path):
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_json(file_path, data):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def load_paypay_data():
    if os.path.exists(PAYPAY_DATA_FILE):
        with open(PAYPAY_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def load_stock_notification_data():
    if os.path.exists(STOCK_NOTIFICATION_DATA_FILE):
        with open(STOCK_NOTIFICATION_DATA_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_stock_notification_data(data):
    with open(STOCK_NOTIFICATION_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def load_coupon_data():
    if os.path.exists(COUPON_DATA_FILE):
        with open(COUPON_DATA_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_coupon_data(data):
    with open(COUPON_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def load_role_assignment_data():
    if os.path.exists(ROLE_ASSIGNMENT_DATA_FILE):
        with open(ROLE_ASSIGNMENT_DATA_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_role_assignment_data(data):
    with open(ROLE_ASSIGNMENT_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

async def vending_machine_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    vending_data = load_json(VENDING_DATA_FILE)
    user_id_str = str(interaction.user.id)
    
    user_machines = [
        (vm_id, vm_data) for vm_id, vm_data in vending_data.items() 
        if vm_data.get("owner_id") == user_id_str
    ]

    return [
        app_commands.Choice(name=vm_data.get("name", "名称未設定"), value=vm_id)
        for vm_id, vm_data in user_machines
        if current.lower() in vm_data.get("name", "").lower()
    ]

async def coupon_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    coupon_data = load_coupon_data()
    user_id_str = str(interaction.user.id)
    
    user_coupons = [
        (coupon_code, coupon_info) for coupon_code, coupon_info in coupon_data.items()
        if coupon_info.get("owner_id") == user_id_str
    ]
    
    choices = []
    for coupon_code, coupon_info in user_coupons:
        if current.lower() in coupon_code.lower():
            discount = coupon_info.get("discount", 0)
            vending_machine_id = coupon_info.get("vending_machine_id", "")
            vending_data = load_json(VENDING_DATA_FILE)
            vm_name = vending_data.get(vending_machine_id, {}).get("name", "不明")
            choices.append(app_commands.Choice(
                name=f"{coupon_code} (-{discount}円) [{vm_name}]",
                value=coupon_code
            ))
    
    return choices[:25]

async def role_assignment_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    role_data = load_role_assignment_data()
    vending_data = load_json(VENDING_DATA_FILE)
    
    choices = []
    for vm_id, role_info in role_data.items():
        if role_info.get("guild_id") == interaction.guild.id:
            vm = vending_data.get(vm_id)
            if vm and vm.get("owner_id") == str(interaction.user.id):
                vm_name = vm.get("name", "不明な自販機")
                if current.lower() in vm_name.lower():
                    choices.append(app_commands.Choice(name=vm_name, value=vm_id))
    
    return choices[:25]

async def handle_error(interaction: discord.Interaction, error: Exception, ephemeral: bool = True):
    """統一エラーハンドリング"""
    try:
        embed = discord.Embed(
            title="エラーが発生しました",
            description=f"```{str(error)}```",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text="Developer @roru2026.")
        
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
    except:
        print(f"Error sending error message: {error}")

async def check_stock(interaction: discord.Interaction, products: list):
    embed = discord.Embed(
        title="在庫・販売数情報",
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow()
    )
    embed.set_footer(text="Developer @roru2026.")

    if not products:
        embed.description = "この自販機には商品が登録されていません。"
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    for product in products:
        product_name = product.get("name", "不明")
        sales_count = product.get("sales_count", 0)
        
        if product.get("infinite_stock"):
            # 無限在庫の場合
            embed.add_field(
                name=f"{product_name}", 
                value=f"```在庫数: ∞個\n販売数: {sales_count}個```", 
                inline=False
            )
        else:
            # 有限在庫の場合
            stock_file = product.get("stock_file")
            
            if not stock_file:
                embed.add_field(
                    name=f"{product_name}", 
                    value=f"```在庫数: 不明\n販売数: {sales_count}個```", 
                    inline=False
                )
                continue
                
            try:
                with open(stock_file, "r", encoding="utf-8") as file:
                    lines = [line for line in file.readlines() if line.strip()]
                    stock_count = len(lines)
                    embed.add_field(
                        name=f"{product_name}", 
                        value=f"```在庫数: {stock_count}個\n販売数: {sales_count}個```", 
                        inline=False
                    )

            except FileNotFoundError:
                embed.add_field(
                    name=f"{product_name}", 
                    value=f"```在庫数: 0個\n販売数: {sales_count}個```", 
                    inline=False
                )
            except Exception as e:
                await handle_error(interaction, e)

    await interaction.followup.send(embed=embed, ephemeral=True)


class VendingMachineCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        """Cogロード時に永続化Viewを復元"""
        vending_data = load_json(VENDING_DATA_FILE)
        
        # 自販機パネル用Viewのみ復元（custom_idがvm_idごとに一意）
        # ProductSelectViewForStock/WithdrawStockView/ContentViewは
        # ephemeralな一時メッセージ用なので再起動後の復元は不要
        count = 0
        for vm_id in vending_data.keys():
            view = VendingMachineCog.VendingMachineView(vm_id, self.bot)
            self.bot.add_view(view)
            count += 1
        
        print(f"[Vending] {count}件の自販機ViewをBot起動時に復元しました。")

    @app_commands.command(name="自販機作成", description="自販機を作成します")
    @is_allowed()
    @app_commands.describe(name="自販機の名前")
    async def vm_create(self, interaction: discord.Interaction, name: str):
        user_id = str(interaction.user.id)
        vending_data = load_json(VENDING_DATA_FILE)
        new_vm_id = str(uuid.uuid4())

        # PayPayアカウントが登録されているかチェック
        paypay_data = load_paypay_data()
        paypay_id = user_id if user_id in paypay_data else None

        vending_data[new_vm_id] = {
            "name": name,
            "owner_id": user_id,
            "paypay_id": paypay_id,
            "log_channel_id": None,
            "private_log_channel_id": None,
            "products": []
        }
        save_json(VENDING_DATA_FILE, vending_data)

        if paypay_id:
            await interaction.response.send_message(f"自販機「{name}」を作成しました。\n**自販機ID:** `{new_vm_id}`", ephemeral=True)
        else:
            await interaction.response.send_message(f"自販機「{name}」を作成しました。\n**自販機ID:** `{new_vm_id}`\nPayPayアカウントが未登録です。`/paypay登録` を実行してください。", ephemeral=True)

    @app_commands.command(name="公開ログ設定", description="公開販売ログを送信するチャンネルを設定します")
    @is_allowed()
    @app_commands.autocomplete(vending_machine_id=vending_machine_autocomplete)
    @app_commands.describe(vending_machine_id="自販機", channel="ログを送信するチャンネル")
    async def vm_set_log(self, interaction: discord.Interaction, vending_machine_id: str, channel: discord.TextChannel):
        vending_data = load_json(VENDING_DATA_FILE)
        vm = vending_data.get(vending_machine_id)
        if not vm or vm.get("owner_id") != str(interaction.user.id):
            return await interaction.response.send_message("指定された自販機が見つかりません。", ephemeral=True)
        
        vm["log_channel_id"] = channel.id
        save_json(VENDING_DATA_FILE, vending_data)
        await interaction.response.send_message(f"自販機「{vm['name']}」のログチャンネルを {channel.mention} に設定しました。", ephemeral=True)

    @app_commands.command(name="非公開ログ設定", description="非公開販売ログを送信するチャンネルを設定します")
    @is_allowed()
    @app_commands.autocomplete(vending_machine_id=vending_machine_autocomplete)
    @app_commands.describe(vending_machine_id="自販機", channel="ログを送信するチャンネル")
    async def vm_set_private_log(self, interaction: discord.Interaction, vending_machine_id: str, channel: discord.TextChannel):
        vending_data = load_json(VENDING_DATA_FILE)
        vm = vending_data.get(vending_machine_id)
        if not vm or vm.get("owner_id") != str(interaction.user.id):
            return await interaction.response.send_message("指定された自販機が見つかりません。", ephemeral=True)
        
        vm["private_log_channel_id"] = channel.id
        save_json(VENDING_DATA_FILE, vending_data)
        
        await interaction.response.send_message(f"自販機「{vm['name']}」の非公開ログチャンネルを {channel.mention} に設定しました。", ephemeral=True)

    @app_commands.command(name="商品追加", description="指定した自販機に新しい商品を追加します")
    @is_allowed()
    @app_commands.autocomplete(vending_machine_id=vending_machine_autocomplete)
    @app_commands.describe(vending_machine_id="商品を登録する自販機",name="商品名",description="商品説明（任意）",price="価格",emoji="商品絵文字")
    async def vm_add_product(self, interaction: discord.Interaction, vending_machine_id: str, name: str, price: int, description: str = None, emoji: str=None):
        vending_data = load_json(VENDING_DATA_FILE)
        vm = vending_data.get(vending_machine_id)
        if not vm or vm.get("owner_id") != str(interaction.user.id):
            return await interaction.response.send_message("指定された自販機が見つかりません。", ephemeral=True)

        product_id = str(uuid.uuid4())
        stock_file_path = os.path.join(STOCK_DIR_BASE, f"{product_id}.txt")
        with open(stock_file_path, "w", encoding="utf-8") as f:
            pass

        new_product = {
            "product_id": product_id,
            "name": name,
            "description": description or "",
            "price": price,
            "emoji": emoji,
            "stock_file": stock_file_path,
            "infinite_stock": False,
            "infinite_content": None,
            "sales_count": 0
        }
        vm["products"].append(new_product)
        save_json(VENDING_DATA_FILE, vending_data)
        await interaction.response.send_message(f"自販機「{vm['name']}」に商品「{name}」を追加しました。", ephemeral=True)

    @app_commands.command(name="在庫追加", description="商品の在庫を追加します")
    @is_allowed()
    @app_commands.autocomplete(vending_machine_id=vending_machine_autocomplete)
    @app_commands.describe(vending_machine_id="自販機", stock_type="在庫タイプ", stock_file="在庫ファイル(txtのみ)")
    @app_commands.choices(stock_type=[
        app_commands.Choice(name="有限", value="finite"),
        app_commands.Choice(name="無限", value="infinite")
    ])
    async def vm_add_stock(self, interaction: discord.Interaction, vending_machine_id: str, stock_type: str, stock_file: discord.Attachment = None):
        
        if stock_file and not stock_file.filename.endswith(".txt"):
            return await interaction.response.send_message("ファイル形式は.txtのみ対応しています。", ephemeral=True)

        vending_data = load_json(VENDING_DATA_FILE)
        vm = vending_data.get(vending_machine_id)
        if not vm or vm.get("owner_id") != str(interaction.user.id):
            return await interaction.response.send_message("指定された自販機が見つかりません。", ephemeral=True)

        products = vm.get("products")
        if not products:
            return await interaction.response.send_message("在庫を追加できる商品がありません。", ephemeral=True)
        
        view = VendingMachineCog.ProductSelectViewForStock(products, stock_file, stock_type)
        await interaction.response.send_message("在庫追加を行う商品を選択してください:", view=view, ephemeral=True)

    @app_commands.command(name="自販機設置", description="自販機パネルを設置します")
    @is_allowed()
    @app_commands.autocomplete(vending_machine_id=vending_machine_autocomplete)
    @app_commands.describe(
        vending_machine_id="設置する自販機", 
        panel_title="パネルのタイトル",
        panel_description="パネルの説明文",
        panel_image="パネルの画像"
    )
    async def vm_setup(self, interaction: discord.Interaction, vending_machine_id: str, panel_title: str = None, panel_description: str = None, panel_image: discord.Attachment = None):
        vending_data = load_json(VENDING_DATA_FILE)
        vm = vending_data.get(vending_machine_id)
        # ⑧ オーナーチェックを追加（他人の自販機IDで設置できるバグを修正）
        if not vm or vm.get("owner_id") != str(interaction.user.id):
            return await interaction.response.send_message("指定された自販機が見つかりません。", ephemeral=True)

        # カスタムパネルかデフォルトパネルかを判定
        is_custom = any([panel_title, panel_description, panel_image])
        
        if is_custom:
            # カスタムパネル
            title = panel_title if panel_title else "自販機"
            description = panel_description if panel_description else "購入したい商品を下のメニューから選択してください。"
            embed = discord.Embed(title=title, description=description, color=discord.Color.green())
            
            if panel_image:
                embed.set_image(url=panel_image.url)
        else:
            # デフォルトパネル
            embed = discord.Embed(title="自販機", description="購入したい商品を下のメニューから選択してください。", color=discord.Color.green())
        
        embed.set_footer(text="Developer @roru2026.")
        
        # 商品フィールドを統一して追加
        products = vm.get("products", [])
        if products:
            for p in products:
                price_text = f"```価格: {p.get('price', '未設定')}円```"
                product_description = p.get('description', '').strip()
                if product_description:
                    value = f"{product_description}{price_text}"
                else:
                    value = price_text
                embed.add_field(
                    name=f"{p['name']}", 
                    value=value, 
                    inline=False
                )
        else:
            if not is_custom:  # デフォルトパネルの場合のみ上書き
                embed.description = "```現在、販売中の商品はありません。```"

        view = VendingMachineCog.VendingMachineView(vending_machine_id, self.bot)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="在庫引出", description="商品の在庫を引き出します")
    @is_allowed()
    @app_commands.autocomplete(vending_machine_id=vending_machine_autocomplete)
    @app_commands.describe(vending_machine_id="自販機", quantity="数量")
    async def vm_withdraw_stock(self, interaction: discord.Interaction, vending_machine_id: str, quantity: int):
        if quantity <= 0:
            return await interaction.response.send_message("引出数量は1以上で指定してください。", ephemeral=True)

        vending_data = load_json(VENDING_DATA_FILE)
        vm = vending_data.get(vending_machine_id)
        if not vm or vm.get("owner_id") != str(interaction.user.id):
            return await interaction.response.send_message("指定された自販機が見つかりません。", ephemeral=True)

        products = vm.get("products")
        if not products:
            return await interaction.response.send_message("引出できる商品がありません。", ephemeral=True)
        
        view = VendingMachineCog.WithdrawStockView(products, quantity)
        await interaction.response.send_message("在庫引出を行う商品を選択してください:", view=view, ephemeral=True)

    @app_commands.command(name="在庫内容確認", description="商品の在庫内容を確認します")
    @is_allowed()
    @app_commands.autocomplete(vending_machine_id=vending_machine_autocomplete)
    @app_commands.describe(vending_machine_id="自販機")
    async def vm_check_stock_content(self, interaction: discord.Interaction, vending_machine_id: str):
        vending_data = load_json(VENDING_DATA_FILE)
        vm = vending_data.get(vending_machine_id)
        if not vm or vm.get("owner_id") != str(interaction.user.id):
            return await interaction.response.send_message("指定された自販機が見つかりません。", ephemeral=True)

        products = vm.get("products")
        if not products:
            return await interaction.response.send_message("内容を確認できる商品がありません。", ephemeral=True)
        
        view = VendingMachineCog.ContentView(products)
        await interaction.response.send_message("在庫内容確認を行う商品を選択してください:", view=view, ephemeral=True)

    @app_commands.command(name="商品削除", description="自販機から商品を完全に削除します")
    @is_allowed()
    @app_commands.autocomplete(vending_machine_id=vending_machine_autocomplete)
    @app_commands.describe(vending_machine_id="自販機")
    async def vm_delete_product(self, interaction: discord.Interaction, vending_machine_id: str):
        vending_data = load_json(VENDING_DATA_FILE)
        vm = vending_data.get(vending_machine_id)
        if not vm or vm.get("owner_id") != str(interaction.user.id):
            return await interaction.response.send_message("指定された自販機が見つかりません。", ephemeral=True)

        products = vm.get("products")
        if not products:
            return await interaction.response.send_message("削除できる商品がありません。", ephemeral=True)
        
        view = ui.View(timeout=None)
        view.add_item(VendingMachineCog.ProductSelectForDelete(products))
        
        await interaction.response.send_message("削除する商品を選択してください:", view=view, ephemeral=True)

    @app_commands.command(name="商品情報変更", description="商品の各情報を変更します")
    @is_allowed()
    @app_commands.autocomplete(vending_machine_id=vending_machine_autocomplete)
    @app_commands.describe(vending_machine_id="自販機")
    async def vm_edit_product(self, interaction: discord.Interaction, vending_machine_id: str):
        vending_data = load_json(VENDING_DATA_FILE)
        vm = vending_data.get(vending_machine_id)
        if not vm or vm.get("owner_id") != str(interaction.user.id):
            return await interaction.response.send_message("指定された自販機が見つかりません。", ephemeral=True)

        products = vm.get("products")
        if not products:
            return await interaction.response.send_message("情報を変更できる商品がありません。", ephemeral=True)
        
        view = VendingMachineCog.EditProductView(products, vending_machine_id)
        await interaction.response.send_message("情報を変更する商品を選択してください:", view=view, ephemeral=True)

    @app_commands.command(name="自販機削除", description="自販機を完全に削除します")
    @is_allowed()
    @app_commands.autocomplete(vending_machine_id=vending_machine_autocomplete)
    @app_commands.describe(vending_machine_id="削除する自販機")
    async def vm_delete(self, interaction: discord.Interaction, vending_machine_id: str):
        try:
            vending_data = load_json(VENDING_DATA_FILE)
            vm = vending_data.get(vending_machine_id)

            if not vm or vm.get("owner_id") != str(interaction.user.id):
                return await interaction.response.send_message("指定された自販機が見つかりません。", ephemeral=True)
            
            vm_name = vm.get("name", "名称不明")
            
            # 確認ボタンを表示
            view = VendingMachineCog.VendingMachineDeleteConfirmView(vending_machine_id, vm_name)
            
            embed = discord.Embed(
                title="自販機削除確認",
                description=f"本当に自販機「{vm_name}」を削除しますか？\n\n**この操作は取り消せません。**\n**すべての商品と在庫データも削除されます。**",
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_footer(text="Developer @roru2026.")
            
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="自販機パネル更新", description="自販機パネルを更新します")
    @is_allowed()
    @app_commands.autocomplete(vending_machine_id=vending_machine_autocomplete)
    @app_commands.describe(
        vending_machine_id="更新する自販機", 
        message_link="更新するメッセージのリンク",
        panel_title="パネルのタイトル",
        panel_description="パネルの説明文",
        panel_image="パネルの画像"
    )
    async def vm_update(self, interaction: discord.Interaction, vending_machine_id: str, message_link: str, panel_title: str = None, panel_description: str = None, panel_image: discord.Attachment = None):
        await interaction.response.defer(ephemeral=True)
        
        try:
            # 権限チェック
            vending_data = load_json(VENDING_DATA_FILE)
            vm = vending_data.get(vending_machine_id)
            if not vm or vm.get("owner_id") != str(interaction.user.id):
                embed = discord.Embed(
                    title="ERROR",
                    description="指定された自販機が見つかりません。",
                    color=discord.Color.red()
                )
                embed.set_footer(text="Developer @roru2026.")
                return await interaction.followup.send(embed=embed, ephemeral=True)
            
            # メッセージリンクを解析
            try:
                # Discord メッセージリンクの形式: https://discord.com/channels/guild_id/channel_id/message_id
                # または https://discordapp.com/channels/guild_id/channel_id/message_id
                link_parts = message_link.replace("https://discord.com/channels/", "").replace("https://discordapp.com/channels/", "")
                guild_id, channel_id, message_id = link_parts.split("/")
                
                # チャンネルとメッセージを取得
                channel = self.bot.get_channel(int(channel_id))
                if not channel:
                    embed = discord.Embed(
                        title="ERROR",
                        description="指定されたチャンネルが見つかりません。",
                        color=discord.Color.red()
                    )
                    embed.set_footer(text="Developer @roru2026.")
                    return await interaction.followup.send(embed=embed, ephemeral=True)
                
                message = await channel.fetch_message(int(message_id))
                if not message:
                    embed = discord.Embed(
                        title="ERROR",
                        description="指定されたメッセージが見つかりません。",
                        color=discord.Color.red()
                    )
                    embed.set_footer(text="Developer @roru2026.")
                    return await interaction.followup.send(embed=embed, ephemeral=True)
                
                # メッセージの送信者がボットかチェック
                if message.author.id != self.bot.user.id:
                    embed = discord.Embed(
                        title="ERROR",
                        description="指定されたメッセージはBOTが送信したものではありません。",
                        color=discord.Color.red()
                    )
                    embed.set_footer(text="Developer @roru2026.")
                    return await interaction.followup.send(embed=embed, ephemeral=True)
                
            except (ValueError, IndexError):
                embed = discord.Embed(
                    title="ERROR",
                    description="メッセージリンクの形式が正しくありません。",
                    color=discord.Color.red()
                )
                embed.set_footer(text="Developer @roru2026.")
                return await interaction.followup.send(embed=embed, ephemeral=True)
            
            # 新しい自販機パネルを作成
            # カスタムパネルかデフォルトパネルかを判定
            is_custom = any([panel_title, panel_description, panel_image])
            
            if is_custom:
                # カスタムパネル
                title = panel_title if panel_title else "自販機"
                description = panel_description if panel_description else "購入したい商品を下のメニューから選択してください。"
                embed = discord.Embed(title=title, description=description, color=discord.Color.green())
                
                if panel_image:
                    embed.set_image(url=panel_image.url)
            else:
                # デフォルトパネル
                embed = discord.Embed(
                    title="自販機", 
                    description="購入したい商品を下のメニューから選択してください。", 
                    color=discord.Color.green()
                )
            
            embed.set_footer(text="Developer @roru2026.")
            
            # 商品フィールドを統一して追加
            products = vm.get("products", [])
            if products:
                for p in products:
                    price_text = f"```価格: {p.get('price', '未設定')}円```"
                    product_description = p.get('description', '').strip()
                    if product_description:
                        value = f"{product_description}{price_text}"
                    else:
                        value = price_text
                    embed.add_field(
                        name=f"{p['name']}", 
                        value=value, 
                        inline=False
                    )
            else:
                if not is_custom:  # デフォルトパネルの場合のみ上書き
                    embed.description = "```現在、販売中の商品はありません。```"
            
            # 新しいViewを作成
            view = VendingMachineCog.VendingMachineView(vending_machine_id, self.bot)
            
            # メッセージを更新
            await message.edit(embed=embed, view=view)
            
            embed_success = discord.Embed(
                title="更新完了",
                description=f"自販機「{vm['name']}」のパネルを更新しました。",
                color=discord.Color.green()
            )
            embed_success.set_footer(text="Developer @roru2026.")
            await interaction.followup.send(embed=embed_success, ephemeral=True)
            
        except Exception as e:
            await handle_error(interaction, e)

    # 新しい購入フロー用のモーダル
    class VendingMachineDeleteConfirmView(ui.View):
        def __init__(self, vending_machine_id: str, vm_name: str):
            super().__init__(timeout=300)
            self.vending_machine_id = vending_machine_id
            self.vm_name = vm_name

        @ui.button(label="削除する", style=discord.ButtonStyle.danger)
        async def confirm_delete(self, interaction, button):
            await interaction.response.defer(ephemeral=True)
            try:
                vending_data = load_json(VENDING_DATA_FILE)
                vm = vending_data.get(self.vending_machine_id)

                if not vm or vm.get("owner_id") != str(interaction.user.id):
                    return await interaction.followup.send("指定された自販機が見つかりません。", ephemeral=True)
                
                # 在庫ファイルを削除
                for product in vm.get("products", []):
                    stock_file_path = product.get("stock_file")
                    if stock_file_path and os.path.exists(stock_file_path):
                        try:
                            os.remove(stock_file_path)
                        except Exception:
                            pass

                # 自販機データを削除
                del vending_data[self.vending_machine_id]
                save_json(VENDING_DATA_FILE, vending_data)

                embed = discord.Embed(
                    title="削除完了",
                    description=f"自販機「{self.vm_name}」を削除しました。",
                    color=discord.Color.green(),
                    timestamp=discord.utils.utcnow()
                )
                embed.set_footer(text="Developer @roru2026.")
                
                await interaction.followup.send(embed=embed, ephemeral=True)
            except Exception as e:
                await handle_error(interaction, e)

        @ui.button(label="キャンセル", style=discord.ButtonStyle.secondary)
        async def cancel_delete(self, interaction, button):
            embed = discord.Embed(
                title="キャンセル",
                description="自販機削除をキャンセルしました。",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_footer(text="Developer @roru2026.")
            await interaction.response.send_message(embed=embed, ephemeral=True)

    class CouponModal(ui.Modal, title="購入情報入力"):
        def __init__(self, vending_machine_id: str, product: dict, bot: commands.Bot):
            super().__init__()
            self.vending_machine_id = vending_machine_id
            self.product = product
            self.bot = bot
            
            # 無限在庫の場合は購入数入力を表示しない
            if not product.get('infinite_stock'):
                self.quantity_input = ui.TextInput(
                    label="購入数", 
                    placeholder="1", 
                    required=True, 
                    max_length=5
                )
                self.add_item(self.quantity_input)
            else:
                self.quantity_input = None
            
            self.coupon_input = ui.TextInput(
                label="クーポンコード", 
                placeholder="あればクーポンコードを入力", 
                required=False, 
                max_length=50
            )
            self.add_item(self.coupon_input)

        async def on_submit(self, interaction):
            try:
                # 無限在庫の場合は購入数を1に固定
                if self.product.get('infinite_stock'):
                    quantity = 1
                else:
                    quantity = int(self.quantity_input.value)
                    if quantity <= 0: 
                        return await interaction.response.send_message("購入数は1以上で入力してください。", ephemeral=True)
                    
            except ValueError:
                return await interaction.response.send_message("購入数には整数を入力してください。", ephemeral=True)

            coupon_code = self.coupon_input.value.strip() if self.coupon_input.value else None
            
            # クーポンの検証と割引計算
            discount = 0
            if coupon_code:
                coupon_data = load_coupon_data()
                if coupon_code in coupon_data:
                    coupon_info = coupon_data[coupon_code]
                    # 自販機指定のクーポンかチェック
                    if coupon_info.get("vending_machine_id") == self.vending_machine_id:
                        discount = coupon_info.get("discount", 0)
                    else:
                        return await interaction.response.send_message("このクーポンコードはこの自販機では使用できません。", ephemeral=True)
                else:
                    return await interaction.response.send_message("無効なクーポンコードです。", ephemeral=True)
            
            product_price = self.product.get('price', 0)
            # (値段 - 割引) × 個数 の計算
            base_price = product_price * quantity
            total_discount = discount * quantity
            final_price = max(0, base_price - total_discount)
            
            # 購入確認パネルを表示
            embed = discord.Embed(
                title="購入確認",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="商品名", value=f"```{self.product['name']}```", inline=False)
            
            # 無限在庫の場合は個数表示を変更
            if self.product.get('infinite_stock'):
                embed.add_field(name="個数", value=f"```1個```", inline=False)
            else:
                embed.add_field(name="個数", value=f"```{quantity}個```", inline=False)
            
            if discount > 0:
                embed.add_field(name="金額", value=f"```{product_price}円 × {quantity}個 - {discount}円 × {quantity}個 = {final_price}円```", inline=False)
            else:
                embed.add_field(name="金額", value=f"```{final_price}円```", inline=False)
            
            embed.set_footer(text="Developer @roru2026.")
            
            view = VendingMachineCog.PurchaseConfirmView(
                self.vending_machine_id, 
                self.product, 
                quantity, 
                final_price, 
                self.bot
            )
            
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    class PurchaseConfirmView(ui.View):
        def __init__(self, vending_machine_id: str, product: dict, quantity: int, final_price: int, bot: commands.Bot):
            super().__init__(timeout=300)
            self.vending_machine_id = vending_machine_id
            self.product = product
            self.quantity = quantity
            self.final_price = final_price
            self.bot = bot

        @ui.button(label="購入確定", style=discord.ButtonStyle.green)
        async def confirm_purchase(self, interaction, button):
            if self.final_price == 0:
                # 0円商品の場合は直接購入処理
                await self.process_purchase(interaction, None)
            else:
                # 有料商品の場合はPayPayリンク入力モーダルを表示
                modal = VendingMachineCog.PayPayModal(
                    self.vending_machine_id, 
                    self.product, 
                    self.quantity, 
                    self.final_price, 
                    self.bot
                )
                await interaction.response.send_modal(modal)

        async def process_purchase(self, interaction, pay_link):
            await interaction.response.defer(ephemeral=True)
            
            try:
                # 自販機の存在確認
                vending_data = load_json(VENDING_DATA_FILE)
                vm = vending_data.get(self.vending_machine_id)
                if not vm:
                    embed = discord.Embed(
                        title="エラー",
                        description="この自販機は削除されているか、存在しません。",
                        color=discord.Color.red()
                    )
                    embed.set_footer(text="Developer @roru2026.")
                    return await interaction.followup.send(embed=embed, ephemeral=True)
                
                # 有料商品の場合はPayPay決済処理
                if self.final_price > 0:
                    payment_info = await paypayu.check_link(pay_link)
                    if not payment_info:
                        return await interaction.followup.send("有効なPayPayリンクを入力してください。", ephemeral=True)

                    total_payment_amount = payment_info.get("payload", {}).get("message", {}).get("data", {}).get("amount")
                    if total_payment_amount < self.final_price:
                        return await interaction.followup.send(f"金額が不足しています。\n必要な金額: {self.final_price}円\nあなたの支払額: {total_payment_amount}円", ephemeral=True)
                    
                    paypay_data = load_paypay_data()
                    owner_credentials = paypay_data.get(vm["paypay_id"])

                    if not owner_credentials:
                        return await interaction.followup.send("販売者のPayPayアカウントが設定されていません。\n販売者にお問い合わせください。", ephemeral=True)

                    result = await paypayu.link_rev(
                        pay_link,
                        owner_credentials["phone"],
                        owner_credentials["password"],
                        owner_credentials["uuid"]
                    )
                    
                    # ログアウトされている場合は自動再ログイン
                    if result == False:
                        try:
                            login_result = await paypayu.login(
                                owner_credentials["phone"],
                                owner_credentials["password"],
                                owner_credentials["uuid"]
                            )
                            
                            if login_result:
                                result = await paypayu.link_rev(
                                    pay_link,
                                    owner_credentials["phone"],
                                    owner_credentials["password"],
                                    owner_credentials["uuid"]
                                )
                        except Exception as e:
                            print(f"自動再ログインエラー: {e}")
                    
                    if result != True:
                        return await interaction.followup.send("PayPay決済の処理に失敗しました。リンクが正しいか確認してください。", ephemeral=True)

                # 在庫処理
                if self.product.get("infinite_stock"):
                    purchased_content = f"```\n{self.product.get('infinite_content', '')}\n```"
                    purchased_content_text = self.product.get('infinite_content', '')
                else:
                    with open(self.product["stock_file"], "r+", encoding="utf-8") as file:
                        # ① 各行末尾の改行を除去してから処理（\n.join時に空行が倍増するバグを修正）
                        lines = [line.rstrip("\n") for line in file.readlines() if line.strip()]
                        
                        if len(lines) < self.quantity:
                            return await interaction.followup.send(f"在庫が不足しています。\n必要数: {self.quantity}個\n現在の在庫: {len(lines)}個", ephemeral=True)
                        
                        purchased_items = lines[:self.quantity]
                        remaining_items = lines[self.quantity:]
                        
                        file.seek(0)
                        file.truncate()
                        file.write("\n".join(remaining_items))
                    
                    purchased_content = f"```\n{chr(10).join(purchased_items)}\n```"
                    purchased_content_text = "\n".join(purchased_items)
                
                # 価格表示を調整
                price_display = "0円" if self.final_price == 0 else f"{self.final_price}円"
                
                embed = discord.Embed(
                    title="購入完了",
                    description=f"**商品:** `{self.product['name']}`\n**数量:** `{self.quantity}`個\n**合計金額:** `{price_display}`",
                    color=discord.Color.green(),
                    timestamp=discord.utils.utcnow()
                )
                embed.add_field(name="購入した商品", value=purchased_content, inline=False)
                embed.set_footer(text="Developer @roru2026.")
                
                await interaction.followup.send(embed=embed, ephemeral=True)
                
                # ② 販売数更新：在庫消費と同じ vending_data を再ロードして1回で保存（競合防止）
                vending_data = load_json(VENDING_DATA_FILE)
                for vm_id, vm_data in vending_data.items():
                    for i, p in enumerate(vm_data.get("products", [])):
                        if p["product_id"] == self.product["product_id"]:
                            vm_data["products"][i]["sales_count"] = p.get("sales_count", 0) + self.quantity
                            break
                    else:
                        continue
                    break
                save_json(VENDING_DATA_FILE, vending_data)
                
                # ロール付与処理
                try:
                    role_data = load_role_assignment_data()
                    role_info = role_data.get(self.vending_machine_id)
                    if role_info and role_info.get("guild_id") == interaction.guild.id:
                        role = interaction.guild.get_role(role_info.get("role_id"))
                        if role and role not in interaction.user.roles:
                            await interaction.user.add_roles(role)
                except:
                    pass  # ロール付与エラーは無視
                
                # DMで購入内容を送信
                try:
                    import datetime
                    import pytz
                    
                    jst = pytz.timezone('Asia/Tokyo')
                    now_jst = datetime.datetime.now(jst)
                    formatted_time = now_jst.strftime("%Y/%m/%d %H:%M:%S(JST)")
                    
                    dm_embed = discord.Embed(
                        title="購入が完了しました",
                        color=discord.Color.green(),
                        timestamp=discord.utils.utcnow()
                    )
                    dm_embed.add_field(name="購入日", value=f"```{formatted_time}```", inline=True)
                    dm_embed.add_field(name="購入サーバー", value=f"```{interaction.guild.name}({interaction.guild.id})```", inline=True)
                    dm_embed.add_field(name="商品名", value=f"```{self.product['name']}```", inline=True)
                    dm_embed.add_field(name="購入数", value=f"```{self.quantity}個```", inline=True)
                    dm_embed.add_field(name="支払金額", value=f"```{price_display}```", inline=True)
                    dm_embed.set_footer(text="Developer @roru2026.")
                    
                    await interaction.user.send(purchased_content_text, embed=dm_embed)
                except:
                    pass
                
                # 公開ログ送信
                if vm.get("log_channel_id"):
                    log_channel = self.bot.get_channel(vm["log_channel_id"])
                    if log_channel:
                        colors = [
                            discord.Color.red(),
                            discord.Color.blue(),
                            discord.Color.green(),
                            discord.Color.yellow(),
                            discord.Color.purple(),
                            discord.Color.orange(),
                            discord.Color.pink(),
                            discord.Color.teal(),
                            discord.Color.magenta(),
                            discord.Color.gold(),
                            discord.Color.blurple(),
                            discord.Color.greyple(),
                            discord.Color.from_rgb(255, 105, 180),
                            discord.Color.from_rgb(57, 255, 20),
                            discord.Color.from_rgb(0, 255, 255),
                            discord.Color.from_rgb(255, 255, 0),
                            discord.Color.from_rgb(255, 0, 255),
                            discord.Color.from_rgb(0, 255, 128),
                            discord.Color.from_rgb(255, 80, 0),
                            discord.Color.from_rgb(0, 191, 255),
                            discord.Color.from_rgb(173, 255, 47)
                        ]
                        random_color = random.choice(colors)
                        
                        log_embed = discord.Embed(color=random_color)
                        log_embed.add_field(name="商品名", value=f"```{self.product['name']}```", inline=True)
                        log_embed.add_field(name="購入数", value=f"```{self.quantity}個```", inline=True)
                        log_embed.add_field(name="購入サーバー", value=f"```{interaction.guild.name}({interaction.guild.id})```", inline=True)
                        log_embed.add_field(name="購入者", value=f"{interaction.user.mention}({interaction.user.id})", inline=True)
                        log_embed.set_footer(text="Developer @roru2026.")
                        await log_channel.send(embed=log_embed)
                
                # 非公開ログ送信
                if vm.get("private_log_channel_id"):
                    private_log_channel = self.bot.get_channel(vm["private_log_channel_id"])
                    if private_log_channel:
                        private_log_embed = discord.Embed(color=discord.Color.orange())
                        private_log_embed.add_field(name="商品名", value=f"```{self.product['name']}```", inline=True)
                        private_log_embed.add_field(name="購入数", value=f"```{self.quantity}個```", inline=True)
                        private_log_embed.add_field(name="購入サーバー", value=f"```{interaction.guild.name}({interaction.guild.id})```", inline=True)
                        private_log_embed.add_field(name="購入者", value=f"{interaction.user.mention}({interaction.user.id})", inline=True)
                        private_log_embed.add_field(name="支払金額", value=f"```{price_display}```", inline=True)
                        private_log_embed.add_field(name="自販機", value=f"```{vm['name']}({self.vending_machine_id})```", inline=True)
                        private_log_embed.set_footer(text="Developer @roru2026.")
                        
                        discord_file = discord.File(
                            io.BytesIO(purchased_content_text.encode('utf-8')),
                            filename=f"purchase_{interaction.user.id}_{int(discord.utils.utcnow().timestamp())}.txt"
                        )
                        
                        await private_log_channel.send(embed=private_log_embed, file=discord_file)
                
            except Exception as e:
                await handle_error(interaction, e)

    class PayPayModal(ui.Modal, title="PayPay決済"):
        def __init__(self, vending_machine_id: str, product: dict, quantity: int, final_price: int, bot: commands.Bot):
            super().__init__()
            self.vending_machine_id = vending_machine_id
            self.product = product
            self.quantity = quantity
            self.final_price = final_price
            self.bot = bot
            
            self.paypay_input = ui.TextInput(
                label="PayPayリンク", 
                placeholder="https://pay.paypay.ne.jp/...", 
                required=True
            )
            self.add_item(self.paypay_input)

        async def on_submit(self, interaction):
            # PurchaseConfirmViewのprocess_purchaseメソッドを呼び出し
            confirm_view = VendingMachineCog.PurchaseConfirmView(
                self.vending_machine_id, 
                self.product, 
                self.quantity, 
                self.final_price, 
                self.bot
            )
            await confirm_view.process_purchase(interaction, self.paypay_input.value)

    class ProductSelect(ui.Select):
        def __init__(self, vending_machine_id: str, bot: commands.Bot):
            self.vending_machine_id = vending_machine_id
            self.bot = bot
            
            # 最新の商品データを取得
            vending_data = load_json(VENDING_DATA_FILE)
            vm = vending_data.get(vending_machine_id, {})
            products = vm.get("products", [])
            
            options = []
            if products:
                for product in products:
                    emoji = product.get("emoji")
                    label = f"{product['name']}"
                    
                    # 在庫数と販売数を取得
                    sales_count = product.get("sales_count", 0)
                    if product.get("infinite_stock"):
                        description = f"価格: {product['price']}円│在庫数: ∞個│販売数: {sales_count}個"
                    else:
                        try:
                            with open(product.get("stock_file", ""), "r", encoding="utf-8") as f:
                                lines = [line for line in f.readlines() if line.strip()]
                                stock_count = len(lines)
                        except:
                            stock_count = 0
                        
                        description = f"価格: {product['price']}円│在庫数: {stock_count}個│販売数: {sales_count}個"
                    
                    options.append(discord.SelectOption(
                        label=label,
                        value=product["product_id"],
                        description=description,
                        emoji=emoji
                    ))
            
            if not options:
                options.append(discord.SelectOption(label="商品なし", value="none", description="現在販売中の商品はありません"))
            
            super().__init__(
                placeholder="商品を選択する",
                options=options,
                custom_id=f"product_select_{vending_machine_id}"
            )

        async def callback(self, interaction):
            if self.values[0] == "none":
                return await interaction.response.send_message("現在販売中の商品はありません。", ephemeral=True)
            
            try:
                # 自販機の存在確認
                vending_data = load_json(VENDING_DATA_FILE)
                vm = vending_data.get(self.vending_machine_id, {})
                if not vm:
                    embed = discord.Embed(
                        title="エラー",
                        description="この自販機は削除されているか、存在しません。",
                        color=discord.Color.red()
                    )
                    embed.set_footer(text="Developer @roru2026.")
                    return await interaction.response.send_message(embed=embed, ephemeral=True)
                
                products = vm.get("products", [])
                product = next((p for p in products if p["product_id"] == self.values[0]), None)
                if not product: 
                    return await interaction.response.send_message("商品が見つかりません。", ephemeral=True)
                
                # 在庫チェック
                if product.get("infinite_stock"):
                    # 無限在庫の場合は常に購入可能
                    modal = VendingMachineCog.CouponModal(self.vending_machine_id, product, self.bot)
                    await interaction.response.send_modal(modal)
                else:
                    # 有限在庫の場合
                    try:
                        with open(product.get("stock_file", ""), "r", encoding="utf-8") as f:
                            lines = [line for line in f.readlines() if line.strip()]
                            if len(lines) == 0:
                                embed = discord.Embed(
                                    title="在庫不足",
                                    description=f"現在 {product['name']}の在庫が不足しています。",
                                    color=discord.Color.orange()
                                )
                                embed.set_footer(text="Developer @roru2026.")
                                return await interaction.response.send_message(embed=embed, ephemeral=True)
                    except:
                        embed = discord.Embed(
                            title="在庫不足",
                            description=f"現在 {product['name']}の在庫が不足しています。",
                            color=discord.Color.orange()
                        )
                        embed.set_footer(text="Developer @roru2026.")
                        return await interaction.response.send_message(embed=embed, ephemeral=True)
                    
                    modal = VendingMachineCog.CouponModal(self.vending_machine_id, product, self.bot)
                    await interaction.response.send_modal(modal)
                
            except Exception as e:
                await handle_error(interaction, e)

    class PurchaseButton(ui.Button):
        def __init__(self, vending_machine_id: str, bot: commands.Bot):
            super().__init__(
                label="購入する",
                style=discord.ButtonStyle.green,
                emoji="🛒",
                custom_id=f"purchase_{vending_machine_id}"
            )
            self.vending_machine_id = vending_machine_id
            self.bot = bot

        async def callback(self, interaction):
            try:
                embed = discord.Embed(
                    title="購入する商品を選択してください。",
                    color=discord.Color.green()
                )
                view = VendingMachineCog.ProductSelectView(self.vending_machine_id, self.bot)
                await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            except Exception as e:
                await handle_error(interaction, e)

    class ProductSelectView(ui.View):
        def __init__(self, vending_machine_id: str, bot: commands.Bot):
            super().__init__(timeout=None)
            self.vending_machine_id = vending_machine_id
            self.add_item(VendingMachineCog.ProductSelect(vending_machine_id, bot))

    class StockCheckButton(ui.Button):
        def __init__(self, vending_machine_id: str):
            super().__init__(
                label="在庫・販売数確認",
                style=discord.ButtonStyle.primary,
                emoji="📦",
                custom_id=f"check_stock_{vending_machine_id}"
            )
            self.vending_machine_id = vending_machine_id

        async def callback(self, interaction):
            try:
                # 自販機の存在確認
                vending_data = load_json(VENDING_DATA_FILE)
                vm = vending_data.get(self.vending_machine_id, {})
                if not vm:
                    embed = discord.Embed(
                        title="エラー",
                        description="この自販機は削除されているか、存在しません。",
                        color=discord.Color.red()
                    )
                    embed.set_footer(text="Developer @roru2026.")
                    return await interaction.response.send_message(embed=embed, ephemeral=True)
                
                # 最新の商品データを動的に取得
                products = vm.get("products", [])
                await interaction.response.defer(ephemeral=True)
                await check_stock(interaction, products)
            except Exception as e:
                await handle_error(interaction, e)

    class VendingMachineView(ui.View):
        def __init__(self, vending_machine_id: str, bot: commands.Bot):
            super().__init__(timeout=None)
            self.vending_machine_id = vending_machine_id
            self.add_item(VendingMachineCog.PurchaseButton(vending_machine_id, bot))
            self.add_item(VendingMachineCog.StockCheckButton(vending_machine_id))

    class ProductSelectViewForStock(ui.View):
        def __init__(self, products: list, attachment: discord.Attachment = None, stock_type: str = "finite"):
            super().__init__(timeout=None)
            self.add_item(VendingMachineCog.ProductSelectForStock(products, attachment, stock_type))
            
    class ProductSelectForStock(ui.Select):
        def __init__(self, products: list, attachment: discord.Attachment = None, stock_type: str = "finite"):
            self.products = products
            self.attachment = attachment
            self.stock_type = stock_type
            options = [discord.SelectOption(label=p["name"], value=p["product_id"]) for p in products]
            super().__init__(
                placeholder="在庫を追加する商品を選択...", 
                options=options,
                custom_id="stock_add_select"
            )

        async def callback(self, interaction):
            try:
                product = next((p for p in self.products if p["product_id"] == self.values[0]), None)
                if not product:
                    await interaction.response.send_message("商品が見つかりません。", ephemeral=True)
                    return

                if self.stock_type == "infinite":
                    # 無限在庫の場合
                    if self.attachment:
                        await interaction.response.defer(ephemeral=True)
                        try:
                            new_stock_content = await self.attachment.read()
                            infinite_content = new_stock_content.decode('utf-8').strip()
                            
                            # 商品データを更新
                            vending_data = load_json(VENDING_DATA_FILE)
                            for vm_id, vm_data in vending_data.items():
                                for i, p in enumerate(vm_data.get("products", [])):
                                    if p["product_id"] == product["product_id"]:
                                        vm_data["products"][i]["infinite_stock"] = True
                                        vm_data["products"][i]["infinite_content"] = infinite_content
                                        break
                            save_json(VENDING_DATA_FILE, vending_data)
                            
                            await interaction.followup.send(f"商品「{product['name']}」を無限在庫に設定しました。", ephemeral=True)
                        except Exception as e:
                            await handle_error(interaction, e)
                    else:
                        modal = VendingMachineCog.InfiniteStockModal(product)
                        await interaction.response.send_modal(modal)
                else:
                    # 有限在庫の場合（従来通り）
                    if self.attachment:
                        await interaction.response.defer(ephemeral=True)
                        try:
                            new_stock_content = await self.attachment.read()
                            new_stock_lines = [line for line in new_stock_content.decode('utf-8').splitlines() if line.strip()]
                            with open(product["stock_file"], "a", encoding="utf-8") as f:
                                if os.path.getsize(product["stock_file"]) > 0: f.write("\n")
                                f.write("\n".join(new_stock_lines))
                            
                            await interaction.followup.send(f"商品「{product['name']}」に`{len(new_stock_lines)}`個の在庫を追加しました。", ephemeral=True)
                            
                            # 在庫追加通知を送信
                            await self.send_stock_notification(interaction, product, len(new_stock_lines))
                            
                        except Exception as e:
                            await handle_error(interaction, e)
                    else:
                        modal = VendingMachineCog.StockAddModal(product)
                        await interaction.response.send_modal(modal)
            except Exception as e:
                await handle_error(interaction, e)
        
        async def send_stock_notification(self, interaction, product, added_count):
            try:
                # 自販機IDを取得
                vending_data = load_json(VENDING_DATA_FILE)
                vending_machine_id = None
                for vm_id, vm_data in vending_data.items():
                    for p in vm_data.get("products", []):
                        if p["product_id"] == product["product_id"]:
                            vending_machine_id = vm_id
                            break
                    if vending_machine_id:
                        break
                
                if not vending_machine_id:
                    return
                
                # 通知設定を確認
                notification_data = load_stock_notification_data()
                notification_info = notification_data.get(vending_machine_id)
                
                if notification_info and notification_info.get("guild_id") == interaction.guild.id:
                    channel = interaction.guild.get_channel(notification_info.get("channel_id"))
                    role = interaction.guild.get_role(notification_info.get("role_id"))
                    
                    if channel and role:
                        embed = discord.Embed(
                            title="在庫追加通知",
                            color=discord.Color.green(),
                            timestamp=discord.utils.utcnow()
                        )
                        embed.add_field(name="追加商品", value=f"```{product['name']}```", inline=True)
                        embed.add_field(name="追加数", value=f"```{added_count}個```", inline=True)
                        embed.set_footer(text="Developer @roru2026.")
                        
                        await channel.send(f"{role.mention}", embed=embed)
                        
            except Exception as e:
                print(f"在庫追加通知送信エラー: {e}")

    class StockAddModal(ui.Modal, title="在庫追加"):
        def __init__(self, product: dict):
            super().__init__(timeout=None)
            self.product = product

        stock_input = ui.TextInput(
            label="在庫内容",
            style=discord.TextStyle.long,
            placeholder="追加する在庫を1行ずつ入力してください",
            required=True
        )

        async def on_submit(self, interaction):
            await interaction.response.defer(ephemeral=True)
            try:
                new_stock_lines = [line for line in self.stock_input.value.splitlines() if line.strip()]
                
                with open(self.product["stock_file"], "a", encoding="utf-8") as f:
                    if os.path.getsize(self.product["stock_file"]) > 0: 
                        f.write("\n")
                    f.write("\n".join(new_stock_lines))
                
                await interaction.followup.send(f"商品「{self.product['name']}」に`{len(new_stock_lines)}`個の在庫を追加しました。", ephemeral=True)
                
                # 在庫追加通知を送信
                await self.send_stock_notification(interaction, self.product, len(new_stock_lines))
                
            except Exception as e:
                await handle_error(interaction, e)
        
        async def send_stock_notification(self, interaction, product, added_count):
            try:
                # 自販機IDを取得
                vending_data = load_json(VENDING_DATA_FILE)
                vending_machine_id = None
                for vm_id, vm_data in vending_data.items():
                    for p in vm_data.get("products", []):
                        if p["product_id"] == product["product_id"]:
                            vending_machine_id = vm_id
                            break
                    if vending_machine_id:
                        break
                
                if not vending_machine_id:
                    return
                
                # 通知設定を確認
                notification_data = load_stock_notification_data()
                notification_info = notification_data.get(vending_machine_id)
                
                if notification_info and notification_info.get("guild_id") == interaction.guild.id:
                    channel = interaction.guild.get_channel(notification_info.get("channel_id"))
                    role = interaction.guild.get_role(notification_info.get("role_id"))
                    
                    if channel and role:
                        embed = discord.Embed(
                            title="在庫追加通知",
                            color=discord.Color.blue(),
                            timestamp=discord.utils.utcnow()
                        )
                        embed.add_field(name="追加商品", value=f"```{product['name']}```", inline=True)
                        embed.add_field(name="追加数", value=f"```{added_count}個```", inline=True)
                        embed.set_footer(text="Developer @roru2026.")
                        
                        await channel.send(f"{role.mention}", embed=embed)
                        
            except Exception as e:
                print(f"在庫追加通知送信エラー: {e}")

    class InfiniteStockModal(ui.Modal, title="無限在庫設定"):
        def __init__(self, product: dict):
            super().__init__(timeout=None)
            self.product = product

        stock_input = ui.TextInput(
            label="無限在庫内容",
            style=discord.TextStyle.long,
            placeholder="購入時に送信される内容を入力してください",
            required=True
        )

        async def on_submit(self, interaction):
            await interaction.response.defer(ephemeral=True)
            try:
                infinite_content = self.stock_input.value.strip()
                
                # 商品データを更新
                vending_data = load_json(VENDING_DATA_FILE)
                for vm_id, vm_data in vending_data.items():
                    for i, p in enumerate(vm_data.get("products", [])):
                        if p["product_id"] == self.product["product_id"]:
                            vm_data["products"][i]["infinite_stock"] = True
                            vm_data["products"][i]["infinite_content"] = infinite_content
                            break
                save_json(VENDING_DATA_FILE, vending_data)
                
                await interaction.followup.send(f"商品「{self.product['name']}」を無限在庫に設定しました。", ephemeral=True)
            except Exception as e:
                await handle_error(interaction, e)

    class WithdrawStockView(ui.View):
        def __init__(self, products: list, quantity: int):
            super().__init__(timeout=None)
            self.add_item(VendingMachineCog.ProductSelectForWithdraw(products, quantity))

    class ProductSelectForWithdraw(ui.Select):
        def __init__(self, products: list, quantity: int):
            self.products = products
            self.quantity = quantity
            options = [discord.SelectOption(label=p["name"], value=p["product_id"]) for p in products]
            super().__init__(
                placeholder="在庫を引き出す商品を選択...", 
                options=options,
                custom_id="withdraw_select"
            )

        async def callback(self, interaction):
            await interaction.response.defer(ephemeral=True)
            try:
                product = next((p for p in self.products if p["product_id"] == self.values[0]), None)
                if not product:
                    await interaction.followup.send("商品が見つかりません。", ephemeral=True)
                    return

                if product.get("infinite_stock"):
                    # 無限在庫の場合は無限在庫を解除
                    vending_data = load_json(VENDING_DATA_FILE)
                    for vm_id, vm_data in vending_data.items():
                        for i, p in enumerate(vm_data.get("products", [])):
                            if p["product_id"] == product["product_id"]:
                                withdrawn_content = f"`{p.get('infinite_content', '')}\n`"
                                vm_data["products"][i]["infinite_stock"] = False
                                vm_data["products"][i]["infinite_content"] = None
                                break
                    save_json(VENDING_DATA_FILE, vending_data)
                    
                    embed = discord.Embed(
                        title="無限在庫解除完了",
                        description=f"**商品:** `{product['name']}`\n**解除された無限在庫内容:**",
                        color=discord.Color.green(),
                        timestamp=discord.utils.utcnow()
                    )
                    embed.add_field(name="引き出した無限在庫", value=withdrawn_content, inline=False)
                    embed.set_footer(text="Developer @roru2026.")
                    
                    await interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    # 有限在庫の場合（従来通り）
                    try:
                        with open(product["stock_file"], "r+", encoding="utf-8") as file:
                            # ① 末尾改行を除去してから処理
                            lines = [line.rstrip("\n") for line in file.readlines() if line.strip()]
                            
                            if len(lines) < self.quantity:
                                await interaction.followup.send(f"在庫が不足しています。\n引出希望数: {self.quantity}個\n現在の在庫: {len(lines)}個", ephemeral=True)
                                return
                            
                            withdrawn_items = lines[:self.quantity]
                            remaining_items = lines[self.quantity:]
                            
                            file.seek(0)
                            file.truncate()
                            file.write("\n".join(remaining_items))
                        
                        withdrawn_content = f"`{chr(10).join(withdrawn_items)}\n`"
                        
                        embed = discord.Embed(
                            title="在庫引出完了",
                            description=f"**商品:** `{product['name']}`\n**引出数量:** `{self.quantity}`個",
                            color=discord.Color.green(),
                            timestamp=discord.utils.utcnow()
                        )
                        embed.add_field(name="引き出した在庫", value=withdrawn_content, inline=False)
                        embed.set_footer(text="Developer @roru2026.")
                        
                        await interaction.followup.send(embed=embed, ephemeral=True)

                    except FileNotFoundError:
                        await handle_error(interaction, FileNotFoundError("在庫ファイルが見つかりません。"))
                    except Exception as e:
                        await handle_error(interaction, e)
            except Exception as e:
                await handle_error(interaction, e)

    class ContentView(ui.View):
        def __init__(self, products: list):
            super().__init__(timeout=None)
            self.add_item(VendingMachineCog.ProductSelectForContent(products))

    class ProductSelectForContent(ui.Select):
        def __init__(self, products: list):
            self.products = products
            options = [discord.SelectOption(label=p["name"], value=p["product_id"]) for p in products]
            super().__init__(
                placeholder="在庫内容を確認する商品を選択...", 
                options=options,
                custom_id="content_select"
            )

        async def callback(self, interaction):
            await interaction.response.defer(ephemeral=True)
            try:
                product = next((p for p in self.products if p["product_id"] == self.values[0]), None)
                if not product:
                    await interaction.followup.send("商品が見つかりません。", ephemeral=True)
                    return

                if product.get("infinite_stock"):
                    # 無限在庫の場合
                    infinite_content = product.get("infinite_content", "")
                    stock_content = f"`{infinite_content}\n`"
                    
                    embed = discord.Embed(
                        title="在庫内容",
                        description=f"**商品:** `{product['name']}`\n**在庫数:** `∞`個",
                        color=discord.Color.blue(),
                        timestamp=discord.utils.utcnow()
                    )
                    embed.add_field(name="無限在庫内容", value=stock_content, inline=False)
                    embed.set_footer(text="Developer @roru2026.")
                    await interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    # 有限在庫の場合（従来通り）
                    try:
                        with open(product["stock_file"], "r", encoding="utf-8") as file:
                            content = file.read().strip()
                            
                            if not content:
                                embed = discord.Embed(
                                    title="在庫内容",
                                    description=f"**商品:** `{product['name']}`\n**在庫数:** `0`個",
                                    color=discord.Color.blue(),
                                    timestamp=discord.utils.utcnow()
                                )
                                embed.add_field(name="在庫内容", value="```\n在庫がありません\n```", inline=False)
                            else:
                                lines = [line for line in content.splitlines() if line.strip()]
                                stock_content = f"`{content}`\n"
                                
                                embed = discord.Embed(
                                    title="在庫内容",
                                    description=f"**商品:** `{product['name']}`\n**在庫数:** `{len(lines)}`個",
                                    color=discord.Color.blue(),
                                    timestamp=discord.utils.utcnow()
                                )
                                embed.add_field(name="在庫内容", value=stock_content, inline=False)
                            
                            embed.set_footer(text="Developer @roru2026.")
                            await interaction.followup.send(embed=embed, ephemeral=True)

                    except FileNotFoundError:
                        await handle_error(interaction, FileNotFoundError("在庫ファイルが見つかりません。"))
                    except Exception as e:
                        await handle_error(interaction, e)
            except Exception as e:
                await handle_error(interaction, e)

    class ProductSelectForDelete(ui.Select):
        def __init__(self, products: list):
            self.products = products
            options = [discord.SelectOption(label=p["name"], value=p["product_id"]) for p in products]
            super().__init__(
                placeholder="削除する商品を選択...", 
                options=options,
                custom_id="delete_select"
            )

        async def callback(self, interaction):
            await interaction.response.defer(ephemeral=True)
            try:
                product = next((p for p in self.products if p["product_id"] == self.values[0]), None)
                if not product:
                    await interaction.followup.send("商品が見つかりません。", ephemeral=True)
                    return

                # 確認ボタンを表示
                view = VendingMachineCog.DeleteConfirmView(product)
                
                embed = discord.Embed(
                    title="商品削除確認",
                    description=f"本当に商品「{product['name']}」を削除しますか？\n\n**この操作は取り消せません。**",
                    color=discord.Color.red()
                )
                embed.set_footer(text="Developer @roru2026.")
                
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)
                
            except Exception as e:
                await handle_error(interaction, e)

    class ProductDeleteView(ui.View):
        def __init__(self, products: list, vending_machine_id: str):
            super().__init__(timeout=None)
            self.vending_machine_id = vending_machine_id
            self.add_item(VendingMachineCog.ProductSelectForDelete(products))

    class DeleteConfirmView(ui.View):
        def __init__(self, product: dict):
            super().__init__(timeout=None)
            self.product = product

        @ui.button(label="削除する", style=discord.ButtonStyle.danger)
        async def confirm_delete(self, interaction, button):
            await interaction.response.defer(ephemeral=True)
            try:
                vending_data = load_json(VENDING_DATA_FILE)
                
                # 商品を削除
                for vm_id, vm_data in vending_data.items():
                    products = vm_data.get("products", [])
                    vm_data["products"] = [p for p in products if p["product_id"] != self.product["product_id"]]
                
                save_json(VENDING_DATA_FILE, vending_data)
                
                # 在庫ファイルも削除
                try:
                    if os.path.exists(self.product["stock_file"]):
                        os.remove(self.product["stock_file"])
                except:
                    pass
                
                embed = discord.Embed(
                    title="削除完了",
                    description=f"商品「{self.product['name']}」を削除しました。",
                    color=discord.Color.green()
                )
                embed.set_footer(text="Developer @roru2026.")
                
                await interaction.followup.send(embed=embed, ephemeral=True)
                
            except Exception as e:
                await handle_error(interaction, e)

        @ui.button(label="キャンセル", style=discord.ButtonStyle.secondary)
        async def cancel_delete(self, interaction, button):
            embed = discord.Embed(
                title="キャンセル",
                description="商品削除をキャンセルしました。",
                color=discord.Color.blue()
            )
            embed.set_footer(text="Developer @roru2026.")
            await interaction.response.send_message(embed=embed, ephemeral=True)

    class EditProductView(ui.View):
        def __init__(self, products: list, vending_machine_id: str):
            super().__init__(timeout=None)
            self.vending_machine_id = vending_machine_id
            self.add_item(VendingMachineCog.ProductSelectForEdit(products, vending_machine_id))

    class ProductSelectForEdit(ui.Select):
        def __init__(self, products: list, vending_machine_id: str):
            self.products = products
            self.vending_machine_id = vending_machine_id
            options = [discord.SelectOption(label=p["name"], value=p["product_id"]) for p in products]
            super().__init__(
                placeholder="編集する商品を選択...", 
                options=options,
                custom_id="edit_select"
            )

        async def callback(self, interaction):
            try:
                product = next((p for p in self.products if p["product_id"] == self.values[0]), None)
                if not product:
                    await interaction.response.send_message("商品が見つかりません。", ephemeral=True)
                    return

                modal = VendingMachineCog.EditProductModal(product, self.vending_machine_id)
                await interaction.response.send_modal(modal)
                
            except Exception as e:
                await handle_error(interaction, e)

    class EditProductModal(ui.Modal, title="商品情報編集"):
        def __init__(self, product: dict, vending_machine_id: str):
            super().__init__(timeout=None)
            self.product = product
            self.vending_machine_id = vending_machine_id
            
            # デフォルト値を設定
            self.name_input.default = product.get("name", "")
            self.description_input.default = product.get("description", "")
            self.price_input.default = str(product.get("price", 0))
            self.emoji_input.default = product.get("emoji", "")

        name_input = ui.TextInput(
            label="商品名",
            placeholder="新しい商品名を入力...",
            required=False,
            max_length=100
        )
        
        description_input = ui.TextInput(
            label="商品説明",
            style=discord.TextStyle.long,
            placeholder="新しい商品説明を入力...",
            required=False,
            max_length=1000
        )
        
        price_input = ui.TextInput(
            label="価格",
            placeholder="新しい価格を入力...",
            required=False,
            max_length=10
        )
        
        emoji_input = ui.TextInput(
            label="絵文字",
            placeholder="新しい絵文字を入力...",
            required=False,
            max_length=50
        )

        async def on_submit(self, interaction):
            await interaction.response.defer(ephemeral=True)
            try:
                vending_data = load_json(VENDING_DATA_FILE)
                updated_fields = []
                
                # 商品データを更新
                for vm_id, vm_data in vending_data.items():
                    for i, p in enumerate(vm_data.get("products", [])):
                        if p["product_id"] == self.product["product_id"]:
                            if self.name_input.value.strip():
                                vm_data["products"][i]["name"] = self.name_input.value.strip()
                                updated_fields.append("商品名")
                            
                            # 説明文の処理
                            if self.description_input.value is not None:
                                if self.description_input.value.strip() == "":
                                    # 空文字が明示的に入力された場合
                                    vm_data["products"][i]["description"] = ""
                                    updated_fields.append("説明: 削除されました")
                                else:
                                    vm_data["products"][i]["description"] = self.description_input.value.strip()
                                    updated_fields.append("商品説明")
                            
                            if self.price_input.value.strip():
                                try:
                                    new_price = int(self.price_input.value.strip())
                                    if new_price >= 0:
                                        vm_data["products"][i]["price"] = new_price
                                        updated_fields.append("価格")
                                    else:
                                        await interaction.followup.send("価格は0以上で入力してください。", ephemeral=True)
                                        return
                                except ValueError:
                                    await interaction.followup.send("価格には整数を入力してください。", ephemeral=True)
                                    return
                            
                            if self.emoji_input.value.strip():
                                vm_data["products"][i]["emoji"] = self.emoji_input.value.strip()
                                updated_fields.append("絵文字")
                            
                            break
                
                if updated_fields:
                    save_json(VENDING_DATA_FILE, vending_data)
                    embed = discord.Embed(
                        title="商品情報更新完了",
                        description=f"商品「{self.product['name']}」の以下の情報を更新しました:\n• " + "\n• ".join(updated_fields),
                        color=discord.Color.green()
                    )
                    embed.set_footer(text="Developer @roru2026.")
                    await interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    await interaction.followup.send("更新する項目が入力されていません。", ephemeral=True)
                
            except Exception as e:
                await handle_error(interaction, e)

    @app_commands.command(name="在庫追加通知設定", description="在庫追加時の通知設定を行います")
    @is_allowed()
    @app_commands.autocomplete(vending_machine_id=vending_machine_autocomplete)
    @app_commands.describe(
        vending_machine_id="通知設定する自販機",
        channel="通知を送信するチャンネル",
        role="メンションするロール"
    )
    async def stock_notification_setup(self, interaction, vending_machine_id: str, channel: discord.TextChannel, role: discord.Role):
        await interaction.response.defer(ephemeral=True)
        
        try:
            vending_data = load_json(VENDING_DATA_FILE)
            vm = vending_data.get(vending_machine_id)
            if not vm or vm.get("owner_id") != str(interaction.user.id):
                await interaction.followup.send("指定された自販機が見つかりません。", ephemeral=True)
                return
            
            # 通知設定を保存
            notification_data = load_stock_notification_data()
            notification_data[vending_machine_id] = {
                "channel_id": channel.id,
                "role_id": role.id,
                "guild_id": interaction.guild.id
            }
            save_stock_notification_data(notification_data)
            
            embed = discord.Embed(
                title="在庫追加通知設定",
                description=f"自販機「{vm['name']}」の在庫追加通知を設定しました。",
                color=discord.Color.green()
            )
            embed.add_field(name="通知チャンネル", value=channel.mention, inline=True)
            embed.add_field(name="メンションロール", value=role.mention, inline=True)
            embed.set_footer(text="Developer @roru2026.")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            embed = discord.Embed(
                title="ERROR",
                description=f"設定の保存中にエラーが発生しました。\n```{str(e)}```",
                color=discord.Color.red()
            )
            embed.set_footer(text="Developer @roru2026.")
            await interaction.followup.send(embed=embed, ephemeral=True)

    async def stock_notification_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        notification_data = load_stock_notification_data()
        vending_data = load_json(VENDING_DATA_FILE)
        
        choices = []
        for vm_id, notification_info in notification_data.items():
            if notification_info.get("guild_id") == interaction.guild.id:
                vm = vending_data.get(vm_id)
                if vm and vm.get("owner_id") == str(interaction.user.id):
                    vm_name = vm.get("name", "不明な自販機")
                    if current.lower() in vm_name.lower():
                        choices.append(app_commands.Choice(name=vm_name, value=vm_id))
        
        return choices[:25]

    @app_commands.command(name="在庫追加設定解除", description="在庫追加通知設定を解除します")
    @is_allowed()
    @app_commands.autocomplete(vending_machine_id=stock_notification_autocomplete)
    @app_commands.describe(vending_machine_id="通知設定を解除する自販機")
    async def stock_notification_remove(self, interaction, vending_machine_id: str):
        await interaction.response.defer(ephemeral=True)
        
        try:
            vending_data = load_json(VENDING_DATA_FILE)
            vm = vending_data.get(vending_machine_id)
            if not vm or vm.get("owner_id") != str(interaction.user.id):
                await interaction.followup.send("指定された自販機が見つかりません。", ephemeral=True)
                return
            
            # 通知設定を削除
            notification_data = load_stock_notification_data()
            if vending_machine_id in notification_data:
                del notification_data[vending_machine_id]
                save_stock_notification_data(notification_data)
                
                embed = discord.Embed(
                    title="在庫追加通知設定解除",
                    description=f"自販機「{vm['name']}」の在庫追加通知設定を解除しました。",
                    color=discord.Color.red()
                )
                embed.set_footer(text="Developer @roru2026.")
                
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.followup.send("指定された自販機に通知設定が見つかりません。", ephemeral=True)
            
        except Exception as e:
            embed = discord.Embed(
                title="ERROR",
                description=f"設定の削除中にエラーが発生しました。\n```{str(e)}```",
                color=discord.Color.red()
            )
            embed.set_footer(text="Developer @roru2026.")
            await interaction.followup.send(embed=embed, ephemeral=True)

    # クーポン関連のコマンド（自販機指定）
    @app_commands.command(name="自販機クーポン作成", description="指定した自販機用のクーポンコードを作成します")
    @is_allowed()
    @app_commands.autocomplete(vending_machine_id=vending_machine_autocomplete)
    @app_commands.describe(vending_machine_id="クーポンを作成する自販機", coupon_code="クーポンコード", discount="割引金額")
    async def vm_create_coupon(self, interaction: discord.Interaction, vending_machine_id: str, coupon_code: str, discount: int):
        try:
            if discount <= 0:
                return await interaction.response.send_message("割引金額は1円以上で指定してください。", ephemeral=True)
            
            # 自販機の存在確認
            vending_data = load_json(VENDING_DATA_FILE)
            vm = vending_data.get(vending_machine_id)
            if not vm or vm.get("owner_id") != str(interaction.user.id):
                return await interaction.response.send_message("指定された自販機が見つかりません。", ephemeral=True)
            
            coupon_data = load_coupon_data()
            
            if coupon_code in coupon_data:
                return await interaction.response.send_message("そのクーポンコードは既に存在します。", ephemeral=True)
            
            coupon_data[coupon_code] = {
                "discount": discount,
                "owner_id": str(interaction.user.id),
                "vending_machine_id": vending_machine_id,
                "created_at": str(discord.utils.utcnow())
            }
            
            save_coupon_data(coupon_data)
            
            await interaction.response.send_message(f"自販機「{vm['name']}」用のクーポンコード「{coupon_code}」を作成しました。\n割引金額: {discount}円", ephemeral=True)
        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="自販機クーポン削除", description="クーポンコードを削除します")
    @is_allowed()
    @app_commands.autocomplete(coupon_code=coupon_autocomplete)
    @app_commands.describe(coupon_code="削除するクーポンコード")
    async def vm_delete_coupon(self, interaction: discord.Interaction, coupon_code: str):
        try:
            coupon_data = load_coupon_data()
            
            if coupon_code not in coupon_data:
                return await interaction.response.send_message("指定されたクーポンコードが見つかりません。", ephemeral=True)

            coupon_info = coupon_data[coupon_code]
            if coupon_info.get("owner_id") != str(interaction.user.id):
                return await interaction.response.send_message("このクーポンコードを削除する権限がありません。", ephemeral=True)

            del coupon_data[coupon_code]
            save_coupon_data(coupon_data)
            
            await interaction.response.send_message(f"クーポンコード「{coupon_code}」を削除しました。", ephemeral=True)
        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="自販機クーポン一覧", description="作成したクーポンコードの一覧を表示します")
    @is_allowed()
    async def vm_list_coupons(self, interaction: discord.Interaction):
        try:
            coupon_data = load_coupon_data()
            vending_data = load_json(VENDING_DATA_FILE)
            user_id_str = str(interaction.user.id)
            
            user_coupons = [
                (coupon_code, coupon_info) for coupon_code, coupon_info in coupon_data.items()
                if coupon_info.get("owner_id") == user_id_str
            ]

            if not user_coupons:
                return await interaction.response.send_message("作成したクーポンコードがありません。", ephemeral=True)

            embed = discord.Embed(
                title="クーポンコード一覧",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_footer(text="Developer @roru2026.")

            for coupon_code, coupon_info in user_coupons:
                discount = coupon_info.get("discount", 0)
                created_at = coupon_info.get("created_at", "不明")
                vending_machine_id = coupon_info.get("vending_machine_id", "")
                vm_name = vending_data.get(vending_machine_id, {}).get("name", "不明な自販機")
                
                embed.add_field(
                    name=f"```{coupon_code}```",
                    value=f"割引: {discount}円\n対象自販機: {vm_name}\n作成日: {created_at[:10]}",
                    inline=True
                )

            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await handle_error(interaction, e)

    # ロール設定関連のコマンド
    @app_commands.command(name="自販機ロール設定", description="購入時に付与するロールを設定します")
    @is_allowed()
    @app_commands.autocomplete(vending_machine_id=vending_machine_autocomplete)
    @app_commands.describe(vending_machine_id="自販機", role="購入時に付与するロール")
    async def vm_set_role(self, interaction: discord.Interaction, vending_machine_id: str, role: discord.Role):
        try:
            vending_data = load_json(VENDING_DATA_FILE)
            vm = vending_data.get(vending_machine_id)
            if not vm or vm.get("owner_id") != str(interaction.user.id):
                return await interaction.response.send_message("指定された自販機が見つかりません。", ephemeral=True)
            
            role_data = load_role_assignment_data()
            role_data[vending_machine_id] = {
                "role_id": role.id,
                "guild_id": interaction.guild.id
            }
            save_role_assignment_data(role_data)
            
            await interaction.response.send_message(f"自販機「{vm['name']}」の購入時付与ロールを {role.mention} に設定しました。", ephemeral=True)
        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="自販機ロール解除", description="購入時のロール付与設定を解除します")
    @is_allowed()
    @app_commands.autocomplete(vending_machine_id=role_assignment_autocomplete)
    @app_commands.describe(vending_machine_id="ロール設定を解除する自販機")
    async def vm_remove_role(self, interaction: discord.Interaction, vending_machine_id: str):
        try:
            vending_data = load_json(VENDING_DATA_FILE)
            vm = vending_data.get(vending_machine_id)
            if not vm or vm.get("owner_id") != str(interaction.user.id):
                return await interaction.response.send_message("指定された自販機が見つかりません。", ephemeral=True)
            
            role_data = load_role_assignment_data()
            if vending_machine_id in role_data:
                del role_data[vending_machine_id]
                save_role_assignment_data(role_data)
                
                await interaction.response.send_message(f"自販機「{vm['name']}」のロール付与設定を解除しました。", ephemeral=True)
            else:
                await interaction.response.send_message("指定された自販機にロール設定が見つかりません。", ephemeral=True)
        except Exception as e:
            await handle_error(interaction, e)

async def setup(bot):
    await bot.add_cog(VendingMachineCog(bot))

