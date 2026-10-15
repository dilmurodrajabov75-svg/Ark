"""Bosh admin va adminlar uchun boshqaruv paneli."""
import asyncio
import html
import time

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import db
import orderflow as of
from db import CATS, CHEF_TYPES, SUBS, ex, one, q, som

router = Router()
router.message.filter(F.from_user.id.func(db.is_admin))
router.callback_query.filter(F.from_user.id.func(db.is_admin))

ROLES = {"waiter": "Ofitsiantlar", "chef": "Oshpazlar", "courier": "Kuryerlar", "admin": "Adminlar"}
SETTING_NAMES = {"card": "Karta raqami", "card_owner": "Karta egasi", "km_price": "Kuryer narxi (1 km, so'm)",
                 "cashback": "Keshbek (%)", "ref_invite": "Taklif qilinadigan do'stlar soni", "ref_buyers": "Shundan xaridorlar soni",
                 "ref_min": "Minimal buyurtma (so'm)", "ayvon": "Ayvondagi stollar soni", "xona": "Alohida xonalar soni"}
MONTHS = ["Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun", "Iyul", "Avgust", "Sentyabr", "Oktyabr", "Noyabr", "Dekabr"]


class AddItem(StatesGroup):
    name = State()
    price = State()
    unit = State()
    photo = State()


class EditItem(StatesGroup):
    price = State()
    photo = State()


class AddStaff(StatesGroup):
    tg = State()
    name = State()


class EditSet(StatesGroup):
    value = State()


class Bcast(StatesGroup):
    text = State()


def kb_of(rows, back="adm:home"):
    b = InlineKeyboardBuilder()
    for text, data in rows:
        b.row(InlineKeyboardButton(text=text, callback_data=data))
    if back:
        b.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data=back))
    return b.as_markup()


