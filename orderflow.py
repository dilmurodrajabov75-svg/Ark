"""Buyurtma oqimi: mijoz va ofitsiant uchun umumiy (menyu, savat, chek, buyurtma yaratish)."""
import asyncio
import html
import math
import time

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove)
from aiogram.utils.keyboard import InlineKeyboardBuilder

import db
from config import REST_LAT, REST_LON
from db import CATS, SUBCHEF, SUBS, CHEF_TYPES, one, q, ex, som

router = Router()
ORDER_OF_CATS = ["food", "drink", "salad"]


class Flow(StatesGroup):
    loc = State()
    addr = State()
    rate_text = State()


def new_ctx(mode, waiter=False):
    return {"mode": mode, "pk": None, "pn": None, "km": 0, "lat": None, "lon": None, "addr": "", "waiter": waiter,
            "cart": {}, "cat": "food", "view": "list", "sub": 0, "pay": None}


async def need(cb, state):
    ctx = (await state.get_data()).get("ctx")
    if not ctx:
        await cb.answer("Sessiya tugagan. /start bosing.", show_alert=True)
    return ctx


async def get_ctx(state: FSMContext):
    return (await state.get_data()).get("ctx")


async def save_ctx(state: FSMContext, ctx):
    await state.update_data(ctx=ctx)


def lines(ctx):
    return [l for l in ctx["cart"].values() if l["qty"] > 0]


def calc(ctx, tg):
    sub = sum(l["price"] * l["qty"] for l in lines(ctx))
    fee = max(1, math.ceil(ctx["km"])) * db.geti("km_price") if ctx["mode"] == "delivery" else 0
    disc = sub * db.geti("cashback") // 100 if (not ctx["waiter"] and db.cashback_on(tg)) else 0
    return sub, fee, disc, sub + fee - disc


def draft_text(ctx, tg):
    sub, fee, disc, total = calc(ctx, tg)
    place = (f"Dastavka ({ctx['km']:.1f} km)" if ctx["mode"] == "delivery"
             else (f"Ayvon, {ctx['pn']}-stol" if ctx["pk"] == "ayvon" else f"Alohida xona, {ctx['pn']}-xona"))
    out = ["🧾 <b>DASTURXON RESTORANI</b>", f"📍 {place}", "—" * 14]
    for l in lines(ctx):
        sz = f" ({l['size']})" if l["size"] else ""
        out.append(f"{l['name']}{sz}\n   {l['qty']} x {som(l['price'])} = <b>{som(l['price'] * l['qty'])}</b>")
    out += ["—" * 14, f"Taomlar: {som(sub)}"]
    if fee:
        out.append(f"Kuryer: {som(fee)}")
    if disc:
        out.append(f"Keshbek {db.get('cashback')}%: -{som(disc)}")
    out.append(f"<b>UMUMIY: {som(total)}</b>")
    return "\n".join(out)


# ---------- menyu ko'rinishlari ----------
async def show(cb: CallbackQuery, text, kb, photo=None):
    """Xabarni almashtiradi (rasm bo'lsa o'chirib qayta yuboradi)."""
    msg = cb.message
    try:
        if photo:
            await msg.delete()
            await cb.bot.send_photo(msg.chat.id, photo, caption=text, reply_markup=kb)
        elif msg.photo:
            await msg.delete()
            await cb.bot.send_message(msg.chat.id, text, reply_markup=kb)
        else:
            await msg.edit_text(text, reply_markup=kb)
    except Exception as e:
        if "not modified" not in str(e):
            await cb.bot.send_message(msg.chat.id, text, reply_markup=kb)


def list_kb(ctx):
    cat = ctx["cat"]
    subs = SUBS[cat]
    b = InlineKeyboardBuilder()
    if len(subs) > 1:
        for i, s in enumerate(subs):
            b.button(text=("• " if i == ctx["sub"] else "") + s, callback_data=f"ms:{i}")
        b.adjust(2)
    items = q("SELECT * FROM menu WHERE cat=? AND sub=? AND stop=0", (cat, subs[ctx["sub"]]))
    for it in items:
        sz = db.sizes_of(it)
        price = min(sz.values()) if sz else it["price"]
        label = f"{it['name']} — {'dan ' if sz else ''}{som(price)}" + (f" / {it['unit']}" if it["unit"] else "")
        b.row(InlineKeyboardButton(text=label, callback_data=f"mi:{it['id']}"))
    nxt = ORDER_OF_CATS.index(cat) + 1
    n = len(lines(ctx))
    nav = []
    if nxt < len(ORDER_OF_CATS):
        nav.append(InlineKeyboardButton(text=f"➡️ {CATS[ORDER_OF_CATS[nxt]]}", callback_data="mn"))
    nav.append(InlineKeyboardButton(text=f"🛒 Chek ({n})" if nxt < len(ORDER_OF_CATS) else f"🧾 Chekni ko'rish ({n})", callback_data="mc"))
    b.row(*nav)
    return b.as_markup()


