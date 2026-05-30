"""
にゃんこ代行.py  ―  vd-pro 版
==============================
yu_vd の「有料にゃんこ代行.py」と「にゃんこ複製.py」を
vd-pro の utils 構造（is_allowed / is_owner / safe_respond / OWNER_ID）に合わせて統合したファイルです。

【含む機能】
  - にゃんこ大戦争アカウント複製パネル（複製 / 最強垢作成）
  - 有料にゃんこ代行パネル（引き継ぎコード不要の自動編集代行）
  - 各種管理コマンド（価格設定・売上確認・ライセンス付与など）

【依存ライブラリ】
  pip install bcsfe discord.py python-dotenv beautifulsoup4
  （bcsfe は git clone が必要な場合あり）

【データファイルパス（vd-pro 準拠）】
  stock_files/base_account.json       … 最強垢のベース引き継ぎコード
  stock_files/duplicate_panel.json    … 複製パネルの設定
  stock_files/daiko_config.json       … 代行パネルの設定
  stock_files/cat_names.json          … 有効 Cat ID 辞書
  paypay_data.json                    … PayPay 認証情報（vd-pro 共通）
  daiko_prices/<guild_id>.json        … サーバー別代行価格
  daiko_sales.json                    … 売上集計
  daiko_licenses.json                 … 無料ライセンス一覧
  daiko_config/<guild_id>.json        … サーバー別実績チャンネル
"""

import sys
import os
import asyncio
import discord
from discord import app_commands, ui
from discord.ext import commands
import traceback
import json
import time
import io
import datetime
from datetime import timezone

from utils import is_allowed, is_owner, safe_respond, OWNER_ID
import paypayu

# ==========================================
# bcsfe インポート（複製機能用）
# ==========================================
BCSFE_AVAILABLE = False
try:
    from bcsfe import core
    from bcsfe.core.server.server_handler import ServerHandler
    from bcsfe.core.game.gamoto.gamatoto import Helper
    from bcsfe.core.game.catbase.cat import Talent

    if getattr(core.core_data, "config", None) is None:
        core.set_config_path(core.Path("config.json"))
        core.set_log_path(core.Path("bcsfe.log"))
        core.core_data.init_data()

    BCSFE_AVAILABLE = True
    print("[にゃんこ代行] bcsfe を正常に読み込みました")
except ImportError as e:
    print(f"[にゃんこ代行] bcsfe インポート失敗（複製機能は無効）: {e}")

# ==========================================
# Savedataedit インポート（代行機能用）
# ==========================================
SAVE_EDITOR_AVAILABLE = False
try:
    from Savedataedit import SaveEditor, load_from_transfer
    SAVE_EDITOR_AVAILABLE = True
    print("[にゃんこ代行] Savedataedit を正常に読み込みました")
except ImportError as e:
    SaveEditor = None
    load_from_transfer = None
    print(f"[にゃんこ代行] Savedataedit インポート失敗（代行機能は無効）: {e}")


# ==========================================
# ファイルパス定数（vd-pro: stock_files/ 以下）
# ==========================================
_SF = "stock_files"

BASE_ACCOUNT_FILE    = os.path.join(_SF, "base_account.json")
DUPLICATE_PANEL_FILE = os.path.join(_SF, "duplicate_panel.json")
DAIKO_CONFIG_FILE    = os.path.join(_SF, "daiko_config.json")
CAT_NAMES_FILE       = os.path.join(_SF, "cat_names.json")
PAYPAY_DATA_FILE     = "paypay_data.json"   # vd-pro 共通

PRICES_DIR    = "daiko_prices"
SALES_FILE    = "daiko_sales.json"
LICENSE_FILE  = "daiko_licenses.json"
DAIKO_CFG_DIR = "daiko_config"


# ==========================================
# JSON ユーティリティ
# ==========================================

def _load_json(path: str) -> dict:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_json(path: str, data: dict):
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def load_paypay_data() -> dict:
    return _load_json(PAYPAY_DATA_FILE)


# ==========================================
# 価格・売上・ライセンス ヘルパー
# ==========================================

ITEM_PRICES: dict[str, int] = {
    "xp": 10, "np": 10, "catfood": 10, "battle_items": 10, "vitamins": 10,
    "base_materials": 10, "catseyes": 10, "talent_orbs": 10,
    "rare": 10, "platinum": 10, "legend": 10, "event_ticket": 10, "lead": 10,
    "sub_medals": 10, "unlock_all": 10, "remove_error": 10, "levels_max": 10,
    "forms_max": 10, "talents_max": 10, "main_clear": 10,
    "zombie_clear": 10, "legend_clear": 10, "uncanny_clear": 10, "legend_quest": 10,
    "ex_clear": 10, "zero_clear": 10, "aku_clear": 10, "event_clear": 10,
    "gamatoto_max": 10, "gamatoto_hlp": 10, "ototo_max": 10, "shrine_max": 10,
    "playtime": 10, "gold_member": 10, "deck_slots": 10, "medals": 10,
    "all_medals": 10, "enemy_enc": 10, "rank_rewards": 10,
    "tutorial_skip": 10, "dojo_max": 10, "missions_clear": 10, "weekly_missions": 10,
}

G1_OPTIONS = [
    ("xp",            "XP MAX"),
    ("np",            "NP MAX"),
    ("catfood",       "猫缶 MAX"),
    ("battle_items",  "バトルアイテム全種 MAX"),
    ("vitamins",      "ネコビタン全種 MAX"),
    ("base_materials","城素材全種 MAX"),
    ("catseyes",      "キャッツアイ全種 MAX"),
    ("talent_orbs",   "本能玉全種 MAX"),
    ("rare",          "にゃんチケ&レアチケ MAX"),
    ("platinum",      "プラチナチケ MAX"),
    ("legend",        "レジェチケ MAX"),
    ("event_ticket",  "イベントチケ&福チケ MAX"),
    ("lead",          "リーダーシップ MAX"),
    ("sub_medals",    "地底迷宮メダル全種 MAX"),
]
G2_OPTIONS = [
    ("unlock_all",   "全キャラ開放"),
    ("remove_error", "エラーキャラ削除"),
    ("levels_max",   "全キャラ/施設 LvMAX"),
    ("forms_max",    "全キャラ最高形態"),
    ("talents_max",  "全キャラ本能全開放"),
]
G3_OPTIONS = [
    ("main_clear",    "メインステージ全クリア+金お宝"),
    ("zombie_clear",  "メインゾンビステージ全クリア"),
    ("legend_clear",  "レジェンド全クリア"),
    ("uncanny_clear", "旧レジェンド全クリア"),
    ("legend_quest",  "レジェンドクエスト全クリア"),
    ("ex_clear",      "真レジェンド全クリア"),
    ("zero_clear",    "零レジェンド全クリア"),
    ("aku_clear",     "魔界編全クリア"),
    ("event_clear",   "イベントステージ全クリア"),
]
G4_OPTIONS = [
    ("gamatoto_max",   "ガマトト LvMAX"),
    ("gamatoto_hlp",   "ガマトト助手 全員レジェンド化"),
    ("ototo_max",      "オトート全城強化 LvMAX"),
    ("shrine_max",     "にゃんこ神社 LvMAX"),
    ("playtime",       "プレイ時間カンスト"),
    ("gold_member",    "ゴールド会員化"),
    ("deck_slots",     "編成スロット数最大拡張"),
    ("medals",         "にゃんこメダル全開放"),
    ("all_medals",     "全メダル獲得"),
    ("enemy_enc",      "敵キャラ図鑑全開放"),
    ("rank_rewards",   "ユーザーランク報酬全受取"),
    ("tutorial_skip",  "チュートリアルスキップ"),
    ("dojo_max",       "道場スコア MAX"),
    ("missions_clear", "全ミッションクリア"),
    ("weekly_missions", "ウィークリーミッション全クリア"),
]