@router.message(F.text == "/admin")
async def admin_cmd(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(home_text(), reply_markup=home_kb())


def home_text():
    n = one("SELECT COUNT(*) c FROM orders WHERE closed=0")["c"]
    return f"🛠 <b>Boshqaruv paneli</b>\nOchiq buyurtmalar: {n}"


def home_kb():
    return kb_of([("📋 Buyurtmalar", "adm:orders"), ("🍽 Menyu (taom, ichimlik, salat)", "adm:menu"), ("👥 Xodimlar", "adm:staff"),
                  ("🧾 To'lovlar tarixi", "adm:h:_:_:_:_:_"), ("📊 Statistika", "adm:stats"), ("💬 Sharhlar", "adm:reviews"),
                  ("📣 Mijozlarga xabar", "adm:bc"), ("⚙️ Sozlamalar", "adm:set")], back=None)


@router.callback_query(F.data == "adm:home")
async def home(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await of.show(cb, home_text(), home_kb())


# ---------- buyurtmalar ----------
@router.callback_query(F.data == "adm:orders")
async def orders(cb: CallbackQuery):
    rows = [(f"№{o['id']} · {db.place_label(o)} · {som(o['total'])}", f"adm:o:{o['id']}") for o in
            q("SELECT * FROM orders WHERE closed=0 ORDER BY id DESC LIMIT 40")]
    await of.show(cb, "📋 <b>Ochiq buyurtmalar</b>" + ("" if rows else "\nHozircha yo'q."), kb_of(rows))


@router.callback_query(F.data.startswith("adm:o:"))
async def order_view(cb: CallbackQuery):
    oid = int(cb.data.split(":")[2])
    o = one("SELECT * FROM orders WHERE id=?", (oid,))
    items = q("SELECT * FROM order_items WHERE order_id=?", (oid,))
    st = {"new": "Yangi", "cooking": "Tayyorlanmoqda", "ready": "Tayyor", "onway": "Yo'lda", "delivered": "Yetkazildi"}.get(o["status"], o["status"])
    txt = db.receipt(oid) + f"\n\nBuyurtmachi: {html.escape(o['by_name'] or '')}\nHolat: {st}\nTo'lov: {o['pay']}"
    txt += "\n" + "\n".join(f"{'✅' if i['ready'] else '⏳'} {i['name']} → {CHEF_TYPES[i['chef']]}" for i in items)
    rows = []
    if o["type"] == "hall" and not o["closed"]:
        rows.append(("💰 To'landi, hisobni yopish", f"adm:close:{oid}"))
    await of.show(cb, txt, kb_of(rows, back="adm:orders"))


@router.callback_query(F.data.startswith("adm:close:"))
async def close_order(cb: CallbackQuery):
    oid = int(cb.data.split(":")[2])
    ex("UPDATE orders SET closed=1, status='closed' WHERE id=?", (oid,))
    await cb.answer("Hisob yopildi va tarixga saqlandi")
    await orders(cb)


# ---------- menyu ----------
@router.callback_query(F.data == "adm:menu")
async def menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await of.show(cb, "🍽 <b>Menyu</b>\nBo'limni tanlang:", kb_of([(v, f"adm:mc:{k}") for k, v in CATS.items()]))


@router.callback_query(F.data.startswith("adm:mc:"))
async def menu_cat(cb: CallbackQuery):
    cat = cb.data.split(":")[2]
    await of.show(cb, f"<b>{CATS[cat]}</b>\nIchki bo'lim:", kb_of([(s, f"adm:ms:{cat}:{i}") for i, s in enumerate(SUBS[cat])], back="adm:menu"))


@router.callback_query(F.data.startswith("adm:ms:"))
async def menu_sub(cb: CallbackQuery):
    _, _, cat, i = cb.data.split(":")
    sub = SUBS[cat][int(i)]
    rows = []
    for it in q("SELECT * FROM menu WHERE cat=? AND sub=?", (cat, sub)):
        sz = db.sizes_of(it)
        rows.append((f"{'🚫 ' if it['stop'] else ''}{it['name']} · {som(min(sz.values()) if sz else it['price'])}", f"adm:mi:{it['id']}"))
    rows.append(("➕ Yangi qo'shish", f"adm:ma:{cat}:{i}"))
    await of.show(cb, f"<b>{CATS[cat]} · {sub}</b>", kb_of(rows, back=f"adm:mc:{cat}"))


@router.callback_query(F.data.startswith("adm:mi:"))
async def item_card(cb: CallbackQuery):
    it = one("SELECT * FROM menu WHERE id=?", (int(cb.data.split(":")[2]),))
    sz = db.sizes_of(it)
    price = "\n".join(f"{k}: {som(v)}" for k, v in sz.items()) if sz else f"{som(it['price'])}" + (f" / {it['unit']}" if it["unit"] else "")
    i = SUBS[it["cat"]].index(it["sub"])
    rows = [("✅ Qaytarish" if it["stop"] else "🚫 Tugadi", f"adm:mt:{it['id']}"), ("✏️ Narxini o'zgartirish", f"adm:mp:{it['id']}"),
            ("🖼 Rasmini o'zgartirish", f"adm:mf:{it['id']}"), ("🗑 O'chirish", f"adm:md:{it['id']}")]
    await of.show(cb, f"<b>{it['name']}</b>\n{price}", kb_of(rows, back=f"adm:ms:{it['cat']}:{i}"), photo=it["photo"] or None)


@router.callback_query(F.data.startswith("adm:mt:"))
async def item_toggle(cb: CallbackQuery):
    iid = int(cb.data.split(":")[2])
    ex("UPDATE menu SET stop=1-stop WHERE id=?", (iid,))
    cb.data = f"adm:mi:{iid}"
    await cb.answer("Yangilandi")
    await item_card(cb)


@router.callback_query(F.data.startswith("adm:md:"))
async def item_del(cb: CallbackQuery):
    it = one("SELECT * FROM menu WHERE id=?", (int(cb.data.split(":")[2]),))
    ex("DELETE FROM menu WHERE id=?", (it["id"],))
    await cb.answer("O'chirildi")
    cb.data = f"adm:ms:{it['cat']}:{SUBS[it['cat']].index(it['sub'])}"
    await menu_sub(cb)


@router.callback_query(F.data.startswith("adm:mp:"))
async def item_price(cb: CallbackQuery, state: FSMContext):
    await state.set_state(EditItem.price)
    await state.update_data(iid=int(cb.data.split(":")[2]))
    await cb.message.answer("Yangi narxni yozing (so'm). Ichimlikda 0.5 l narxi yoziladi, boshqa hajmlar avtomatik hisoblanadi:")
    await cb.answer()


@router.message(EditItem.price, F.text)
async def item_price_set(m: Message, state: FSMContext):
    if not m.text.replace(" ", "").isdigit():
        return await m.answer("Faqat raqam yozing.")
    d = await state.get_data()
    p = int(m.text.replace(" ", ""))
    it = one("SELECT * FROM menu WHERE id=?", (d["iid"],))
    if it["sizes"]:
        import json
        r = lambda x: round(x / 500) * 500
        ex("UPDATE menu SET price=?, sizes=? WHERE id=?", (p, json.dumps({"0.5 l": p, "1 l": r(p * 1.6), "1.5 l": r(p * 2.2), "2 l": r(p * 2.7)}), it["id"]))
    else:
        ex("UPDATE menu SET price=? WHERE id=?", (p, it["id"]))
    await state.clear()
    await m.answer("✅ Narx yangilandi.", reply_markup=kb_of([], back="adm:menu"))


@router.callback_query(F.data.startswith("adm:mf:"))
async def item_photo(cb: CallbackQuery, state: FSMContext):
    await state.set_state(EditItem.photo)
    await state.update_data(iid=int(cb.data.split(":")[2]))
    await cb.message.answer("Yangi rasmni yuboring:")
    await cb.answer()


@router.message(EditItem.photo, F.photo)
async def item_photo_set(m: Message, state: FSMContext):
    d = await state.get_data()
    ex("UPDATE menu SET photo=? WHERE id=?", (m.photo[-1].file_id, d["iid"]))
    await state.clear()
    await m.answer("✅ Rasm yangilandi.", reply_markup=kb_of([], back="adm:menu"))


@router.callback_query(F.data.startswith("adm:ma:"))
async def add_item(cb: CallbackQuery, state: FSMContext):
    _, _, cat, i = cb.data.split(":")
    await state.set_state(AddItem.name)
    await state.update_data(cat=cat, sub=SUBS[cat][int(i)])
    await cb.message.answer(f"➕ {CATS[cat]} · {SUBS[cat][int(i)]}\nTaom nomini yozing:")
    await cb.answer()


@router.message(AddItem.name, F.text)
async def add_name(m: Message, state: FSMContext):
    await state.update_data(name=html.escape(m.text.strip()[:60]))
    await state.set_state(AddItem.price)
    await m.answer("Narxini yozing (so'm):")


@router.message(AddItem.price, F.text)
async def add_price(m: Message, state: FSMContext):
    if not m.text.replace(" ", "").isdigit():
        return await m.answer("Faqat raqam yozing.")
    await state.update_data(price=int(m.text.replace(" ", "")))
    await state.set_state(AddItem.unit)
    await m.answer("O'lchov birligi (masalan: 1 kg, 1 porsiya). Yo'q bo'lsa - yozing:")


@router.message(AddItem.unit, F.text)
async def add_unit(m: Message, state: FSMContext):
    await state.update_data(unit="" if m.text.strip() == "-" else html.escape(m.text.strip()[:30]))
    await state.set_state(AddItem.photo)
    await m.answer("Taom rasmini yuboring (rasm yo'q bo'lsa «-» yozing):")


@router.message(AddItem.photo)
async def add_photo(m: Message, state: FSMContext):
    d = await state.get_data()
    photo = m.photo[-1].file_id if m.photo else None
    ex("INSERT INTO menu(cat,sub,name,price,unit,photo) VALUES(?,?,?,?,?,?)", (d["cat"], d["sub"], d["name"], d["price"], d["unit"], photo))
    await state.clear()
    await m.answer(f"✅ «{d['name']}» menyuga qo'shildi.", reply_markup=kb_of([], back="adm:menu"))


# ---------- xodimlar ----------
@router.callback_query(F.data == "adm:staff")
async def staff(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await of.show(cb, "👥 <b>Xodimlar</b>", kb_of([(v, f"adm:sl:{k}") for k, v in ROLES.items()]))


@router.callback_query(F.data.startswith("adm:sl:"))
async def staff_list(cb: CallbackQuery):
    role = cb.data.split(":")[2]
    rows = []
    txt = f"<b>{ROLES[role]}</b>\n"
    for s in q("SELECT * FROM staff WHERE role=?", (role,)):
        extra = f" ({CHEF_TYPES[s['chef_type']]})" if s["chef_type"] else ""
        txt += f"• {s['name']}{extra} — <code>{s['tg_id']}</code>\n"
        rows.append((f"🗑 {s['name']}", f"adm:sd:{role}:{s['tg_id']}"))
    if role == "admin":
        txt += f"• Bosh admin — <code>{db.ADMIN_ID}</code>\n"
    rows.append(("➕ Qo'shish", f"adm:sa:{role}"))
    await of.show(cb, txt, kb_of(rows, back="adm:staff"))


@router.callback_query(F.data.startswith("adm:sd:"))
async def staff_del(cb: CallbackQuery):
    _, _, role, tg = cb.data.split(":")
    ex("DELETE FROM staff WHERE tg_id=? AND role=?", (int(tg), role))
    await cb.answer("O'chirildi")
    cb.data = f"adm:sl:{role}"
    await staff_list(cb)


@router.callback_query(F.data.startswith("adm:sa:"))
async def staff_add(cb: CallbackQuery, state: FSMContext):
    role = cb.data.split(":")[2]
    await state.set_state(AddStaff.tg)
    await state.update_data(role=role)
    await cb.message.answer("Xodimning Telegram ID raqamini yozing.\n(U avval botga /start bosgan bo'lishi kerak. ID ni @userinfobot orqali bilish mumkin.)")
    await cb.answer()


@router.message(AddStaff.tg, F.text)
async def staff_tg(m: Message, state: FSMContext):
    if not m.text.strip().isdigit():
        return await m.answer("ID faqat raqamlardan iborat bo'ladi.")
    await state.update_data(tg=int(m.text.strip()))
    await state.set_state(AddStaff.name)
    await m.answer("Ismini yozing:")


@router.message(AddStaff.name, F.text)
async def staff_name(m: Message, state: FSMContext):
    await state.update_data(name=html.escape(m.text.strip()[:50]))
    d = await state.get_data()
    if d["role"] == "chef":
        return await m.answer("Oshpazning vazifasini tanlang:", reply_markup=kb_of([(v, f"adm:sc:{k}") for k, v in CHEF_TYPES.items()], back=None))
    await save_staff(m, state, None)


@router.callback_query(F.data.startswith("adm:sc:"))
async def staff_ctype(cb: CallbackQuery, state: FSMContext):
    await save_staff(cb.message, state, cb.data.split(":")[2])
    await cb.answer()


async def save_staff(msg, state, ctype):
    d = await state.get_data()
    ex("INSERT OR REPLACE INTO staff(tg_id,role,chef_type,name) VALUES(?,?,?,?)", (d["tg"], d["role"], ctype, d["name"]))
    await state.clear()
    await msg.answer(f"✅ {d['name']} qo'shildi ({ROLES[d['role']]}). Unga /start bosishni ayting.", reply_markup=kb_of([], back="adm:staff"))


# ---------- to'lovlar tarixi ----------
def hist_where(p):
    t, y, mo, d, pl = p
    rows = q("SELECT * FROM orders WHERE closed=1 AND type=? AND ts>=? ORDER BY ts DESC", (t, int(time.time()) - 366 * 86400))
    out = []
    for o in rows:
        lt = time.localtime(o["ts"])
        if y not in ("_", "all") and lt.tm_year != int(y):
            continue
        if mo not in ("_", "all") and lt.tm_mon != int(mo):
            continue
        if d not in ("_", "all") and lt.tm_mday != int(d):
            continue
        if t == "hall" and pl not in ("_", "all"):
            if pl in ("ayvon", "xona"):
                if o["place_kind"] != pl:
                    continue
            elif f"{o['place_kind']}{o['place_no']}" != pl:
                continue
        out.append(o)
    return out


@router.callback_query(F.data.startswith("adm:h:"))
async def history(cb: CallbackQuery):
    p = cb.data.split(":")[2:]
    pre = "adm:h:"
    def link(idx, val):
        n = list(p)
        n[idx] = val
        return pre + ":".join(n)
    if p[0] == "_":
        return await of.show(cb, "🧾 <b>To'lovlar tarixi</b>\nChek turini tanlang:", kb_of([("🍽 Restoran cheklari", pre + "hall:_:_:_:_"), ("🛵 Dastavka cheklari", pre + "delivery:_:_:_:_")]))
    if p[0] == "delivery":
        p[4] = "all"
    back = "adm:h:_:_:_:_:_"
    if p[1] == "_":
        yrs = sorted({time.localtime(o["ts"]).tm_year for o in q("SELECT ts FROM orders WHERE closed=1 AND type=?", (p[0],))}, reverse=True)
        rows = [("Barcha yillar", link(1, "all"))] + [(str(y), link(1, str(y))) for y in yrs]
        return await of.show(cb, "Yilni tanlang:", kb_of(rows, back=back))
    if p[2] == "_":
        rows = [("Barcha oylar", link(2, "all"))] + [(MONTHS[i], link(2, str(i + 1))) for i in range(12)]
        return await of.show(cb, "Oyni tanlang:", kb_of(rows, back=back))
    if p[3] == "_":
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="Barcha kunlar", callback_data=link(3, "all")))
        for i in range(1, 32):
            b.button(text=str(i), callback_data=link(3, str(i)))
        b.adjust(1, 7, 7, 7, 7, 3)
        b.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data=back))
        return await of.show(cb, "Kunni tanlang:", b.as_markup())
    if p[4] == "_":
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="Umumiy (hamma xona va stol)", callback_data=link(4, "all")))
        b.row(InlineKeyboardButton(text="Barcha ayvon", callback_data=link(4, "ayvon")), InlineKeyboardButton(text="Barcha xonalar", callback_data=link(4, "xona")))
        for i in range(1, db.geti("ayvon") + 1):
            b.button(text=f"A{i}", callback_data=link(4, f"ayvon{i}"))
        for i in range(1, db.geti("xona") + 1):
            b.button(text=f"X{i}", callback_data=link(4, f"xona{i}"))
        b.adjust(1, 2, 6)
        b.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data=back))
        return await of.show(cb, "Joyni tanlang (A - ayvon stoli, X - xona):", b.as_markup())
    lst = hist_where(p)
    total = sum(o["total"] for o in lst)
    rows = [(f"№{o['id']} · {time.strftime('%d.%m %H:%M', time.localtime(o['ts']))} · {som(o['total'])}", f"adm:rc:{o['id']}") for o in lst[:40]]
    await of.show(cb, f"🧾 <b>Cheklar:</b> {len(lst)} ta · Jami: <b>{som(total)}</b>" + ("" if lst else "\nBu filtr bo'yicha chek topilmadi."), kb_of(rows, back=back))


