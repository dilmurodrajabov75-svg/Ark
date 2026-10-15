"""Ofitsiant, oshpaz va kuryer harakatlari."""
from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import db
import orderflow as of
from client import stars_kb
from db import CHEF_TYPES, ex, one, q, som

router = Router()


# ---------- Ofitsiant ----------
@router.callback_query(F.data == "wnew")
async def waiter_new(cb: CallbackQuery, state: FSMContext):
    if db.role_of(cb.from_user.id) not in ("waiter", "admin"):
        return await cb.answer("Bu funksiya ofitsiantlar uchun.", show_alert=True)
    await of.save_ctx(state, of.new_ctx("hall", waiter=True))
    await cb.answer()
    await cb.message.answer("Qaysi joydan buyurtma olasiz?", reply_markup=of.place_kb_kinds())


# ---------- Oshpaz ----------
@router.callback_query(F.data.startswith("rd:"))
async def chef_ready(cb: CallbackQuery, bot: Bot):
    _, oid, chef = cb.data.split(":")
    oid = int(oid)
    if not one("SELECT 1 FROM staff WHERE tg_id=? AND role='chef' AND chef_type=?", (cb.from_user.id, chef)):
        return await cb.answer("Bu buyurtma sizning toifangiz emas.", show_alert=True)
    ex("UPDATE order_items SET ready=1 WHERE order_id=? AND chef=?", (oid, chef))
    await cb.message.edit_text(cb.message.html_text + "\n\n✅ <b>Tayyor</b>", reply_markup=None)
    left = one("SELECT COUNT(*) c FROM order_items WHERE order_id=? AND ready=0", (oid,))["c"]
    o = one("SELECT * FROM orders WHERE id=?", (oid,))
    if left == 0:
        ex("UPDATE orders SET status='ready' WHERE id=?", (oid,))
        txt = f"✅ №{oid} buyurtmaning hammasi tayyor.\n{db.place_label(o)}"
        targets = [o["waiter_id"]] if o["waiter_id"] else db.staff_ids("admin")
        if o["type"] == "delivery":
            targets = ([o["courier_id"]] if o["courier_id"] else db.staff_ids("courier")) + db.staff_ids("admin")
        for t in set(targets):
            await of.safe_send(bot, t, txt)
    else:
        for a in db.staff_ids("admin"):
            await of.safe_send(bot, a, f"👨‍🍳 №{oid}: {CHEF_TYPES[chef]} tayyor ({left} ta taom qoldi).")
    await cb.answer("Tayyor deb belgilandi")


# ---------- Kuryer ----------
@router.callback_query(F.data.startswith("cp:"))
async def courier_pick(cb: CallbackQuery, bot: Bot):
    oid = int(cb.data.split(":")[1])
    if db.role_of(cb.from_user.id) != "courier":
        return await cb.answer("Faqat kuryerlar uchun.", show_alert=True)
    cur = db.con.execute("UPDATE orders SET courier_id=?, status='onway' WHERE id=? AND courier_id IS NULL", (cb.from_user.id, oid))
    db.con.commit()
    if cur.rowcount == 0:
        return await cb.answer("Bu buyurtmani boshqa kuryer oldi.", show_alert=True)
    o = one("SELECT * FROM orders WHERE id=?", (oid,))
    b = InlineKeyboardBuilder()
    b.button(text="📦 Buyurtma yetkazib berildi", callback_data=f"cd:{oid}")
    await cb.message.edit_reply_markup(reply_markup=b.as_markup())
    await cb.message.answer("📍 Endi mijoz sizni ko'rishi uchun <b>jonli joylashuv</b> yuboring:\n"
                            "📎 (skrepka) → Joylashuv → «Jonli joylashuvni ulashish».")
    await of.safe_send(bot, o["tg_id"], "🛵 Kuryer buyurtmangizni oldi va yo'lga chiqdi. Uning jonli joylashuvi shu yerga keladi.")
    for a in db.staff_ids("admin"):
        await of.safe_send(bot, a, f"🛵 №{oid}: kuryer buyurtmani oldi.")
    await cb.answer()


@router.message(F.location)
async def courier_location(m: Message, bot: Bot):
    o = one("SELECT * FROM orders WHERE courier_id=? AND status='onway' AND closed=0 ORDER BY id DESC", (m.from_user.id,))
    if not o or o["live_msg"]:
        return
    try:
        msg = await bot.send_location(o["tg_id"], m.location.latitude, m.location.longitude,
                                      live_period=m.location.live_period) if m.location.live_period else \
            await bot.send_location(o["tg_id"], m.location.latitude, m.location.longitude)
        ex("UPDATE orders SET live_msg=? WHERE id=?", (msg.message_id, o["id"]))
    except Exception:
        pass


@router.edited_message(F.location)
async def courier_live_update(m: Message, bot: Bot):
    o = one("SELECT * FROM orders WHERE courier_id=? AND status='onway' AND live_msg IS NOT NULL ORDER BY id DESC", (m.from_user.id,))
    if not o:
        return
    try:
        await bot.edit_message_live_location(latitude=m.location.latitude, longitude=m.location.longitude,
                                             chat_id=o["tg_id"], message_id=o["live_msg"])
    except Exception:
        pass


@router.callback_query(F.data.startswith("cd:"))
async def delivered(cb: CallbackQuery, bot: Bot):
    oid = int(cb.data.split(":")[1])
    o = one("SELECT * FROM orders WHERE id=?", (oid,))
    if not o or o["courier_id"] != cb.from_user.id:
        return await cb.answer("Bu sizning buyurtmangiz emas.", show_alert=True)
    ex("UPDATE orders SET status='delivered', closed=1 WHERE id=?", (oid,))
    if o["live_msg"]:
        try:
            await bot.stop_message_live_location(chat_id=o["tg_id"], message_id=o["live_msg"])
        except Exception:
            pass
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer("✅ Buyurtma yetkazib berildi deb belgilandi. Rahmat!")
    await of.safe_send(bot, o["tg_id"], "✅ Buyurtmangiz yetkazib berildi. Yoqimli ishtaha!\nKuryer xizmatini baholang:", reply_markup=stars_kb(oid))
    for a in db.staff_ids("admin"):
        await of.safe_send(bot, a, f"✅ №{oid} dastavka yetkazib berildi.")
    await cb.answer()