def list_text(ctx):
    sub = SUBS[ctx["cat"]][ctx["sub"]]
    return f"<b>{CATS[ctx['cat']]}</b> · {sub}\nKerakli taomni tanlang:"


async def open_list(cb, state, ctx):
    ctx["view"] = "list"
    await save_ctx(state, ctx)
    await show(cb, list_text(ctx), list_kb(ctx))


def item_kb(ctx, it):
    sz = db.sizes_of(it)
    variants = list(sz.items()) if sz else [(it["unit"], it["price"])]
    b = InlineKeyboardBuilder()
    for si, (name, price) in enumerate(variants):
        qty = ctx["cart"].get(f"{it['id']}|{si}", {}).get("qty", 0)
        b.row(InlineKeyboardButton(text="➖", callback_data=f"mq:{it['id']}:{si}:-1"),
              InlineKeyboardButton(text=f"{name + ' · ' if name else ''}{som(price)}  [{qty}]", callback_data="noop"),
              InlineKeyboardButton(text="➕", callback_data=f"mq:{it['id']}:{si}:1"))
    b.row(InlineKeyboardButton(text="◀️ Ro'yxatga qaytish", callback_data="mb"))
    return b.as_markup()


@router.callback_query(F.data == "noop")
async def noop(cb: CallbackQuery):
    await cb.answer()


@router.callback_query(F.data.startswith("ms:"))
async def sub_pick(cb: CallbackQuery, state: FSMContext):
    ctx = await need(cb, state)
    if not ctx:
        return
    ctx["sub"] = int(cb.data.split(":")[1])
    await open_list(cb, state, ctx)


@router.callback_query(F.data.startswith("mi:"))
async def item_open(cb: CallbackQuery, state: FSMContext):
    ctx = await need(cb, state)
    if not ctx:
        return
    it = one("SELECT * FROM menu WHERE id=?", (int(cb.data.split(":")[1]),))
    ctx["view"] = f"item:{it['id']}"
    await save_ctx(state, ctx)
    cap = f"<b>{it['name']}</b>\nSonini belgilang:"
    await show(cb, cap, item_kb(ctx, it), photo=it["photo"] or None)


@router.callback_query(F.data == "mb")
async def back_list(cb: CallbackQuery, state: FSMContext):
    ctx = await need(cb, state)
    if ctx:
        await open_list(cb, state, ctx)


@router.callback_query(F.data.startswith("mq:"))
async def qty(cb: CallbackQuery, state: FSMContext):
    ctx = await need(cb, state)
    if not ctx:
        return
    _, iid, si, d = cb.data.split(":")
    iid, si, d = int(iid), int(si), int(d)
    it = one("SELECT * FROM menu WHERE id=?", (iid,))
    if not it:
        return await cb.answer("Taom topilmadi")
    sz = db.sizes_of(it)
    name, price = (list(sz.items())[si] if sz else (it["unit"], it["price"]))
    key = f"{iid}|{si}"
    l = ctx["cart"].get(key) or {"id": iid, "si": si, "name": it["name"], "size": name, "price": price, "qty": 0,
                                 "chef": SUBCHEF[it["sub"]]}
    l["qty"] = max(0, l["qty"] + d)
    ctx["cart"][key] = l
    await save_ctx(state, ctx)
    await cb.answer(f"{it['name']}: {l['qty']}")
    if ctx["view"] == "cart":
        await show_cart(cb, state, ctx, edit=True)
    else:
        try:
            await cb.message.edit_reply_markup(reply_markup=item_kb(ctx, it))
        except Exception:
            pass


@router.callback_query(F.data == "mn")
async def next_cat(cb: CallbackQuery, state: FSMContext):
    ctx = await need(cb, state)
    if not ctx:
        return
    i = ORDER_OF_CATS.index(ctx["cat"]) + 1
    if i < len(ORDER_OF_CATS):
        ctx["cat"], ctx["sub"] = ORDER_OF_CATS[i], 0
    await open_list(cb, state, ctx)