@router.callback_query(F.data.startswith("adm:rc:"))
async def receipt_view(cb: CallbackQuery):
    oid = int(cb.data.split(":")[2])
    o = one("SELECT * FROM orders WHERE id=?", (oid,))
    await of.show(cb, db.receipt(oid) + f"\n\nBuyurtmachi: {html.escape(o['by_name'] or '')}\nTo'lov: {o['pay']}", kb_of([], back="adm:home"))


# ---------- statistika, sharhlar ----------
@router.callback_query(F.data == "adm:stats")
async def stats(cb: CallbackQuery):
    day = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
    r = one("SELECT COUNT(*) c, COALESCE(SUM(total),0) s FROM orders WHERE ts>=?", (day,))
    top = q("SELECT name, SUM(qty) n FROM order_items GROUP BY name ORDER BY n DESC LIMIT 5")
    users = one("SELECT COUNT(*) c FROM users")["c"]
    txt = f"📊 <b>Statistika</b>\nBugun: {r['c']} ta buyurtma, {som(r['s'])}\nMijozlar: {users}\n\n<b>Eng ko'p sotilganlar:</b>\n" + "\n".join(f"{i + 1}. {t['name']} — {t['n']}" for i, t in enumerate(top))
    await of.show(cb, txt, kb_of([]))


