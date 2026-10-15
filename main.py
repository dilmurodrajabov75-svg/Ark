import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

import admin
import client
import db
import orderflow
import staff
from config import BOT_TOKEN


async def main():
    logging.basicConfig(level=logging.INFO)
    if not BOT_TOKEN:
        raise SystemExit(".env faylida BOT_TOKEN yozilmagan.")
    db.init()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    # Tartib muhim: admin -> buyurtma oqimi -> mijoz -> xodimlar
    dp.include_routers(admin.router, orderflow.router, client.router, staff.router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
