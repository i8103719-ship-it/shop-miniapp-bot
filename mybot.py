import os
import json
import logging
import asyncio
from html import escape

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    WebAppInfo,
    ContentType,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode


# ==================================================
# CONFIGURATION
# ==================================================

WEBAPP_URL = "https://i8103719-ship-it.github.io/my-first-miniapp/"

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")


# ==================================================
# LOGGING
# ==================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


# ==================================================
# SERVER PRODUCTS
# Цены берутся ТОЛЬКО отсюда.
# ==================================================

PRODUCTS = {
    "sneakers": {
        "name": "VOID SNEAKERS",
        "price": 8990,
    },
    "tshirt": {
        "name": "VOID OVERSIZE TEE",
        "price": 3490,
    },
    "cap": {
        "name": "VOID BASEBALL CAP",
        "price": 2490,
    },
    "hoodie": {
        "name": "VOID HEAVY HOODIE",
        "price": 6490,
    },
}


# ==================================================
# FSM STATES
# ==================================================

class OrderStates(StatesGroup):
    waiting_for_phone = State()


# ==================================================
# KEYBOARDS
# ==================================================

def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="Открыть магазин",
                    web_app=WebAppInfo(url=WEBAPP_URL),
                )
            ]
        ],
        resize_keyboard=True,
    )


def get_phone_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="Отправить номер телефона",
                    request_contact=True,
                )
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


# ==================================================
# HELPERS
# ==================================================

def format_price(price: int) -> str:
    return f"{price:,}".replace(",", " ") + " руб."


def calculate_order(cart_data):
    """
    Проверяет входящие данные Mini App.
    Рассчитывает стоимость исключительно по PRODUCTS.
    Возвращает список товаров и общую сумму.
    """

    if not isinstance(cart_data, list):
        raise ValueError("Корзина должна быть списком.")

    if not cart_data:
        raise ValueError("Корзина пуста.")

    if len(cart_data) > len(PRODUCTS):
        raise ValueError("Слишком много позиций в корзине.")

    quantities = {}

    for item in cart_data:

        if not isinstance(item, dict):
            raise ValueError("Некорректная позиция товара.")

        product_id = item.get("id")
        quantity = item.get("quantity")

        if not isinstance(product_id, str):
            raise ValueError("Некорректный ID товара.")

        if product_id not in PRODUCTS:
            raise ValueError(f"Неизвестный товар: {product_id}")

        # bool является подклассом int в Python,
        # поэтому проверяем его отдельно.
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise ValueError("Некорректное количество товара.")

        if quantity < 1 or quantity > 50:
            raise ValueError("Количество товара должно быть от 1 до 50.")

        quantities[product_id] = quantities.get(product_id, 0) + quantity

        if quantities[product_id] > 50:
            raise ValueError("Слишком большое количество одного товара.")

    order_items = []
    total = 0

    for product_id, quantity in quantities.items():

        product = PRODUCTS[product_id]

        # Цена берётся только с сервера.
        price = product["price"]
        subtotal = price * quantity

        total += subtotal

        order_items.append({
            "id": product_id,
            "name": product["name"],
            "quantity": quantity,
            "price": price,
            "subtotal": subtotal,
        })

    return order_items, total


def create_receipt(order_items, total):
    lines = [
        "<b>VOID. — ВАШ ЗАКАЗ</b>",
        "",
        "Состав заказа:",
        "",
    ]

    for item in order_items:
        lines.append(
            f"{item['quantity']} шт. "
            f"{escape(item['name'])} — "
            f"{format_price(item['subtotal'])}"
        )

    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━",
        f"<b>ИТОГО: {format_price(total)}</b>",
    ])

    return "\n".join(lines)


# ==================================================
# BOT HANDLERS
# ==================================================

async def start_handler(message: Message, state: FSMContext):
    await state.clear()

    await message.answer(
        "<b>VOID.</b>\n\n"
        "Добро пожаловать в наш магазин.\n"
        "Выбирай вещи из новой коллекции.",
        reply_markup=get_main_keyboard(),
    )


async def cancel_handler(message: Message, state: FSMContext):
    await state.clear()

    await message.answer(
        "Оформление заказа отменено.",
        reply_markup=get_main_keyboard(),
    )


# ==================================================
# RECEIVE WEB APP DATA
# ==================================================