async def show_cart(cb, state, ctx, edit=False):
    ctx["view"] = "cart"
    await save_ctx(state, ctx)
    ls = lines(ctx)
    if not ls:
        b = InlineKeyboardBuilder()
        b.button(text="◀️ Menyuga qaytish", callback_data="mb")
        return await show(cb, "Savat bo'sh. Avval taom tanlang.", b.as_markup())
    b = InlineKeyboardBuilder()
    for l in ls:
        k = f"{l['id']}:{l['si']}"
        b.row(InlineKeyboardButton(text="➖", callback_data=f"mq:{k}:-1"),
              InlineKeyboardButton(text=f"{l['name']} {l['size']} × {l['qty']}"[:40], callback_data="noop"),
              InlineKeyboardButton(text="➕", callback_data=f"mq:{k}:1"))
    b.row(InlineKeyboardButton(text="➕ Yana tanlash", callback_data="mb"))
    b.row(InlineKeyboardButton(text="✅ Tasdiqlash", callback_data="mok"))
    await show(cb, draft_text(ctx, cb.from_user.id), b.as_markup())


@router.callback_query(F.data == "mc")
async def cart(cb: CallbackQuery, state: FSMContext):
    ctx = await need(cb, state)
    if ctx:
        await show_cart(cb, state, ctx)


@router.callback_query(F.data == "mok")
async def confirm(cb: CallbackQuery, state: FSMContext, bot: Bot):
    ctx = await need(cb, state)
    if not ctx:
        return
    if not lines(ctx):
        return await cb.answer("Savat bo'sh", show_alert=True)
    if not db.geti("accepting"):
        return await cb.answer("Hozir buyurtma qabul qilinmaydi.", show_alert=True)
    if ctx["mode"] == "delivery":
        b = InlineKeyboardBuilder()
        b.button(text="💵 Naqd pul (kuryerga)", callback_data="mp:Naqd")
        b.button(text="💳 Kartaga o'tkazma", callback_data="mp:Karta")
        b.adjust(1)
        return await show(cb, draft_text(ctx, cb.from_user.id) + "\n\nTo'lov usulini tanlang:", b.as_markup())
    await finish(cb, state, bot)


@router.callback_query(F.data.startswith("mp:"))
async def pay(cb: CallbackQuery, state: FSMContext, bot: Bot):
    ctx = await need(cb, state)
    if not ctx:
        return
    ctx["pay"] = cb.data.split(":")[1]
    await save_ctx(state, ctx)
    await finish(cb, state, bot)


# ---------- buyurtma yaratish ----------
async def finish(cb, state, bot):
    ctx = await need(cb, state)
    if not ctx:
        return
    tg = cb.from_user.id
    u = one("SELECT * FROM users WHERE tg_id=?", (tg,))
    by = (f"{u['name']} {u['surname']}" if u else cb.from_user.full_name)
    oid, is_extra, new_items = create_order(ctx, tg, by)
    await state.update_data(ctx=None, last_order=oid)
    await state.set_state(None)
    o = one("SELECT * FROM orders WHERE id=?", (oid,))
    b = InlineKeyboardBuilder()
    if ctx["mode"] == "hall":
        b.button(text="➕ Qo'shimcha buyurtma", callback_data=f"ex:{oid}")
        if not ctx["waiter"]:
            b.button(text="⭐ Xizmatni baholash", callback_data=f"rt:{oid}:0")
        else:
            b.button(text="🆕 Yangi stol", callback_data="wnew")
        b.adjust(1)
    text = db.receipt(oid) + ("\n\n✅ Qo'shimcha buyurtma umumiy chekka qo'shildi." if is_extra else "\n\n✅ Buyurtmangiz qabul qilindi.")
    if o["type"] == "delivery":
        text += f"\n\nTo'lov: {o['pay']}"
        if o["pay"] == "Karta":
            text += f"\n💳 <code>{db.get('card')}</code>\n{db.get('card_owner')}\nShu kartaga <b>{som(o['total'])}</b> o'tkazing."
        else:
            text += f"\n💵 Taom puli ({som(o['sub'] - o['disc'])}) kuryerga naqd to'lanadi."
    await show(cb, text, b.as_markup() if ctx["mode"] == "hall" else None)
    await notify_new(bot, oid, is_extra, new_items)
    if ctx["mode"] == "delivery":
        await bot.send_message(tg, "Kuryer buyurtmani olgach, uning jonli joylashuvi shu yerga keladi.")
    mark_referral(tg, o["sub"])


