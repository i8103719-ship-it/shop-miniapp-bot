
import asyncio
import json
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ContentType
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    WebAppInfo,
)
from dotenv import load_dotenv


# ==========================================
# Загрузка переменных окружения
# ==========================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")

# Ссылка на Mini App
WEBAPP_URL = "https://i8103719-ship-it.github.io/my-first-miniapp/"


# ==========================================
# Проверка переменных окружения
# ==========================================

if not BOT_TOKEN:
    raise ValueError("Не задан BOT_TOKEN!")

if not ADMIN_ID:
    raise ValueError("Не задан ADMIN_ID!")

ADMIN_ID = int(ADMIN_ID)


# ==========================================
# Логирование
# ==========================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


# ==========================================
# Товары магазина
# ==========================================

PRODUCTS = {
    "sneakers": {
        "name": "Кроссовки",
        "price": 5990,
    },
    "tshirt": {
        "name": "Футболка",
        "price": 1990,
    },
    "cap": {
        "name": "Кепка",
        "price": 990,
    },
    "hoodie": {
        "name": "Худи",
        "price": 3990,
    },
}


# ==========================================
# FSM: состояние оформления заказа
# ==========================================

class OrderStates(StatesGroup):
    waiting_for_contact = State()


# ==========================================
# Инициализация бота
# ==========================================

bot = Bot(token=BOT_TOKEN)

dp = Dispatcher(storage=MemoryStorage())


# ==========================================
# Клавиатура Mini App
# ==========================================

def get_webapp_keyboard():

    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="🛍 Открыть магазин",
                    web_app=WebAppInfo(url=WEBAPP_URL)
                )
            ]
        ],
        resize_keyboard=True
    )

    return keyboard


# ==========================================
# Клавиатура запроса контакта
# ==========================================

def get_contact_keyboard():

    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="📱 Отправить номер",
                    request_contact=True
                )
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

    return keyboard


# ==========================================
# Команда /start
# ==========================================

@dp.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):

    await state.clear()

    await message.answer(
        "👋 Добро пожаловать в наш магазин!\n\n"
        "🛍 Нажмите кнопку ниже, чтобы открыть каталог товаров.",
        reply_markup=get_webapp_keyboard()
    )


# ==========================================
# Получение данных из Mini App
# ==========================================

@dp.message(F.content_type == ContentType.WEB_APP_DATA)
async def webapp_data_handler(message: Message, state: FSMContext):

    try:
        # Получаем JSON из Mini App
        data = json.loads(message.web_app_data.data)

        product_id = data.get("id")

        # Проверяем товар по серверному каталогу
        product = PRODUCTS.get(product_id)

        if not product:
            await message.answer(
                "❌ Такого товара нет в каталоге.",
                reply_markup=get_webapp_keyboard()
            )
            return

        # Сохраняем товар в FSM
        await state.set_state(OrderStates.waiting_for_contact)

        await state.update_data(
            product_id=product_id,
            product_name=product["name"],
            product_price=product["price"]
        )

        # Запрашиваем номер телефона
        await message.answer(
            f"🛍 Вы выбрали: <b>{product['name']}</b>\n"
            f"💰 Цена: <b>{product['price']} ₽</b>\n\n"
            "📱 Для оформления заказа отправьте свой номер телефона.",
            reply_markup=get_contact_keyboard(),
            parse_mode="HTML"
        )

    except (json.JSONDecodeError, AttributeError, TypeError):
        logger.exception("Ошибка обработки данных Mini App")

        await message.answer(
            "❌ Не удалось обработать выбранный товар. Попробуйте снова.",
            reply_markup=get_webapp_keyboard()
        )


# ==========================================
# Получение контакта пользователя
# ==========================================

@dp.message(
    OrderStates.waiting_for_contact,
    F.contact
)
async def contact_handler(message: Message, state: FSMContext):

    contact = message.contact

    # Проверяем, что пользователь отправил собственный номер
    if contact.user_id != message.from_user.id:
        await message.answer(
            "⚠️ Пожалуйста, отправьте именно свой номер телефона.",
            reply_markup=get_contact_keyboard()
        )
        return

    # Получаем данные заказа
    data = await state.get_data()

    product_name = data.get("product_name")
    product_price = data.get("product_price")

    if not product_name or product_price is None:
        await state.clear()

        await message.answer(
            "❌ Информация о заказе потеряна. Оформите заказ заново.",
            reply_markup=ReplyKeyboardRemove()
        )
        return

    phone = contact.phone_number

    username = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else "Не указан"
    )

    # Формируем сообщение администратору
    admin_text = (
        "🛒 <b>НОВЫЙ ЗАКАЗ!</b>\n\n"
        f"📦 Товар: <b>{product_name}</b>\n"
        f"💰 Цена: <b>{product_price} ₽</b>\n\n"
        f"📱 Телефон: <code>{phone}</code>\n"
        f"👤 Username: {username}\n"
        f"🆔 Telegram ID: <code>{message.from_user.id}</code>"
    )

    # Отправляем заявку администратору
    try:
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_text,
            parse_mode="HTML"
        )

    except Exception:
        logger.exception("Не удалось отправить заказ администратору")

        await message.answer(
            "⚠️ Не удалось отправить заказ. Попробуйте позже.",
            reply_markup=ReplyKeyboardRemove()
        )

        await state.clear()
        return

    # Благодарим покупателя
    await message.answer(
        "🎉 <b>Спасибо за заказ!</b>\n\n"
        "Ваша заявка успешно отправлена администратору.\n"
        "Скоро с вами свяжется наш менеджер.\n\n"
        "❤️ Хорошего дня!",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML"
    )

    # Очищаем состояние FSM
    await state.clear()


# ==========================================
# Если пользователь отправил не контакт
# ==========================================

@dp.message(OrderStates.waiting_for_contact)
async def waiting_contact_handler(message: Message):

    await message.answer(
        "📱 Для продолжения оформления заказа "
        "нажмите кнопку «Отправить номер»."
    )


# ==========================================
# Запуск бота
# ==========================================

async def main():

    logger.info("Telegram Shop Bot запущен!")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
  
