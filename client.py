"""Mijoz: ro'yxatdan o'tish, bosh menyu, do'st taklif qilish, baholash."""
import asyncio
import time

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, KeyboardButton, Message, ReplyKeyboardMarkup,
                           ReplyKeyboardRemove)
from aiogram.utils.keyboard import InlineKeyboardBuilder

import db
import orderflow as of
from db import ex, one, q, som

router = Router()


class Reg(StatesGroup):
    name = State()
    surname = State()
    phone = State()
    photo = State()


def main_menu():
    b = InlineKeyboardBuilder()
    b.button(text="🍽 Restoranda o'tiraman", callback_data="mode:hall")
    b.button(text="🛵 Uyga dastavka kerak", callback_data="mode:delivery")
    b.button(text="👥 Do'st taklif qilish", callback_data="ref")
    b.adjust(1)
    return b.as_markup()


@router.message(CommandStart())
async def start(m: Message, state: FSMContext, command: CommandObject, bot: Bot):
    await state.clear()
    tg = m.from_user.id
    role = db.role_of(tg)
    if role == "admin":
        b = InlineKeyboardBuilder()
        b.button(text="🛠 Boshqaruv paneli", callback_data="adm:home")
        return await m.answer("Assalomu alaykum, admin! Boshqaruv panelini oching:", reply_markup=b.as_markup())
    if role == "waiter":
        b = InlineKeyboardBuilder()
        b.button(text="🆕 Yangi buyurtma olish", callback_data="wnew")
        return await m.answer("Assalomu alaykum! Stol yoki xonadan buyurtma olish uchun bosing:", reply_markup=b.as_markup())
    if role == "chef":
        return await m.answer("Assalomu alaykum! Sizning toifangizdagi buyurtmalar shu yerga keladi. Tayyor bo'lgach ✅ tugmasini bosing.")
    if role == "courier":
        return await m.answer("Assalomu alaykum! Dastavka buyurtmalari shu yerga keladi.")
    if command.args and command.args.isdigit() and int(command.args) != tg:
        if not one("SELECT 1 FROM users WHERE tg_id=?", (tg,)) and not one("SELECT 1 FROM referrals WHERE invited=?", (tg,)):
            ex("INSERT INTO referrals(inviter, invited) VALUES(?,?)", (int(command.args), tg))
    if one("SELECT 1 FROM users WHERE tg_id=?", (tg,)):
        return await m.answer("Siz taomga buyurtma bermoqchimisiz?", reply_markup=main_menu())
    await state.set_state(Reg.name)
    await m.answer("Assalomu alaykum! Dasturxon restoraniga xush kelibsiz.\nRo'yxatdan o'tish uchun ismingizni yozing:")


@router.message(Reg.name, F.text)
async def reg_name(m: Message, state: FSMContext):
    await state.update_data(name=m.text.strip()[:40])
    await state.set_state(Reg.surname)
    await m.answer("Familiyangizni yozing:")


@router.message(Reg.surname, F.text)
async def reg_surname(m: Message, state: FSMContext):
    await state.update_data(surname=m.text.strip()[:40])
    await state.set_state(Reg.phone)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Raqamni yuborish", request_contact=True)]], resize_keyboard=True, one_time_keyboard=True)
    await m.answer("Telefon raqamingizni yuboring (tugma yoki qo'lda yozing):", reply_markup=kb)


@router.message(Reg.phone)
async def reg_phone(m: Message, state: FSMContext):
    phone = m.contact.phone_number if m.contact else (m.text or "").strip()
    if sum(c.isdigit() for c in phone) < 9:
        return await m.answer("Telefon raqam noto'g'ri. Qayta kiriting:")
    await state.update_data(phone=phone)
    await state.set_state(Reg.photo)
    b = InlineKeyboardBuilder()
    b.button(text="O'tkazib yuborish", callback_data="regskip")
    await m.answer("Rasmingizni yuboring:", reply_markup=ReplyKeyboardRemove())
    await m.answer("Rasm ixtiyoriy.", reply_markup=b.as_markup())


async def save_user(tg, state: FSMContext, photo=None):
    d = await state.get_data()
    ex("INSERT OR REPLACE INTO users(tg_id,name,surname,phone,photo,ref_by,created) VALUES(?,?,?,?,?,?,?)",
       (tg, d["name"], d["surname"], d["phone"], photo, None, int(time.time())))
    await state.clear()


@router.message(Reg.photo, F.photo)
async def reg_photo(m: Message, state: FSMContext):
    await save_user(m.from_user.id, state, m.photo[-1].file_id)
    await m.answer("✅ Ro'yxatdan o'tdingiz!\n\nSiz taomga buyurtma bermoqchimisiz?", reply_markup=main_menu())