def create_order(ctx, tg, by):
    sub, fee, disc, total = calc(ctx, tg)
    ls = lines(ctx)
    now = int(time.time())
    if ctx["mode"] == "hall":
        o = one("SELECT * FROM orders WHERE type='hall' AND closed=0 AND place_kind=? AND place_no=?", (ctx["pk"], ctx["pn"]))
        if o:
            ids = [ex("INSERT INTO order_items(order_id,name,size,price,qty,chef,extra) VALUES(?,?,?,?,?,?,1)",
                      (o["id"], l["name"], l["size"], l["price"], l["qty"], l["chef"])) for l in ls]
            ex("UPDATE orders SET sub=sub+?, total=total+?, status='cooking' WHERE id=?", (sub, sub, o["id"]))
            return o["id"], True, ids
    oid = ex("""INSERT INTO orders(type,place_kind,place_no,km,addr,lat,lon,tg_id,by_name,waiter_id,status,sub,fee,disc,total,pay,ts)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
             (ctx["mode"], ctx["pk"], ctx["pn"], ctx["km"], ctx["addr"], ctx["lat"], ctx["lon"], tg, by,
              tg if ctx["waiter"] else None, "new", sub, fee, disc, total, ctx["pay"] or "Restoranda", now))
    ids = [ex("INSERT INTO order_items(order_id,name,size,price,qty,chef) VALUES(?,?,?,?,?,?)",
              (oid, l["name"], l["size"], l["price"], l["qty"], l["chef"])) for l in ls]
    return oid, False, ids


def mark_referral(tg, sub):
    r = one("SELECT * FROM referrals WHERE invited=?", (tg,))
    if r and not r["bought"] and sub >= db.geti("ref_min"):
        ex("UPDATE referrals SET bought=1 WHERE invited=?", (tg,))


async def safe_send(bot, chat, text, **kw):
    try:
        return await bot.send_message(chat, text, **kw)
    except Exception:
        return None


async def notify_new(bot: Bot, oid, is_extra, item_ids):
    o = one("SELECT * FROM orders WHERE id=?", (oid,))
    head = "➕ <b>QO'SHIMCHA BUYURTMA</b>\n" if is_extra else "🆕 <b>YANGI BUYURTMA</b>\n"
    head += f"№{oid} · {db.place_label(o)}\nKim: {html.escape(o['by_name'] or '')}\n\n"
    new = [dict(r) for r in q(f"SELECT * FROM order_items WHERE id IN ({','.join('?' * len(item_ids))})", item_ids)] if item_ids else []
    body = "\n".join(f"• {i['name']} {i['size'] or ''} × {i['qty']} = {som(i['price'] * i['qty'])}" for i in new)
    tail = f"\n\nChek jami: <b>{som(o['total'])}</b>" + (f"\nTo'lov: {o['pay']}" if o["type"] == "delivery" else "")
    for a in db.staff_ids("admin"):
        await safe_send(bot, a, head + body + tail)
        if o["type"] == "delivery" and o["lat"] is not None and not is_extra:
            try:
                await bot.send_location(a, o["lat"], o["lon"])
            except Exception:
                pass
    by_chef = {}
    for i in new:
        by_chef.setdefault(i["chef"], []).append(i)
    for chef, items in by_chef.items():
        b = InlineKeyboardBuilder()
        b.button(text="✅ Tayyor", callback_data=f"rd:{oid}:{chef}")
        txt = f"🍳 <b>{CHEF_TYPES[chef]}</b> · №{oid} · {db.place_label(o)}\n" + "\n".join(f"• {i['name']} {i['size'] or ''} × {i['qty']}" for i in items)
        targets = db.staff_ids("chef", chef)
        for t in targets:
            await safe_send(bot, t, txt, reply_markup=b.as_markup())
        if not targets:
            for a in db.staff_ids("admin"):
                await safe_send(bot, a, f"⚠️ {CHEF_TYPES[chef]} qo'shilmagan! №{oid} dagi taomlarni kim tayyorlaydi?")
    if o["type"] == "delivery" and not is_extra:
        b = InlineKeyboardBuilder()
        b.button(text="🚚 Buyurtmani oldim", callback_data=f"cp:{oid}")
        txt = (f"🛵 <b>Dastavka №{oid}</b>\n{o['km']:.1f} km · kuryer haqi {som(o['fee'])}\nManzil: {o['addr'] or '—'}\n"
               f"To'lov: {o['pay']}" + (f"\nMijozdan olinadigan taom puli: <b>{som(o['sub'] - o['disc'])}</b>" if o["pay"] == "Naqd" else ""))
        for c in db.staff_ids("courier"):
            await safe_send(bot, c, txt, reply_markup=b.as_markup())
            if o["lat"] is not None:
                try:
                    await bot.send_location(c, o["lat"], o["lon"])
                except Exception:
                    pass


@router.callback_query(F.data.startswith("ex:"))
async def extra(cb: CallbackQuery, state: FSMContext):
    o = one("SELECT * FROM orders WHERE id=?", (int(cb.data.split(":")[1]),))
    if not o or o["closed"]:
        return await cb.answer("Bu hisob yopilgan.", show_alert=True)
    w = db.role_of(cb.from_user.id) == "waiter"
    ctx = new_ctx("hall", waiter=w)
    ctx["pk"], ctx["pn"] = o["place_kind"], o["place_no"]
    await save_ctx(state, ctx)
    await cb.answer()
    await cb.message.answer(f"➕ Qo'shimcha buyurtma: {db.place_label(o)}\nUmumiy summa shu stol chekiga qo'shiladi.")
    await cb.message.answer(list_text(ctx), reply_markup=list_kb(ctx))


# ---------- joy tanlash (restoran) ----------
def place_kb_kinds():
    b = InlineKeyboardBuilder()
    b.button(text="🏞 Ayvon", callback_data="pk:ayvon")
    b.button(text="🚪 Alohida xona", callback_data="pk:xona")
    b.adjust(2)
    return b.as_markup()


@router.callback_query(F.data.startswith("pk:"))
async def place_kind(cb: CallbackQuery, state: FSMContext):
    ctx = await need(cb, state)
    if not ctx:
        return
    ctx["pk"] = cb.data.split(":")[1]
    await save_ctx(state, ctx)
    n = db.geti(ctx["pk"])
    busy = {r["place_no"] for r in q("SELECT place_no FROM orders WHERE type='hall' AND closed=0 AND place_kind=?", (ctx["pk"],))}
    b = InlineKeyboardBuilder()
    for i in range(1, n + 1):
        b.button(text=f"{i}{'•' if i in busy else ''}", callback_data=f"pn:{i}")
    b.adjust(5)
    what = f"1 dan {n} gacha stol raqami" if ctx["pk"] == "ayvon" else f"1 dan {n} gacha xona raqami"
    await cb.message.edit_text(f"Qaysi joyda o'tirgansiz? {what}ni belgilang.\n(• belgisi: ochiq hisob bor)", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("pn:"))
async def place_no(cb: CallbackQuery, state: FSMContext):
    ctx = await need(cb, state)
    if not ctx:
        return
    ctx["pn"] = int(cb.data.split(":")[1])
    await save_ctx(state, ctx)
    await cb.message.edit_text(f"✅ {'Ayvon' if ctx['pk'] == 'ayvon' else 'Xona'} {ctx['pn']} tanlandi.")
    await cb.message.answer(list_text(ctx), reply_markup=list_kb(ctx))


# ---------- dastavka: joylashuv ----------
async def ask_location(msg: Message, state: FSMContext):
    await save_ctx(state, new_ctx("delivery"))
    await state.set_state(Flow.loc)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Joylashuvni yuborish", request_location=True)]],
                             resize_keyboard=True, one_time_keyboard=True)
    await msg.answer("Yetkazib berish manzilingizni yuboring (pastdagi tugmani bosing).", reply_markup=kb)


@router.message(Flow.loc, F.location)
async def got_location(m: Message, state: FSMContext):
    ctx = await get_ctx(state)
    ctx["lat"], ctx["lon"] = m.location.latitude, m.location.longitude
    ctx["km"] = round(db.km_between(REST_LAT, REST_LON, ctx["lat"], ctx["lon"]), 1)
    await save_ctx(state, ctx)
    await state.set_state(Flow.addr)
    await m.answer(f"Masofa: {ctx['km']} km. Kuryer narxi: {som(max(1, math.ceil(ctx['km'])) * db.geti('km_price'))}.\n"
                   "Manzil izohini yozing (mahalla, uy, kvartira):", reply_markup=ReplyKeyboardRemove())


@router.message(Flow.addr, F.text)
async def got_addr(m: Message, state: FSMContext):
    ctx = await get_ctx(state)
    ctx["addr"] = m.text[:200]
    await save_ctx(state, ctx)
    await state.set_state(None)
    await m.answer(list_text(ctx), reply_markup=list_kb(ctx))