ALL_OPTIONS = {v: l for v, l in G1_OPTIONS + G2_OPTIONS + G3_OPTIONS + G4_OPTIONS}


def _prices_file(guild_id: int) -> str:
    os.makedirs(PRICES_DIR, exist_ok=True)
    return os.path.join(PRICES_DIR, f"{guild_id}.json")


def _load_prices(guild_id: int) -> dict:
    path = _prices_file(guild_id)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return dict(ITEM_PRICES)


def _save_prices(guild_id: int, data: dict):
    with open(_prices_file(guild_id), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_sales() -> dict:
    if os.path.exists(SALES_FILE):
        try:
            with open(SALES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"total": 0, "users": {}}


def _record_sale(user_id: int, amount: int):
    if amount <= 0:
        return
    data = _load_sales()
    uid  = str(user_id)
    data["users"][uid] = data["users"].get(uid, 0) + amount
    data["total"]      = data.get("total", 0) + amount
    with open(SALES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_licenses() -> dict:
    if os.path.exists(LICENSE_FILE):
        try:
            with open(LICENSE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_licenses(data: dict):
    with open(LICENSE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _has_license(user_id: int) -> bool:
    data   = _load_licenses()
    expiry = data.get(str(user_id), 0)
    return expiry == -1 or expiry > time.time()


def get_options_with_price(opts: list, guild_id: int = 0) -> list:
    prices = _load_prices(guild_id)
    return [(k, f"{l} ¥{prices.get(k, ITEM_PRICES.get(k, 0))}") for k, l in opts]


def calc_total(selected: list[str], guild_id: int = 0) -> int:
    prices = _load_prices(guild_id)
    return sum(prices.get(k, ITEM_PRICES.get(k, 0)) for k in selected)


# ==========================================
# bcsfe ヘルパー（複製機能）
# ==========================================

def get_valid_cat_ids() -> set:
    data = _load_json(CAT_NAMES_FILE)
    return {int(k) for k in data if k.isdigit()}


def get_handler_sync(transfer_code, confirm_code):
    cc = core.CountryCode.from_code("jp")
    gv = core.GameVersion.from_string("13.0.0")
    handler, _ = ServerHandler.from_codes(
        transfer_code, confirm_code, cc, gv, print=False, save_backup=False
    )
    return handler


def create_and_get_codes_sync(handler):
    if not handler.create_new_account():
        return None
    return handler.get_codes()


# ─── 全マシ処理（最強垢作成） ──────────────────────────────────────

def _maximize_upgrades_in_obj(obj, visited=None):
    if obj is None: return
    if visited is None: visited = set()
    if id(obj) in visited: return
    visited.add(id(obj))
    if type(obj).__name__ == "Upgrade":
        obj.base = 29; obj.plus = 10; return
    if isinstance(obj, (dict, list, tuple)):
        for v in (obj.values() if isinstance(obj, dict) else obj):
            _maximize_upgrades_in_obj(v, visited)
        return
    try:
        for attr in dir(obj):
            if attr.startswith("__"): continue
            val = getattr(obj, attr)
            if type(val).__name__ == "Upgrade":
                val.base = 29; val.plus = 10
            elif isinstance(val, (dict, list, tuple)):
                _maximize_upgrades_in_obj(val, visited)
    except Exception:
        pass


def super_safe_max_items(obj, max_val=9999):
    if not obj: return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if hasattr(v, "amount"): v.amount = max_val
            elif hasattr(v, "value"): v.value = max_val
            else: obj[k] = max_val
        return
    if isinstance(obj, list):
        for i in range(len(obj)):
            if hasattr(obj[i], "amount"): obj[i].amount = max_val
            elif hasattr(obj[i], "value"): obj[i].value = max_val
            else: obj[i] = max_val
        return
    if hasattr(obj, "items"): super_safe_max_items(obj.items, max_val)
    elif hasattr(obj, "materials"): super_safe_max_items(obj.materials, max_val)
    elif hasattr(obj, "orbs"): super_safe_max_items(obj.orbs, max_val)


def super_safe_clear(obj, visited=None):
    if obj is None: return
    if visited is None: visited = set()
    if id(obj) in visited: return
    visited.add(id(obj))
    if isinstance(obj, (dict, list, tuple)):
        for v in (obj.values() if isinstance(obj, dict) else obj):
            super_safe_clear(v, visited)
        return
    if isinstance(obj, (int, float, str, bool)): return
    for attr in ["clear_times", "clear_amount"]:
        if hasattr(obj, attr):
            try: setattr(obj, attr, 1)
            except: pass
    if hasattr(obj, "treasure"):
        try: obj.treasure = 3
        except: pass
    if hasattr(obj, "clear_progress"):
        try:
            obj.clear_progress = len(obj.stages) if hasattr(obj, "stages") and hasattr(obj.stages, "__len__") else 48
        except: pass
    for attr in ["unlock_state", "chapter_unlock_state"]:
        if hasattr(obj, attr):
            try: setattr(obj, attr, 3)
            except: pass
    try:
        for attr in dir(obj):
            if attr.startswith("__"): continue
            if attr in ["chapters","stages","outbreaks","event_stages","uncanny","zero_legends",
                        "aku","sub_chapters","gauntlets","collab_gauntlets","behemoth_culling",
                        "tower","enigma","legend_quest","timed_score","missions","login_bonuses"]:
                try: super_safe_clear(getattr(obj, attr), visited)
                except: pass
    except: pass


def apply_all_max(save_file):
    """セーブデータを全マシ状態にする"""
    try:
        valid_cat_ids = get_valid_cat_ids()

        save_file.xp = 99999999; save_file.np = 9999; save_file.catfood = 45000
        save_file.leadership = 9999; save_file.normal_tickets = 999
        save_file.rare_tickets = 299; save_file.platinum_tickets = 9; save_file.legend_tickets = 4

        if hasattr(save_file, "event_capsules"):
            for i in range(len(save_file.event_capsules)): save_file.event_capsules[i] = 999
        if hasattr(save_file, "lucky_tickets"):
            for i in range(len(save_file.lucky_tickets)): save_file.lucky_tickets[i] = 999

        super_safe_max_items(getattr(save_file, "battle_items", None), 9999)
        super_safe_max_items(getattr(save_file, "catamins", None), 9999)
        if hasattr(save_file, "ototo"):
            super_safe_max_items(getattr(save_file.ototo, "base_materials", None), 9999)
        super_safe_max_items(getattr(save_file, "catseyes", None), 999)

        if hasattr(save_file, "catfruit"):
            for i in range(len(save_file.catfruit)): save_file.catfruit[i] = 99
        if hasattr(save_file, "talent_orbs") and hasattr(save_file.talent_orbs, "orbs"):
            for i in range(1, 150):
                save_file.talent_orbs.orbs[i] = core.TalentOrb(i, 99)
        if hasattr(save_file, "labyrinth_medals"):
            for i in range(len(save_file.labyrinth_medals)): save_file.labyrinth_medals[i] = 9999

        for upg_attr in ["upgrades", "normal_upgrades", "base_upgrades", "tech"]:
            try:
                if hasattr(save_file, upg_attr):
                    _maximize_upgrades_in_obj(getattr(save_file, upg_attr))
            except: pass

        for ui_attr in ["ui1","ui2","ui3","ui4","ui5","ui6","ui7","ui8","ui9"]:
            try: setattr(save_file, ui_attr, 29)
            except: pass

        pic_book = talent_data = None
        try: pic_book    = save_file.cats.read_nyanko_picture_book(save_file)
        except: pass
        try: talent_data = save_file.cats.read_talent_data(save_file)
        except: pass

        for cat in save_file.cats.cats:
            is_valid = cat.id in valid_cat_ids and cat.id != 673
            if pic_book and pic_book.get_cat(cat.id) is None:
                is_valid = False

            if not is_valid:
                cat.unlocked = 0; cat.upgrade.base = 0; cat.upgrade.plus = 0
                cat.current_form = 0; cat.unlocked_forms = 0; cat.fourth_form = 0
                continue

            cat.unlocked = 1; cat.upgrade.base = 59; cat.upgrade.plus = 90
            if hasattr(save_file.cats, "chara_new_flags"):
                save_file.cats.chara_new_flags[cat.id] = 0

            total_forms = 3
            if pic_book:
                pc = pic_book.get_cat(cat.id)
                if pc: total_forms = pc.total_forms

            if total_forms >= 4:
                cat.unlocked_forms = 3; cat.current_form = 2; cat.fourth_form = 2
            elif total_forms == 3: cat.unlocked_forms = 3; cat.current_form = 2
            elif total_forms == 2: cat.unlocked_forms = 2; cat.current_form = 1
            else:                  cat.unlocked_forms = 1; cat.current_form = 0

            if talent_data is not None:
                cat_skill = talent_data.get_cat_skill(cat.id)
                if cat_skill and hasattr(cat_skill, "skills"):
                    try:
                        cat.talents = [
                            Talent(getattr(s, "ability_id", 0), max(getattr(s, "max_lv", 10), 1))
                            for s in cat_skill.skills
                        ]
                    except: pass

        if hasattr(save_file, "story"):
            for ch in save_file.story.chapters:
                ch.progress = 48
                for st in ch.stages: st.clear_times = 1; st.treasure = 3

        for attr in ["outbreaks","event_stages","uncanny","zero_legends","aku","gauntlets",
                     "collab_gauntlets","behemoth_culling","tower","enigma","legend_quest",
                     "timed_score"]:
            super_safe_clear(getattr(save_file, attr, None))

        if hasattr(save_file, "gamatoto"):
            save_file.gamatoto.xp = 99999999
            if hasattr(save_file.gamatoto, "helpers"):
                save_file.gamatoto.helpers.helpers = [Helper(4) for _ in range(10)]

        if hasattr(save_file, "ototo") and hasattr(save_file.ototo, "cannons"):
            for cannon in save_file.ototo.cannons.cannons.values():
                cannon.development = 3; cannon.levels = [30, 30, 30]

        try:
            if hasattr(save_file, "cat_shrine"):
                save_file.cat_shrine.xp_offering = 99999999
                if hasattr(save_file.cat_shrine, "level"): save_file.cat_shrine.level = 50
                if hasattr(save_file.cat_shrine, "unlocked"): save_file.cat_shrine.unlocked = True
        except: pass

        try:
            medal_names = core.core_data.get_medal_names(save_file)
            if medal_names and medal_names.medal_names:
                for i, m in enumerate(medal_names.medal_names):
                    if m: save_file.medals.add_medal(i)
        except: pass

        if hasattr(save_file, "enemy_guide"):
            save_file.enemy_guide = [1] * len(save_file.enemy_guide)
        try:
            if hasattr(save_file, "enemy_guide_new"):
                save_file.enemy_guide_new = [0] * len(save_file.enemy_guide_new)
        except: pass

        if hasattr(save_file, "missions"):
            super_safe_clear(save_file.missions)
            try:
                if hasattr(save_file.missions, "missions"):
                    for m in save_file.missions.missions:
                        if hasattr(m, "completed"): m.completed = True
                        if hasattr(m, "claimed"):   m.claimed   = True
                        if hasattr(m, "state"):     m.state     = 2
            except: pass

        if hasattr(save_file, "login_bonuses"):
            super_safe_clear(save_file.login_bonuses)

        if hasattr(save_file, "user_rank_rewards") and hasattr(save_file.user_rank_rewards, "rewards"):
            for r in save_file.user_rank_rewards.rewards:
                if hasattr(r, "claimed"): r.claimed = True

        if hasattr(save_file, "officer_pass"):
            save_file.officer_pass.play_time = 2147483647
            if hasattr(save_file.officer_pass, "gold_pass"):
                try: save_file.officer_pass.gold_pass.get_gold_pass(12345, 30, save_file)
                except: pass

        try:
            save_file.date_3 = datetime.datetime.now()
            save_file.timestamp = datetime.datetime.now().timestamp()
            save_file.energy_penalty_timestamp = datetime.datetime.now().timestamp()
            if hasattr(save_file, "gamatoto"): save_file.gamatoto.skin = 2
            if hasattr(save_file, "ototo"):
                save_file.ototo.cannons = core.game.gamoto.ototo.Cannons.init(save_file.game_version)
            if hasattr(save_file, "officer_pass"):
                save_file.officer_pass.cat_id = 0; save_file.officer_pass.cat_form = 0
        except: pass

        try:
            if hasattr(save_file, "dojo") and hasattr(save_file.dojo, "chapters"):
                st = save_file.dojo.chapters.get_stage(0, 0)
                if st: st.score = 999999
        except: pass

        try:
            if hasattr(save_file, "unlock_popups") and hasattr(save_file.unlock_popups, "popups"):
                for popup in save_file.unlock_popups.popups.values():
                    if hasattr(popup, "seen"): popup.seen = True
        except: pass

        try:
            if hasattr(save_file, "cats") and hasattr(save_file.cats, "storage_items"):
                save_file.cats.storage_items = []
        except: pass

        try: save_file.sanitize()
        except: pass

    except Exception as e:
        print(f"[全マシ] 処理中にエラー: {e}")


def apply_max_sync(handler):
    apply_all_max(handler.save_file)


# ==========================================
# UI：アカウント複製パネル
# ==========================================

class DuplicateModal(discord.ui.Modal, title="アカウント複製（決済＆コード入力）"):
    def __init__(self, unit_price: int, owner_id: str):
        super().__init__()
        self.unit_price = unit_price
        self.owner_id   = owner_id

        self.transfer_code = discord.ui.TextInput(label="引き継ぎコード", placeholder="例: 1a2b3c4d5", required=True)
        self.confirm_code  = discord.ui.TextInput(label="確認コード",     placeholder="例: 1234",      required=True)
        self.amount        = discord.ui.TextInput(label="複製する数（最大10）", placeholder="例: 5", default="1", required=True)
        self.add_item(self.transfer_code)
        self.add_item(self.confirm_code)
        self.add_item(self.amount)

        if self.unit_price > 0:
            self.pay_link = discord.ui.TextInput(
                label=f"PayPay リンク（単価 {self.unit_price}円 × 個数分）",
                placeholder="https://pay.paypay.ne.jp/...",
                required=True,
            )
            self.add_item(self.pay_link)
        else:
            self.pay_link = None

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            await interaction.channel.send(f"{interaction.user.mention} が **アカウント複製** を使用しました")
        except Exception:
            pass

        try:
            num = int(self.amount.value)
            if not 1 <= num <= 10:
                return await interaction.followup.send("エラー：1個〜10個の範囲で指定してください。", ephemeral=True)
        except ValueError:
            return await interaction.followup.send("エラー：半角数字で入力してください。", ephemeral=True)

        total_price = num * self.unit_price

        if total_price > 0:
            pp_data    = load_paypay_data()
            owner_cred = pp_data.get(self.owner_id) or pp_data.get(str(self.owner_id))
            if not owner_cred:
                return await interaction.followup.send("エラー: 販売者の PayPay が登録されていません。", ephemeral=True)

            link_val = self.pay_link.value.strip()
            info     = await paypayu.check_link(link_val)
            received = (info.get("payload", {}).get("pendingP2PInfo", {}).get("amount", 0)
                        if info else 0)

            if received < total_price:
                return await interaction.followup.send(
                    f"エラー: 金額が不足しています。必要: {total_price}円 / リンク: {received}円", ephemeral=True
                )

            rev = await paypayu.link_rev(link_val, owner_cred["phone"], owner_cred["password"], owner_cred["uuid"])
            if rev is not True:
                return await interaction.followup.send("エラー: PayPay の受け取りに失敗しました。", ephemeral=True)

        msg = await interaction.followup.send(
            embed=discord.Embed(
                title="処理中...",
                description=f"アカウントを {num}個 複製しています...\n（時間がかかります）",
                color=0x00AAFF,
            ),
            wait=True, ephemeral=True,
        )

        try:
            handler = await asyncio.to_thread(get_handler_sync, self.transfer_code.value, self.confirm_code.value)
            if handler is None:
                return await msg.edit(embed=discord.Embed(title="エラー", description="データの取得に失敗しました。コードを確認してください。", color=0xFF0000))

            results = []
            for i in range(num):
                codes = await asyncio.to_thread(create_and_get_codes_sync, handler)
                if codes:
                    results.append(f"【{i+1}個目】\n引き継ぎ: `{codes[0]}`\n確認: `{codes[1]}`")
                else:
                    results.append(f"【{i+1}個目】\nアカウント作成失敗")
                await asyncio.sleep(0.1)

            result_text = "\n".join(results)
            if total_price > 0:
                _record_sale(interaction.user.id, total_price)

            try:
                if len(result_text) <= 4000:
                    await interaction.user.send(
                        embed=discord.Embed(title="複製完了", description=f"{num}個 複製しました！\n\n{result_text}", color=0x00AAFF)
                    )
                else:
                    buf = io.BytesIO(result_text.replace("`","").encode("utf-8"))
                    await interaction.user.send(
                        embed=discord.Embed(title="複製完了", description=f"{num}個 複製しました！（ファイル参照）", color=0x00AAFF),
                        file=discord.File(fp=buf, filename="results.txt"),
                    )
                await msg.edit(embed=discord.Embed(title="完了", description="複製結果を DM に送信しました！", color=0x00AAFF))

                dc = _load_json(DAIKO_CONFIG_FILE)
                log_ch_id = dc.get("panel_log_channel_id")
                if log_ch_id:
                    lc = interaction.client.get_channel(log_ch_id)
                    if lc:
                        le = discord.Embed(title="【アカウント複製】実績ログ", color=0x00AAFF)
                        le.add_field(name="実行者", value=f"{interaction.user.mention}", inline=False)
                        le.add_field(name="製造数", value=f"{num}個", inline=False)
                        le.add_field(name="売上金額", value=f"**{total_price}円**", inline=False)
                        await lc.send(embed=le)
            except discord.Forbidden:
                await msg.edit(embed=discord.Embed(title="エラー", description="DM の送信に失敗しました。DM を開放してください。", color=0xFF0000))

        except Exception as e:
            await msg.edit(embed=discord.Embed(
                title="エラーが発生しました",
                description=f"```py\n{e}\n```",
                color=0xFF0000,
            ))
            print(f"[ERROR: 複製]\n{traceback.format_exc()}")


class AutoCreateMaxModal(discord.ui.Modal, title="最強アカウント作成（決済）"):
    def __init__(self, unit_price: int, owner_id: str):
        super().__init__()
        self.unit_price = unit_price
        self.owner_id   = owner_id

        self.amount = discord.ui.TextInput(label="作成する数（最大10）", placeholder="例: 5", default="1", required=True)
        self.add_item(self.amount)

        if self.unit_price > 0:
            self.pay_link = discord.ui.TextInput(
                label=f"PayPay リンク（単価 {self.unit_price}円 × 個数分）",
                placeholder="https://pay.paypay.ne.jp/...",
                required=True,
            )
            self.add_item(self.pay_link)
        else:
            self.pay_link = None

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            await interaction.channel.send(f"{interaction.user.mention} が **最強アカウント作成** を使用しました")
        except Exception:
            pass

        base = _load_json(BASE_ACCOUNT_FILE)
        if not base.get("transfer_code") or not base.get("confirm_code"):
            return await interaction.followup.send("エラー: ベースアカウントが登録されていません。", ephemeral=True)

        try:
            num = int(self.amount.value)
            if not 1 <= num <= 10:
                return await interaction.followup.send("エラー：1個〜10個の範囲で指定してください。", ephemeral=True)
        except ValueError:
            return await interaction.followup.send("エラー：半角数字で入力してください。", ephemeral=True)

        total_price = num * self.unit_price

        if total_price > 0:
            pp_data    = load_paypay_data()
            owner_cred = pp_data.get(self.owner_id) or pp_data.get(str(self.owner_id))
            if not owner_cred:
                return await interaction.followup.send("エラー: 販売者の PayPay が登録されていません。", ephemeral=True)

            link_val = self.pay_link.value.strip()
            info     = await paypayu.check_link(link_val)
            received = (info.get("payload", {}).get("pendingP2PInfo", {}).get("amount", 0) if info else 0)

            if received < total_price:
                return await interaction.followup.send(
                    f"エラー: 金額が不足しています。必要: {total_price}円 / リンク: {received}円", ephemeral=True
                )

            rev = await paypayu.link_rev(link_val, owner_cred["phone"], owner_cred["password"], owner_cred["uuid"])
            if rev is not True:
                return await interaction.followup.send("エラー: PayPay の受け取りに失敗しました。", ephemeral=True)

        msg = await interaction.followup.send(
            embed=discord.Embed(
                title="自動作成中...",
                description=f"最強アカウントを {num}個 量産しています...",
                color=0x00AAFF,
            ),
            wait=True, ephemeral=True,
        )

        try:
            handler = await asyncio.to_thread(get_handler_sync, base["transfer_code"], base["confirm_code"])
            if handler is None:
                return await msg.edit(embed=discord.Embed(title="エラー", description="ベースデータの取得に失敗しました。", color=0xFF0000))

            await asyncio.to_thread(apply_max_sync, handler)

            # ベースアカウントを先に自己更新（客のコードと分離）
            new_base = await asyncio.to_thread(create_and_get_codes_sync, handler)
            if new_base:
                _save_json(BASE_ACCOUNT_FILE, {"transfer_code": new_base[0], "confirm_code": new_base[1]})

            results = []
            for i in range(num):
                codes = await asyncio.to_thread(create_and_get_codes_sync, handler)
                if codes:
                    results.append(f"【{i+1}個目】\n引き継ぎ: `{codes[0]}`\n確認: `{codes[1]}`")
                else:
                    results.append(f"【{i+1}個目】\nアカウント作成失敗")
                await asyncio.sleep(0.1)

            result_text = "\n".join(results)
            if total_price > 0:
                _record_sale(interaction.user.id, total_price)

            try:
                if len(result_text) <= 4000:
                    await interaction.user.send(
                        embed=discord.Embed(title="最強アカウント作成完了", description=f"{num}個 作成しました！\n\n{result_text}", color=0x00AAFF)
                    )
                else:
                    buf = io.BytesIO(result_text.replace("`","").encode("utf-8"))
                    await interaction.user.send(
                        embed=discord.Embed(title="最強アカウント作成完了", description=f"{num}個 作成しました！（ファイル参照）", color=0x00AAFF),
                        file=discord.File(fp=buf, filename="results_max.txt"),
                    )
                await msg.edit(embed=discord.Embed(title="完了", description="最強アカウント情報を DM に送信しました！", color=0x00AAFF))

                dc = _load_json(DAIKO_CONFIG_FILE)
                log_ch_id = dc.get("panel_log_channel_id")
                if log_ch_id:
                    lc = interaction.client.get_channel(log_ch_id)
                    if lc:
                        le = discord.Embed(title="【最強アカウント作成】実績ログ", color=0x00AAFF)
                        le.add_field(name="実行者", value=f"{interaction.user.mention}", inline=False)
                        le.add_field(name="製造数", value=f"{num}個", inline=False)
                        le.add_field(name="売上金額", value=f"**{total_price}円**", inline=False)
                        await lc.send(embed=le)
            except discord.Forbidden:
                await msg.edit(embed=discord.Embed(title="エラー", description="DM の送信に失敗しました。DM を開放してください。", color=0xFF0000))

        except Exception as e:
            await msg.edit(embed=discord.Embed(
                title="エラーが発生しました",
                description=f"```py\n{e}\n```",
                color=0xFF0000,
            ))
            print(f"[ERROR: 最強垢]\n{traceback.format_exc()}")


class DuplicatePanelView(discord.ui.View):
    """複製パネル（常設）"""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="アカウント複製", style=discord.ButtonStyle.blurple, custom_id="nyanko_dup_btn_v2")
    async def btn_duplicate(self, interaction: discord.Interaction, button: discord.ui.Button):
        pd    = _load_json(DUPLICATE_PANEL_FILE)
        price = pd.get("duplicate_price", 0)
        oid   = str(pd.get("owner_id", OWNER_ID))
        if not BCSFE_AVAILABLE:
            return await interaction.response.send_message("⚠️ 複製機能が現在利用できません（bcsfe 未インストール）。", ephemeral=True)
        await interaction.response.send_modal(DuplicateModal(unit_price=price, owner_id=oid))

    @discord.ui.button(label="最強アカウント作成", style=discord.ButtonStyle.red, custom_id="nyanko_max_btn_v2")
    async def btn_create_max(self, interaction: discord.Interaction, button: discord.ui.Button):
        pd    = _load_json(DUPLICATE_PANEL_FILE)
        price = pd.get("max_price", 0)
        oid   = str(pd.get("owner_id", OWNER_ID))
        if not BCSFE_AVAILABLE:
            return await interaction.response.send_message("⚠️ 最強垢作成機能が現在利用できません（bcsfe 未インストール）。", ephemeral=True)
        await interaction.response.send_modal(AutoCreateMaxModal(unit_price=price, owner_id=oid))


# ==========================================
# UI：有料代行パネル（引き継ぎコード不要）
# ==========================================

class DaikoMenuView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(
        label="ログインして注文する",
        style=discord.ButtonStyle.success,
        emoji="🛒",
        custom_id="daiko_paid_login_v4",
    )
    async def login_btn(self, interaction: discord.Interaction, button: ui.Button):
        if not SAVE_EDITOR_AVAILABLE:
            return await interaction.response.send_message("⚠️ 代行機能が現在利用できません（Savedataedit 未インストール）。", ephemeral=True)
        try:
            await interaction.response.send_modal(DaikoLoginModal())
        except Exception as e:
            print(f"[代行] ログインボタンエラー: {e}")
            try:
                await interaction.followup.send("エラーが発生しました。コマンド `/にゃんこ代行` を再実行してください。", ephemeral=True)
            except Exception:
                pass


class DaikoLoginModal(ui.Modal, title="アカウントログイン"):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(ui.TextInput(label="引き継ぎコード", placeholder="引き継ぎコードを入力してください"))
        self.add_item(ui.TextInput(label="認証コード", placeholder="4桁の認証コード", min_length=4, max_length=4))

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            editor = await load_from_transfer(self.children[0].value, self.children[1].value, "jp")
            embed  = discord.Embed(title="代行内容を選択", description="カテゴリから項目を選んでください", color=0x5865F2)
            await interaction.followup.send(embed=embed, view=DaikoPaidSelectView(editor, interaction.guild_id or 0), ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"ログイン失敗: {e}", ephemeral=True)


class DaikoPaidSelectView(ui.View):
    def __init__(self, editor, guild_id: int = 0):
        super().__init__(timeout=300)
        self.editor   = editor
        self.guild_id = guild_id
        self.sel1 = self.sel2 = self.sel3 = self.sel4 = []

        self.add_item(_GroupSelect(self, get_options_with_price(G1_OPTIONS, guild_id), "アイテム系を選択",    0))
        self.add_item(_GroupSelect(self, get_options_with_price(G2_OPTIONS, guild_id), "キャラ系を選択",      1))
        self.add_item(_GroupSelect(self, get_options_with_price(G3_OPTIONS, guild_id), "ステージ系を選択",    2))
        self.add_item(_GroupSelect(self, get_options_with_price(G4_OPTIONS, guild_id), "施設・その他を選択",  3))

        confirm_btn = ui.Button(label="確定して金額確認", style=discord.ButtonStyle.success, emoji="✅", row=4)
        confirm_btn.callback = self._confirm
        self.add_item(confirm_btn)

    def _all_selected(self):
        return self.sel1 + self.sel2 + self.sel3 + self.sel4

    async def _confirm(self, interaction: discord.Interaction):
        selected = self._all_selected()
        if not selected:
            return await interaction.response.send_message("何も選択されていません。", ephemeral=True)
        total  = calc_total(selected, self.guild_id)
        prices = _load_prices(self.guild_id)
        lines  = "\n".join(f"・{ALL_OPTIONS.get(k,k)} ¥{prices.get(k, ITEM_PRICES.get(k,0))}" for k in selected)
        embed  = discord.Embed(title="金額確認", description=f"{lines}\n\n**合計 ¥{total}**", color=0x2ECC71)
        await interaction.response.send_message(embed=embed, view=_PayConfirmView(self.editor, selected, total), ephemeral=True)


class _GroupSelect(ui.Select):
    def __init__(self, parent_view, opts, placeholder, row):
        self.parent_view = parent_view
        options = [discord.SelectOption(label=label, value=val) for val, label in opts]
        super().__init__(
            placeholder=placeholder,
            min_values=0,
            max_values=len(options),
            options=options,
            row=row,
            custom_id=f"daiko_grp_{row}_{hash(placeholder) % 9999:04d}",
        )

    async def callback(self, interaction: discord.Interaction):
        ph = self.placeholder
        if "アイテム" in ph:   self.parent_view.sel1 = self.values
        elif "キャラ" in ph:   self.parent_view.sel2 = self.values
        elif "ステージ" in ph: self.parent_view.sel3 = self.values
        else:                  self.parent_view.sel4 = self.values
        try: await interaction.response.edit_message()
        except: pass


class _PayConfirmView(ui.View):
    def __init__(self, editor, selected, total):
        super().__init__(timeout=180)
        self.editor   = editor
        self.selected = selected
        self.total    = total

        # 合計0円（無料）の場合はそのままボタンを出す
        if total == 0:
            btn = ui.Button(label="無料で代行を実行する", style=discord.ButtonStyle.success, emoji="✅")
        else:
            btn = ui.Button(label=f"¥{total} PayPayで支払う", style=discord.ButtonStyle.primary, emoji="💳")
        btn.callback = self._on_confirm
        self.add_item(btn)

    async def _on_confirm(self, interaction: discord.Interaction):
        # ライセンス保持者 or 元々0円 → PayPay不要で即実行
        actual = 0 if _has_license(interaction.user.id) else self.total
        if actual == 0:
            await interaction.response.defer(ephemeral=True)
            await interaction.followup.send("無料のため決済をスキップして代行を実行しています...", ephemeral=True)
            actions = await _execute_daiko(self.editor, self.selected)
            await _send_daiko_result(interaction, self.editor, actions, 0)
        else:
            await interaction.response.send_modal(PayPayLinkModal(self.editor, self.selected, actual))


class PayPayLinkModal(ui.Modal, title="PayPay 送金リンク入力"):
    link      = ui.TextInput(label="PayPay 送金リンク", placeholder="https://pay.paypay.ne.jp/...", required=True)
    link_pass = ui.TextInput(label="パスコード（ある場合のみ）", required=False, placeholder="パスコードが設定されている場合のみ入力")

    def __init__(self, editor, selected, total):
        super().__init__(timeout=180)
        self.editor   = editor
        self.selected = selected
        self.total    = total

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # 合計0円（無料）の場合は PayPay 決済をスキップして即代行実行
        if self.total == 0:
            await interaction.followup.send("無料のため決済をスキップして代行を実行しています...", ephemeral=True)
            actions = await _execute_daiko(self.editor, self.selected)
            await _send_daiko_result(interaction, self.editor, actions, 0)
            return

        link_url = self.link.value.strip()
        passcode = self.link_pass.value.strip() or None

        link_info = await paypayu.check_link(link_url)
        if not link_info:
            return await interaction.followup.send("リンクの確認に失敗しました。", ephemeral=True)

        p2p    = link_info.get("payload", {}).get("pendingP2PInfo", {})
        amount = p2p.get("amount", 0)
        if amount != self.total:
            return await interaction.followup.send(
                f"金額が一致しません。請求: ¥{self.total} / 送金: ¥{amount}", ephemeral=True
            )

        if p2p.get("isSetPasscode") and not passcode:
            return await interaction.followup.send("パスコードが設定されています。入力してください。", ephemeral=True)

        # オーナーの PayPay 情報を取得
        pp_all = load_paypay_data()
        pp_info = pp_all.get(str(OWNER_ID)) or pp_all.get(OWNER_ID)
        if not pp_info:
            # Bot のアプリケーションオーナーでも試みる
            try:
                app_info = await interaction.client.application_info()
                pp_info  = pp_all.get(str(app_info.owner.id))
            except Exception:
                pass

        if not pp_info:
            return await interaction.followup.send(
                "Bot 管理者の PayPay アカウントが登録されていません。`/paypayログイン` を実行してください。",
                ephemeral=True,
            )

        result = await paypayu.link_rev(link_url, pp_info["phone"], pp_info["password"], pp_info["uuid"], passcode)

        if result is True:
            await interaction.followup.send("PayPay でのお支払いを確認しました。代行を実行しています...", ephemeral=True)
            actions = await _execute_daiko(self.editor, self.selected)
            await _send_daiko_result(interaction, self.editor, actions, self.total)
        elif result == "LOGINERR":
            await interaction.followup.send("PayPay ログインに失敗しました。管理者に連絡してください。", ephemeral=True)
        else:
            await interaction.followup.send("送金の受け取りに失敗しました。リンクの有効期限やパスコードを確認してください。", ephemeral=True)


# ==========================================
# 代行実行ロジック
# ==========================================

async def _execute_daiko(editor, selected: list[str]) -> list[str]:
    actions = []
    for key in selected:
        try:
            if   key == "unlock_all":     await asyncio.to_thread(editor.unlock_all_cats)
            elif key == "remove_error":   await asyncio.to_thread(editor.remove_ban_flags)
            elif key == "levels_max":     await asyncio.to_thread(editor.max_level_all_cats)
            elif key == "forms_max":      await asyncio.to_thread(editor.max_all_cats)
            elif key == "main_clear":     await asyncio.to_thread(editor.clear_all_stages)
            elif key == "talents_max":
                cats = editor.get_all_cats()
                for cat in cats:
                    if cat.unlocked: await asyncio.to_thread(cat.max_talents, 10)
            elif key == "zombie_clear":   await asyncio.to_thread(editor.clear_all_outbreaks)
            elif key == "legend_clear":   await asyncio.to_thread(editor.clear_all_zero_legends)
            elif key == "uncanny_clear":  await asyncio.to_thread(editor.clear_all_uncanny)
            elif key == "legend_quest":   await asyncio.to_thread(editor.clear_all_legend_quest)
            elif key == "ex_clear":       await asyncio.to_thread(editor.clear_all_ex_stages)
            elif key == "zero_clear":     await asyncio.to_thread(editor.clear_all_zero_legends)
            elif key == "aku_clear":      await asyncio.to_thread(editor.clear_all_aku)
            elif key == "event_clear":    await asyncio.to_thread(editor.clear_all_events)
            elif key == "gamatoto_max":   editor.gamatoto_xp = 9999999; await asyncio.to_thread(editor.max_gamatoto_helpers)
            elif key == "gamatoto_hlp":   await asyncio.to_thread(editor.max_gamatoto_helpers)
            elif key == "ototo_max":      await asyncio.to_thread(editor.max_facilities)
            elif key == "shrine_max":     editor.set_cat_shrine(30, 9999999)
            elif key == "playtime":       editor.set_play_time(99999, 0)
            elif key == "gold_member":    editor.set_gold_pass(365)
            elif key == "deck_slots":     editor.equip_slots = 50
            elif key in ("medals", "all_medals"): editor.unlock_all_medals()
            elif key == "enemy_enc":      editor.unlock_enemy_guide()
            elif key == "tutorial_skip":  editor.set_tutorial_cleared(); editor.unlock_equip_menu()
            elif key == "dojo_max":       editor.set_dojo_score(0, 999999)
            elif key in ("missions_clear", "weekly_missions"): editor.clear_all_missions()
            elif key == "rank_rewards":
                try:
                    if hasattr(editor, "user_rank_rewards") and hasattr(editor.user_rank_rewards, "rewards"):
                        for r in editor.user_rank_rewards.rewards:
                            if hasattr(r, "claimed"): r.claimed = True
                    elif hasattr(editor, "claim_all_rank_rewards"):
                        editor.claim_all_rank_rewards()
                except Exception: pass
            elif key == "xp":            editor.xp = 999999999
            elif key == "np":            editor.np = 999999
            elif key == "catfood":       editor.catfood = 50000
            elif key == "battle_items":  editor.set_all_battle_items(999)
            elif key == "vitamins":      editor.set_all_catamins(999)
            elif key == "base_materials": editor.max_base_materials(9999)
            elif key == "catseyes":      editor.set_all_catseyes(999)
            elif key == "talent_orbs":   editor.max_all_talent_orbs()
            elif key == "rare":          editor.rare_tickets = 999; editor.normal_tickets = 29
            elif key == "platinum":      editor.platinum_tickets = 29
            elif key == "legend":        editor.legend_tickets = 29
            elif key == "event_ticket":  editor.hundred_million_ticket = 99
            elif key == "lead":          editor.leadership = 999
            elif key == "sub_medals":    editor.set_all_labyrinth_medals(99)
            else:
                actions.append(f"⚠ {ALL_OPTIONS.get(key, key)} (未実装)"); continue
            actions.append(f"✓ {ALL_OPTIONS.get(key, key)}")
        except Exception as e:
            print(f"[代行] エラー {key}: {e}")
            actions.append(f"✗ {ALL_OPTIONS.get(key, key)}")
    return actions


async def _send_daiko_result(interaction: discord.Interaction, editor, actions: list[str], paid: int):
    try:
        result = editor.issue_transfer_codes()
        if asyncio.iscoroutine(result):
            tc, pin = await result
        else:
            tc, pin = await asyncio.to_thread(editor.issue_transfer_codes)

        if tc and pin:
            embed_dm = discord.Embed(title="代行完了", description=f"お支払い金額: ¥{paid}", color=0x2ECC71)
            embed_dm.add_field(name="引き継ぎコード", value=f"`{tc}`", inline=False)
            embed_dm.add_field(name="認証コード",     value=f"`{pin}`", inline=False)
            embed_dm.add_field(name="実行内容",       value="\n".join(actions), inline=False)
            embed_dm.set_footer(text="代行が完了しました。アプリ内でコードを入力してください")
            await interaction.user.send(embed=embed_dm)
            await interaction.followup.send("DM に新しい引き継ぎコードを送信しました", ephemeral=True)

            _record_sale(interaction.user.id, paid)
            await _send_jisseki(interaction, actions, paid)
            return
    except Exception as e:
        print(f"[代行] コード発行エラー: {e}")

    await interaction.followup.send("コード発行に失敗しました。もう一度お試しください", ephemeral=True)


async def _send_jisseki(interaction: discord.Interaction, actions: list[str], paid: int):
    guild_id = interaction.guild_id or 0
    cfg_file = os.path.join(DAIKO_CFG_DIR, f"{guild_id}.json")
    if not os.path.exists(cfg_file):
        return
    cfg = _load_json(cfg_file)
    ch_id = cfg.get("jisseki_channel_id")
    if not ch_id:
        return
    ch = interaction.guild.get_channel(ch_id) if interaction.guild else None
    if not ch:
        return

    order_items = [a.replace("✓ ", "") for a in actions if a.startswith("✓")]
    embed = discord.Embed(
        title="代行実績",
        description="```\n" + "\n".join(f"・{i}" for i in order_items) + "\n```",
        color=0x00FF00,
        timestamp=datetime.datetime.now(timezone.utc),
    )
    embed.set_author(
        name=interaction.user.display_name,
        icon_url=interaction.user.avatar.url if interaction.user.avatar else None,
    )
    embed.add_field(name="合計金額", value=f"¥{paid}", inline=False)
    embed.set_footer(text="roru2026.")
    await ch.send(embed=embed)


# ==========================================
# Cog 定義
# ==========================================

class NyankoCog(commands.Cog):
    """アカウント複製＋有料代行の統合 Cog"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._panel_restored = False

    async def cog_load(self):
        """Bot 起動時に永続 View を復元（再投稿はしない）"""
        self.bot.add_view(DuplicatePanelView())
        self.bot.add_view(DaikoMenuView())

    def _dup_panel_embed(self, pd: dict = None) -> discord.Embed:
        pd = pd or _load_json(DUPLICATE_PANEL_FILE)
        dup_price = pd.get("duplicate_price", 0)
        max_price = pd.get("max_price", 0)

        desc = (
            "【アカウント複製】\n入力したアカウントをそのままの状態で好きな数だけ複製します。\n"
            f"> 単価: **{dup_price}円** / 1アカウント\n\n"
            "【最強アカウント作成】\n完全コンプリート状態にして好きな数だけ自動作成します。\n"
            f"> 単価: **{max_price}円** / 1アカウント\n\n"
            "下のボタンを選んでください。"
        )
        if dup_price > 0 or max_price > 0:
            desc += "\n\n※ PayPay 自動決済に対応しています。\n※ ボタンを押した後の画面で「作成数 × 単価」のリンクを入力してください。"

        embed = discord.Embed(title="アカウント複製 ＆ 作成ツール", description=desc, color=0x2B2D31)
        embed.set_footer(text="roru2026.")
        return embed

    # ─── /にゃんこ大戦争複製パネル ──────────────────────────────
    @app_commands.command(name="にゃんこ大戦争複製パネル", description="複製・作成パネルを設置します（許可ユーザー専用）")
    @is_allowed()
    @app_commands.describe(duplicate_price="アカウント複製の単価（円）", max_price="最強垢作成の単価（円）")
    async def setup_dup_panel(self, interaction: discord.Interaction, duplicate_price: int = 200, max_price: int = 200):
        # 旧パネルを削除
        pd = _load_json(DUPLICATE_PANEL_FILE)
        if pd:
            old_ch = self.bot.get_channel(pd.get("channel_id", 0))
            if old_ch and pd.get("message_id"):
                try:
                    old_msg = await old_ch.fetch_message(pd["message_id"])
                    await old_msg.delete()
                except Exception:
                    pass

        new_pd = {
            "channel_id":      interaction.channel.id,
            "message_id":      None,
            "owner_id":        str(interaction.user.id),
            "duplicate_price": duplicate_price,
            "max_price":       max_price,
        }
        msg = await interaction.channel.send(embed=self._dup_panel_embed(new_pd), view=DuplicatePanelView())
        new_pd["message_id"] = msg.id
        _save_json(DUPLICATE_PANEL_FILE, new_pd)

        await safe_respond(interaction, "✅ 複製パネルを設置しました。", ephemeral=True)

    # ─── /set_base ── ベースアカウント登録 ─────────────────────
    @app_commands.command(name="set_base", description="最強垢のベースアカウントを登録します（オーナー専用）")
    @is_owner()
    @app_commands.describe(transfer_code="初期垢の引き継ぎコード", confirm_code="確認コード")
    async def set_base_account(self, interaction: discord.Interaction, transfer_code: str, confirm_code: str):
        _save_json(BASE_ACCOUNT_FILE, {"transfer_code": transfer_code, "confirm_code": confirm_code})
        await safe_respond(interaction, "✅ ベースアカウントを登録しました。", ephemeral=True)

    # ─── /price_dup ── 複製パネル価格変更 ──────────────────────
    @app_commands.command(name="price_dup", description="複製・最強垢の単価を設定します（オーナー専用）")
    @is_owner()
    @app_commands.describe(duplicate_price="アカウント複製の単価（円）", max_price="最強垢作成の単価（円）")
    async def set_dup_price(self, interaction: discord.Interaction, duplicate_price: int, max_price: int):
        pd = _load_json(DUPLICATE_PANEL_FILE) or {}
        pd["duplicate_price"] = duplicate_price
        pd["max_price"]       = max_price
        _save_json(DUPLICATE_PANEL_FILE, pd)

        # パネルメッセージも更新
        ch_id  = pd.get("channel_id")
        msg_id = pd.get("message_id")
        if ch_id and msg_id:
            ch = self.bot.get_channel(ch_id)
            if ch:
                try:
                    msg = await ch.fetch_message(msg_id)
                    await msg.edit(embed=self._dup_panel_embed(pd))
                except Exception:
                    pass

        await safe_respond(interaction, f"✅ 複製: {duplicate_price}円 / 最強垢: {max_price}円 に設定しました。", ephemeral=True)

    # ─── /set_panel_log ── 複製ログチャンネル設定 ───────────────
    @app_commands.command(name="set_panel_log", description="複製・最強垢作成の実績ログチャンネルを設定します（オーナー専用）")
    @is_owner()
    @app_commands.describe(channel="ログを送信するチャンネル")
    async def set_panel_log(self, interaction: discord.Interaction, channel: discord.TextChannel):
        dc = _load_json(DAIKO_CONFIG_FILE) or {}
        dc["panel_log_channel_id"] = channel.id
        _save_json(DAIKO_CONFIG_FILE, dc)
        await safe_respond(interaction, f"✅ 複製ログを {channel.mention} に設定しました。", ephemeral=True)

    # ─── /にゃんこ代行 ── 有料代行パネル ──────────────────────
    @app_commands.command(name="にゃんこ代行", description="有料のにゃんこ大戦争代行サービス")
    @is_allowed()
    async def daiko(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("サーバー内のみ使用できます", ephemeral=True)

        gid = interaction.guild_id or 0

        def make_field(opts):
            return "\n".join(f"・{l}" for _, l in get_options_with_price(opts, gid))

        embed = discord.Embed(
            title="にゃんこ大戦争 代行自販機",
            description="カテゴリで選択 → 確定 → PayPay で支払い → 代行実行",
            color=0xF5A623,
        )
        embed.add_field(name="アイテム系",     value=f"```{make_field(G1_OPTIONS)}```", inline=False)
        embed.add_field(name="キャラ系",       value=f"```{make_field(G2_OPTIONS)}```", inline=False)
        embed.add_field(name="ステージ系",     value=f"```{make_field(G3_OPTIONS)}```", inline=False)
        embed.add_field(name="施設・その他系", value=f"```{make_field(G4_OPTIONS)}```", inline=False)
        embed.set_footer(text="代行後は新しい引き継ぎコードが DM に送られます | roru2026.")
        await interaction.response.send_message(embed=embed, view=DaikoMenuView())

    # ─── /にゃんこ実績チャンネル ────────────────────────────────
    @app_commands.command(name="にゃんこ実績チャンネル", description="代行実績を送信するチャンネルを設定します")
    @is_allowed()
    @app_commands.describe(channel="送信先のチャンネル")
    async def set_jisseki_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        guild_id = interaction.guild_id or 0
        os.makedirs(DAIKO_CFG_DIR, exist_ok=True)
        cfg_file = os.path.join(DAIKO_CFG_DIR, f"{guild_id}.json")
        cfg = _load_json(cfg_file)
        cfg["jisseki_channel_id"] = channel.id
        with open(cfg_file, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)

        embed = discord.Embed(
            title="✅ 設定完了",
            description=f"代行完了時に {channel.mention} に実績を送信します。",
            color=0x00FF00,
        )
        await safe_respond(interaction, embed=embed, ephemeral=True)

    # ─── /にゃんこ実績チャンネル解除 ────────────────────────────
    @app_commands.command(name="にゃんこ実績チャンネル解除", description="実績送信チャンネルを解除します")
    @is_allowed()
    async def unset_jisseki_channel(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id or 0
        cfg_file = os.path.join(DAIKO_CFG_DIR, f"{guild_id}.json")
        if os.path.exists(cfg_file):
            cfg = _load_json(cfg_file)
            if "jisseki_channel_id" in cfg:
                del cfg["jisseki_channel_id"]
                with open(cfg_file, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=2, ensure_ascii=False)
                return await safe_respond(interaction, "✅ 実績送信チャンネルを解除しました。", ephemeral=True)
        await safe_respond(interaction, "設定されていません。", ephemeral=True)

    # ─── /にゃんこ価格設定 ──────────────────────────────────────
    @app_commands.command(name="にゃんこ価格設定", description="各代行メニューの価格を設定します（管理者専用）")
    @is_owner()
    @app_commands.describe(item="変更するキー（例: xp, catfood, main_clear）all で全一括変更", price="新しい価格（円、0で無料）")
    async def set_price(self, interaction: discord.Interaction, item: str, price: int):
        if price < 0:
            return await safe_respond(interaction, "0以上の値を入力してください", ephemeral=True)
        gid = interaction.guild_id or 0
        if item == "all":
            _save_prices(gid, {k: price for k in ITEM_PRICES})
            embed = discord.Embed(title="✅ 価格一括変更完了", description=f"全{len(ITEM_PRICES)}項目を **¥{price}** に設定しました", color=0x2ECC71)
            return await safe_respond(interaction, embed=embed, ephemeral=True)
        if item not in ITEM_PRICES:
            keys = ", ".join(sorted(ITEM_PRICES))
            return await safe_respond(interaction, f"不明なキー: `{item}`\n\n使えるキー:\n```{keys}```\n`all` で一括変更も可", ephemeral=True)
        prices = _load_prices(gid)
        old = prices.get(item, ITEM_PRICES[item])
        prices[item] = price
        _save_prices(gid, prices)
        embed = discord.Embed(title="✅ 価格変更完了", description=f"**{ALL_OPTIONS.get(item, item)}**\n¥{old} → ¥{price}", color=0x2ECC71)
        await safe_respond(interaction, embed=embed, ephemeral=True)

    # ─── /にゃんこ価格一覧 ──────────────────────────────────────
    @app_commands.command(name="にゃんこ価格一覧", description="現在の代行メニュー価格一覧を表示します")
    @is_allowed()
    async def list_prices(self, interaction: discord.Interaction):
        gid    = interaction.guild_id or 0
        prices = _load_prices(gid)

        def block(opts):
            return "\n".join(f"{ALL_OPTIONS.get(v,v)}: ¥{prices.get(v, ITEM_PRICES.get(v,0))}" for v, _ in opts)

        embed = discord.Embed(title="💴 代行メニュー価格一覧", color=0x3498DB)
        embed.add_field(name="アイテム系",   value=f"```{block(G1_OPTIONS)}```", inline=False)
        embed.add_field(name="キャラ系",     value=f"```{block(G2_OPTIONS)}```", inline=False)
        embed.add_field(name="ステージ系",   value=f"```{block(G3_OPTIONS)}```", inline=False)
        embed.add_field(name="施設・その他", value=f"```{block(G4_OPTIONS)}```", inline=False)
        embed.set_footer(text="roru2026.")
        await safe_respond(interaction, embed=embed, ephemeral=True)

    # ─── /にゃんこ売上 ──────────────────────────────────────────
    @app_commands.command(name="にゃんこ売上", description="代行サービスの売上を確認します（管理者専用）")
    @is_owner()
    async def show_sales(self, interaction: discord.Interaction):
        data   = _load_sales()
        total  = data.get("total", 0)
        users  = data.get("users", {})
        sorted_u = sorted(users.items(), key=lambda x: x[1], reverse=True)
        medals   = ["🥇", "🥈", "🥉"]
        lines = [
            f"{medals[i] if i < 3 else f'**{i+1}位**'} <@{uid}>: ¥{amt}"
            for i, (uid, amt) in enumerate(sorted_u[:15])
        ]
        desc = "\n".join(lines) if lines else "まだ売上データがありません"
        desc += f"\n\n{'='*20}\n💰 **売上合計: ¥{total}**"
        embed = discord.Embed(title="🏆 売上ランキング", description=desc, color=0xF1C40F)
        embed.set_footer(text="roru2026.")
        await safe_respond(interaction, embed=embed, ephemeral=True)

    # ─── /にゃんこ売上リセット ──────────────────────────────────
    @app_commands.command(name="にゃんこ売上リセット", description="売上データをリセットします（オーナー専用・取消不可）")
    @is_owner()
    async def reset_sales(self, interaction: discord.Interaction):
        with open(SALES_FILE, "w", encoding="utf-8") as f:
            json.dump({"total": 0, "users": {}}, f)
        await safe_respond(interaction, "✅ 売上データをリセットしました。", ephemeral=True)

    # ─── /にゃんこ無料付与 ──────────────────────────────────────
    @app_commands.command(name="にゃんこ無料付与", description="指定ユーザーを無料枠に設定します（オーナー専用）")
    @is_owner()
    @app_commands.describe(user="対象ユーザー", days="有効日数（0で永久、-1で解除）")
    async def grant_free(self, interaction: discord.Interaction, user: discord.Member, days: int = 30):
        data = _load_licenses()
        uid  = str(user.id)
        if days == -1:
            data.pop(uid, None)
            _save_licenses(data)
            return await safe_respond(interaction, f"✅ {user.mention} の無料ライセンスを解除しました。", ephemeral=True)
        expiry = -1 if days == 0 else int(time.time()) + days * 86400
        data[uid] = expiry
        _save_licenses(data)
        text = "永久" if days == 0 else f"{days}日間"
        embed = discord.Embed(title="✅ 無料ライセンス付与", description=f"{user.mention} に **{text}** の無料枠を付与しました", color=0x2ECC71)
        await safe_respond(interaction, embed=embed, ephemeral=True)

    # ─── /にゃんこライセンス一覧 ────────────────────────────────
    @app_commands.command(name="にゃんこライセンス一覧", description="無料枠ユーザーの一覧を表示します（オーナー専用）")
    @is_owner()
    async def list_licenses(self, interaction: discord.Interaction):
        data = _load_licenses()
        now  = time.time()
        lines = []
        for uid, expiry in data.items():
            if expiry == -1:       status = "永久"
            elif expiry > now:     status = f"残{int((expiry-now)/86400)}日"
            else:                  status = "⚠ 期限切れ"
            lines.append(f"<@{uid}>: {status}")
        embed = discord.Embed(title="🎫 無料ライセンス一覧", description="\n".join(lines) or "登録なし", color=0x9B59B6)
        embed.set_footer(text="roru2026.")
        await safe_respond(interaction, embed=embed, ephemeral=True)

    # ─── /にゃんこ価格一括設定 ──────────────────────────────────
    @app_commands.command(name="にゃんこ価格一括設定", description="全メニューの価格を一括変更します（オーナー専用）")
    @is_owner()
    @app_commands.describe(price="全アイテムに設定する価格（円、0で全部無料）")
    async def set_all_prices(self, interaction: discord.Interaction, price: int):
        if price < 0:
            return await safe_respond(interaction, "0以上の値を入力してください", ephemeral=True)
        _save_prices(interaction.guild_id or 0, {k: price for k in ITEM_PRICES})
        embed = discord.Embed(
            title="✅ 価格一括変更完了",
            description=f"全{len(ITEM_PRICES)}項目を **¥{price}** に設定しました",
            color=0x2ECC71,
        )
        embed.set_footer(text="個別変更は /にゃんこ価格設定 を使用してください")
        await safe_respond(interaction, embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(NyankoCog(bot))