@router.callback_query(F.data == "regskip")
async def reg_skip(cb: CallbackQuery, state: FSMContext):
    await save_user(cb.from_user.id, state)
    await cb.message.edit_text("✅ Ro'yxatdan o'tdingiz!")
    await cb.message.answer("Siz taomga buyurtma bermoqchimisiz?", reply_markup=main_menu())


@router.callback_query(F.data == "mode:hall")
async def mode_hall(cb: CallbackQuery, state: FSMContext):
    if not db.geti("accepting"):
        return await cb.answer("Hozir buyurtma qabul qilinmaydi.", show_alert=True)
    await of.save_ctx(state, of.new_ctx("hall"))
    await cb.message.edit_text("Restoranda qayerda o'tirgansiz?", reply_markup=of.place_kb_kinds())


@router.callback_query(F.data == "mode:delivery")
async def mode_delivery(cb: CallbackQuery, state: FSMContext):
    if not db.geti("accepting"):
        return await cb.answer("Hozir buyurtma qabul qilinmaydi.", show_alert=True)
    await cb.answer()
    await of.ask_location(cb.message, state)


@router.callback_query(F.data == "ref")
async def ref(cb: CallbackQuery, bot: Bot):
    tg = cb.from_user.id
    r = one("SELECT COUNT(*) c, COALESCE(SUM(bought),0) b FROM referrals WHERE inviter=?", (tg,))
    me = await bot.get_me()
    await cb.message.answer(
        f"👥 <b>Do'st taklif qilish</b>\n{db.geti('ref_invite')} ta do'stingizni taklif qiling. Ulardan {db.geti('ref_buyers')} tasi kamida "
        f"{som(db.geti('ref_min'))}lik buyurtma bersa, har buyurtmangizga {db.geti('cashback')}% keshbek (chegirma) beriladi.\n\n"
        f"Taklif qilinganlar: {r['c']}/{db.geti('ref_invite')}\nXarid qilganlar: {r['b']}/{db.geti('ref_buyers')}"
        f"{chr(10) + '✅ Keshbek faol!' if db.cashback_on(tg) else ''}\n\nHavolangiz:\nhttps://t.me/{me.username}?start={tg}")
    await cb.answer()


# ---------- baholash ----------
def stars_kb(oid):
    b = InlineKeyboardBuilder()
    for i in range(1, 6):
        b.button(text="⭐" * i, callback_data=f"rt:{oid}:{i}")
    b.adjust(1)
    return b.as_markup()


@router.callback_query(F.data.startswith("rt:"))
async def rate(cb: CallbackQuery, state: FSMContext):
    _, oid, n = cb.data.split(":")
    oid, n = int(oid), int(n)
    if n == 0:
        return await cb.message.answer("Xizmatni baholang:", reply_markup=stars_kb(oid))
    await state.update_data(rate_oid=oid, rate_n=n)
    await state.set_state(of.Flow.rate_text)
    b = InlineKeyboardBuilder()
    b.button(text="Matnsiz yuborish", callback_data="rskip")
    await cb.message.edit_text(f"Bahoyingiz: {'⭐' * n}\nEndi sharh yozib qoldiring:", reply_markup=b.as_markup())


async def save_review(bot: Bot, tg, state: FSMContext, text):
    d = await state.get_data()
    oid, n = d["rate_oid"], d["rate_n"]
    o = one("SELECT * FROM orders WHERE id=?", (oid,))
    kind = "Kuryer xizmati" if o and o["type"] == "delivery" else "Restoran xizmati"
    ex("INSERT INTO reviews(order_id,tg_id,stars,text,kind,ts) VALUES(?,?,?,?,?,?)", (oid, tg, n, text, kind, int(time.time())))
    await state.clear()
    u = one("SELECT * FROM users WHERE tg_id=?", (tg,))
    name = f"{u['name']} {u['surname']}" if u else str(tg)
    for a in db.staff_ids("admin"):
        msg = await of.safe_send(bot, a, f"💬 <b>Yangi sharh</b> · {kind} · №{oid}\n{'⭐' * n}\n{name}: {text or 'matnsiz baho'}")
        if msg:
            asyncio.create_task(delete_later(bot, a, msg.message_id, 10))


async def delete_later(bot, chat, mid, sec):
    await asyncio.sleep(sec)
    try:
        await bot.delete_message(chat, mid)
    except Exception:
        pass


@router.message(of.Flow.rate_text, F.text)
async def rate_text(m: Message, state: FSMContext, bot: Bot):
    await save_review(bot, m.from_user.id, state, m.text[:500])
    await m.answer("Rahmat! Bahoyingiz qabul qilindi. 🙏", reply_markup=main_menu())


@router.callback_query(F.data == "rskip")
async def rate_skip(cb: CallbackQuery, state: FSMContext, bot: Bot):
    await save_review(bot, cb.from_user.id, state, "")
    await cb.message.edit_text("Rahmat! Bahoyingiz qabul qilindi. 🙏")
    await cb.message.answer("Yana buyurtma berasizmi?", reply_markup=main_menu())
