import asyncio
import logging
import os
import bcrypt
import openpyxl as exl
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from datetime import datetime

# Логирование
logging.basicConfig(level=logging.INFO)

# Инициализация бота
BOT_TOKEN = os.getenv("BOT_TOKEN", "7144811796:AAE3JA9JQC3jc8Qpy0bTPbMh5fZ3_ih-bDI")
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Пути к файлам
PASSWORD_FILE = "passwords.txt"
TABLES_FILE = "tables.txt"
EXCEL_FILE = "table.xlsx"

# Хранилища
user_data = {}  # {табельный номер: хеш пароля}
authenticated_users = {}  # {user_id: табельный номер}
allowed_tables = set()  # Разрешённые табельные номера

# === Загрузка данных ===
def load_allowed_tables():
    """ Загружает список разрешённых табельных номеров. """
    global allowed_tables
    try:
        if os.path.exists(TABLES_FILE):
            with open(TABLES_FILE, "r", encoding="utf-8") as file:
                allowed_tables = {line.strip() for line in file if line.strip()}
            logging.info(f"Загружено {len(allowed_tables)} разрешённых табельных номеров.")
        else:
            logging.warning(f"Файл {TABLES_FILE} не найден.")
    except Exception as e:
        logging.error(f"Ошибка загрузки {TABLES_FILE}: {e}")

def load_passwords():
    """ Загружает хешированные пароли пользователей. """
    try:
        if os.path.exists(PASSWORD_FILE):
            with open(PASSWORD_FILE, "r", encoding="utf-8") as file:
                for line in file:
                    parts = line.strip().split(":", 1)
                    if len(parts) == 2:
                        table_number, password_hash = parts
                        user_data[table_number] = password_hash.encode('utf-8')
            logging.info(f"Загружено {len(user_data)} пользователей.")
        else:
            logging.warning(f"Файл {PASSWORD_FILE} не найден.")
    except Exception as e:
        logging.error(f"Ошибка загрузки {PASSWORD_FILE}: {e}")

# === Работа с паролями ===
def save_password(table_number, password):
    """ Хеширует и сохраняет новый пароль. """
    salt = bcrypt.gensalt()
    password_hash = bcrypt.hashpw(password.encode(), salt)
    with open(PASSWORD_FILE, "a", encoding="utf-8") as file:
        file.write(f"{table_number}:{password_hash.decode()}\n")
    user_data[table_number] = password_hash

def check_password(table_number, password):
    """ Проверяет, соответствует ли введённый пароль сохранённому хешу. """
    password_hash = user_data.get(table_number)
    return password_hash and bcrypt.checkpw(password.encode(), password_hash)

# Загрузка данных при запуске
load_allowed_tables()
load_passwords()

# === Состояния FSM ===
class AuthState(StatesGroup):
    waiting_for_table = State()
    waiting_for_password = State()

# === Обработчики команд ===
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    """ Запрос табельного номера при старте. """
    await state.clear()
    await state.set_state(AuthState.waiting_for_table)
    await message.answer("Введите свой табельный номер, чтобы начать:")

@dp.message(AuthState.waiting_for_table, F.text)
async def process_table_number(message: types.Message, state: FSMContext):
    """ Проверка введённого табельного номера. """
    table_number = message.text.strip()

    if table_number not in allowed_tables:
        await message.answer("Ошибка: этот табельный номер не разрешён.")
        return

    await state.update_data(table_number=table_number)

    if table_number in user_data:
        await state.set_state(AuthState.waiting_for_password)
        await message.answer("Введите пароль для входа:")
    else:
        await state.set_state(AuthState.waiting_for_password)
        await message.answer("Этот табельный номер не зарегистрирован. Введите новый пароль для регистрации:")

@dp.message(AuthState.waiting_for_password, F.text)
async def process_password(message: types.Message, state: FSMContext):
    """ Обработка пароля пользователя. """
    user_state = await state.get_data()
    table_number = user_state.get("table_number")
    password = message.text.strip()

    if not table_number:
        await message.answer("Ошибка: табельный номер не найден. Попробуйте снова через /start.")
        await state.clear()
        return

    if table_number not in user_data:
        save_password(table_number, password)
        authenticated_users[message.from_user.id] = table_number
        await state.clear()
        await message.answer("✅ Регистрация успешна! Вы вошли в систему.\nТеперь используйте команды: /table для получения табеля или /logout для выхода.")
    elif check_password(table_number, password):
        authenticated_users[message.from_user.id] = table_number
        await state.clear()
        await message.answer("✅ Аутентификация успешна!\nТеперь используйте команды: /table для получения табеля или /logout для выхода.")
    else:
        await message.answer("❌ Неверный пароль. Попробуйте снова.")

@dp.message(Command("table"))
async def cmd_table(message: types.Message):
    """ Обрабатывает запрос табеля. """
    user_id = message.from_user.id

    if user_id in authenticated_users:
        table_number = authenticated_users[user_id]
        await get_timesheet(message, table_number)
    else:
        await message.answer("Пожалуйста, войдите в систему с помощью /start.")

@dp.message(Command("logout"))
async def cmd_logout(message: types.Message):
    """ Выход из системы. """
    user_id = message.from_user.id

    if user_id in authenticated_users:
        del authenticated_users[user_id]
        await message.answer("Вы вышли из системы. Введите /start для повторного входа.")
    else:
        await message.answer("Вы не авторизованы. Введите /start для входа.")

async def get_timesheet(message: types.Message, table_number: str):
    """ Отправляет табель пользователю. """
    try:
        wb = exl.load_workbook(EXCEL_FILE, data_only=True)
        sheet = wb['Sheet1']
        column_c_dict = {str(cell.value).strip(): cell.row for cell in sheet["C"] if cell.value is not None}
        row_number = column_c_dict.get(table_number)

        if row_number:
            values = [cell.value for cell in sheet[row_number]]
            headers = [cell.value.strftime("%d %b") if isinstance(cell.value, datetime) else cell.value for cell in sheet[4]]
            table_data = "\n".join(f"{header}: {value}" for header, value in zip(headers, values))
            await message.reply(f"📊 Ваш табель:\n\n{table_data}", parse_mode="Markdown")
        else:
            await message.answer("❌ Ваш табельный номер не найден в таблице.")
    except Exception as e:
        logging.error(f"Ошибка при чтении файла Excel: {e}")
        await message.answer("⚠ Ошибка при обработке запроса табеля.")

async def main():
    """ Запуск бота. """
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())