@router.callback_query(F.data == "adm:reviews")
async def reviews(cb: CallbackQuery):
    avg = one("SELECT AVG(stars) a, COUNT(*) c FROM reviews")
    txt = f"💬 <b>Sharhlar tarixi</b>\nO'rtacha baho: {avg['a'] and round(avg['a'], 1) or '–'} ({avg['c']} ta)\n\n"
    for r in q("SELECT * FROM reviews ORDER BY id DESC LIMIT 10"):
        txt += f"{'⭐' * r['stars']} {r['kind']} №{r['order_id']}\n{html.escape(r['text'] or 'matnsiz')}\n\n"
    await of.show(cb, txt, kb_of([]))


# ---------- sozlamalar, xabar ----------
@router.callback_query(F.data == "adm:set")
async def settings(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    rows = [(f"{n}: {db.get(k)}", f"adm:se:{k}") for k, n in SETTING_NAMES.items()]
    rows.append((f"Buyurtma qabul: {'ochiq ✅' if db.geti('accepting') else 'yopiq 🚫'}", "adm:acc"))
    await of.show(cb, "⚙️ <b>Sozlamalar</b>\nO'zgartirish uchun tanlang:", kb_of(rows))


@router.callback_query(F.data == "adm:acc")
async def toggle_acc(cb: CallbackQuery, state: FSMContext):
    db.put("accepting", 0 if db.geti("accepting") else 1)
    await settings(cb, state)


@router.callback_query(F.data.startswith("adm:se:"))
async def set_edit(cb: CallbackQuery, state: FSMContext):
    key = cb.data.split(":")[2]
    await state.set_state(EditSet.value)
    await state.update_data(key=key)
    await cb.message.answer(f"{SETTING_NAMES[key]}\nHozirgi qiymat: {db.get(key)}\nYangi qiymatni yozing:")
    await cb.answer()


@router.message(EditSet.value, F.text)
async def set_save(m: Message, state: FSMContext):
    d = await state.get_data()
    v = m.text.strip()
    if d["key"] not in ("card", "card_owner") and not v.replace(" ", "").isdigit():
        return await m.answer("Faqat raqam yozing.")
    db.put(d["key"], v if d["key"] in ("card", "card_owner") else v.replace(" ", ""))
    await state.clear()
    await m.answer("✅ Saqlandi.", reply_markup=kb_of([], back="adm:set"))


@router.callback_query(F.data == "adm:bc")
async def bc(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Bcast.text)
    await cb.message.answer("Barcha mijozlarga yuboriladigan xabar matnini yozing:")
    await cb.answer()


@router.message(Bcast.text, F.text)
async def bc_send(m: Message, state: FSMContext, bot: Bot):
    await state.clear()
    ok = 0
    for u in q("SELECT tg_id FROM users"):
        if await of.safe_send(bot, u["tg_id"], m.text):
            ok += 1
        await asyncio.sleep(0.05)
    await m.answer(f"✅ {ok} ta mijozga yuborildi.", reply_markup=kb_of([]))