async def web_app_handler(message: Message, state: FSMContext):

    try:
        if not message.web_app_data:
            await message.answer(
                "Не удалось получить данные корзины.",
                reply_markup=get_main_keyboard(),
            )
            return

        raw_data = message.web_app_data.data

        logger.info(
            "Получены данные WebApp от пользователя %s",
            message.from_user.id,
        )

        # Проверяем JSON.
        try:
            data = json.loads(raw_data)
        except json.JSONDecodeError:
            await message.answer(
                "Ошибка обработки корзины. Попробуйте оформить заказ ещё раз.",
                reply_markup=get_main_keyboard(),
            )
            return

        if not isinstance(data, dict):
            raise ValueError("Некорректный формат заказа.")

        cart_data = data.get("cart")

        # Проверяем корзину и считаем стоимость на сервере.
        order_items, total = calculate_order(cart_data)

        # Формируем чек.
        receipt = create_receipt(order_items, total)

        # Сохраняем заказ в FSM.
        await state.update_data(
            order_items=order_items,
            total=total,
            receipt=receipt,
        )

        await state.set_state(OrderStates.waiting_for_phone)

        await message.answer(
            f"{receipt}\n\n"
            "<b>Остался последний шаг!</b>\n"
            "Отправьте номер телефона, чтобы мы могли "
            "связаться с вами для подтверждения заказа.",
            reply_markup=get_phone_keyboard(),
        )

    except ValueError as error:
        logger.warning(
            "Некорректный заказ от %s: %s",
            message.from_user.id,
            error,
        )

        await state.clear()

        await message.answer(
            "Не удалось обработать заказ.\n"
            "Проверьте корзину и попробуйте ещё раз.",
            reply_markup=get_main_keyboard(),
        )

    except Exception:
        logger.exception("Ошибка обработки данных Mini App")

        await message.answer(
            "Произошла ошибка при обработке заказа. "
            "Попробуйте позже.",
            reply_markup=get_main_keyboard(),
        )


# ==================================================
# RECEIVE PHONE AND SEND ORDER TO ADMIN
# ==================================================

async def phone_handler(message: Message, state: FSMContext, bot: Bot):

    contact = message.contact

    if not contact:
        await message.answer(
            "Пожалуйста, отправьте номер с помощью кнопки ниже.",
            reply_markup=get_phone_keyboard(),
        )
        return

    # Проверяем, что пользователь отправил именно свой контакт.
    if contact.user_id != message.from_user.id:
        await message.answer(
            "Пожалуйста, отправьте свой собственный номер телефона.",
            reply_markup=get_phone_keyboard(),
        )
        return

    data = await state.get_data()

    order_items = data.get("order_items")
    total = data.get("total")
    receipt = data.get("receipt")

    if not order_items or total is None or not receipt:
        await state.clear()

        await message.answer(
            "Данные заказа не найдены. Пожалуйста, оформите заказ заново.",
            reply_markup=get_main_keyboard(),
        )
        return

    user = message.from_user

    username = f"@{user.username}" if user.username else "Не указан"

    full_name = escape(user.full_name or "Не указано")
    phone = escape(contact.phone_number)
    username_safe = escape(username)

    admin_report = (
        "<b>НОВЫЙ ЗАКАЗ — VOID.</b>\n"
        "\n"
        "━━━━━━━━━━━━━━━━\n"
        "\n"
        "<b>ИНФОРМАЦИЯ О КЛИЕНТЕ</b>\n"
        f"Имя: {full_name}\n"
        f"Username: {username_safe}\n"
        f"Telegram ID: <code>{user.id}</code>\n"
        f"Телефон: <code>{phone}</code>\n"
        "\n"
        "━━━━━━━━━━━━━━━━\n"
        "\n"
        f"{receipt}\n"
        "\n"
        "━━━━━━━━━━━━━━━━"
    )

    try:
        # Отправляем отчёт администратору.
        await bot.send_message(
            chat_id=int(ADMIN_ID),
            text=admin_report,
        )

        logger.info(
            "Заказ успешно отправлен администратору. User ID: %s",
            user.id,
        )

        await message.answer(
            "<b>СПАСИБО ЗА ЗАКАЗ!</b>\n\n"
            "Ваш заказ успешно оформлен.\n"
            "Наш менеджер свяжется с вами для подтверждения.",
            reply_markup=ReplyKeyboardRemove(),
        )

        await state.clear()

    except Exception:
        logger.exception(
            "Не удалось отправить заказ администратору. User ID: %s",
            user.id,
        )

        await message.answer(
            "Не удалось передать заказ менеджеру.\n"
            "Пожалуйста, попробуйте отправить контакт ещё раз.",
            reply_markup=get_phone_keyboard(),
        )


# ==================================================
# MAIN
# ==================================================

async def main():

    if not BOT_TOKEN:
        raise RuntimeError(
            "Переменная окружения BOT_TOKEN не установлена."
        )

    if not ADMIN_ID:
        raise RuntimeError(
            "Переменная окружения ADMIN_ID не установлена."
        )

    try:
        admin_id = int(ADMIN_ID)
    except ValueError:
        raise RuntimeError("ADMIN_ID должен быть числом.")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML
        ),
    )

    dp = Dispatcher(storage=MemoryStorage())

    # Команды.
    dp.message.register(start_handler, CommandStart())
    dp.message.register(cancel_handler, Command("cancel"))

    # Данные из Telegram Mini App.
    dp.message.register(
        web_app_handler,
        F.content_type == ContentType.WEB_APP_DATA,
    )

    # Контакт пользователя.
    dp.message.register(
        phone_handler,
        OrderStates.waiting_for_phone,
        F.contact,
    )

    logger.info("VOID Bot запущен.")
    logger.info("Admin ID: %s", admin_id)
    logger.info("WebApp URL: %s", WEBAPP_URL)

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("VOID Bot остановлен.")
    except Exception:
        logger.exception("Критическая ошибка запуска бота.")
        raise
