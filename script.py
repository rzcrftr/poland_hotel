import asyncio
import aiomysql
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.markdown import hbold
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import random
import string

# Конфігурація
TOKEN = "7899813626:AAHYsm0XFlnwMsa8-hTjzSeHOqA5_l9ejCY"
ADMIN_ID = 581841350  # ID адміністратора
GROUP_CHAT_ID = -1002430145426 # Замініть на ID вашого групового чату
DB_CONFIG = {
    "host": "minecraft.testhost.co.ua",
    "user": "admin",
    "password": "qawsed1472005",
    "db": "employee",
    "autocommit": True,
    "auth_plugin": "mysql_native_password"
}

bot = Bot(token=TOKEN)
dp = Dispatcher()

async def create_db_pool():
    return await aiomysql.create_pool(**DB_CONFIG)

db_pool = None

async def init_db():
    global db_pool
    db_pool = await create_db_pool()
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS workers (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name TEXT,
                    room_number TEXT,
                    unique_code VARCHAR(20) UNIQUE,
                    role TEXT,
                    chat_id BIGINT DEFAULT NULL
                )
            """)

# Функція для генерації унікального коду
async def generate_unique_code():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))

# --- FSM стани ---

# Стан для додавання працівника (адміністратор)
class AddWorkerState(StatesGroup):
    waiting_for_name = State()

# Стан для призначення кімнати (адміністратор)
class AssignRoomState(StatesGroup):
    waiting_for_worker_code = State()
    waiting_for_room_number = State()

# --- Обробники команд ---

# Команда /start – для адміністратора та співробітників
@dp.message(Command("start"))
async def start_handler(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="Додати працівника")],
                [KeyboardButton(text="Призначити кімнати")],
                [KeyboardButton(text="Переглянути працівників")]
            ],
            resize_keyboard=True
        )
    else:
        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Завершити роботу")]],
            resize_keyboard=True
        )
    await message.answer("Ласкаво просимо!", reply_markup=keyboard)

# --- Додавання працівника (адміністратор) ---

@dp.message(lambda message: message.text == "Додати працівника" and message.from_user.id == ADMIN_ID)
async def add_worker(message: types.Message, state: FSMContext):
    await message.answer("Введіть ім'я працівника:")
    await state.set_state(AddWorkerState.waiting_for_name)

@dp.message(AddWorkerState.waiting_for_name)
async def get_worker_name(message: types.Message, state: FSMContext):
    code = await generate_unique_code()
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO workers (name, unique_code, role) VALUES (%s, %s, %s)",
                (message.text, code, "worker")
            )
    await message.answer(f"Працівник {hbold(message.text)} доданий!\nУнікальний код: {hbold(code)}")
    await state.clear()

# --- Призначення кімнати (адміністратор) через FSM ---

@dp.message(lambda message: message.text == "Призначити кімнати" and message.from_user.id == ADMIN_ID)
async def assign_room_start(message: types.Message, state: FSMContext):
    await message.answer("Введіть унікальний код працівника (лише код, без додаткового тексту):")
    await state.set_state(AssignRoomState.waiting_for_worker_code)

@dp.message(AssignRoomState.waiting_for_worker_code)
async def assign_room_get_code(message: types.Message, state: FSMContext):
    worker_code = message.text.strip()
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id, name, chat_id FROM workers WHERE unique_code = %s", (worker_code,))
            worker = await cur.fetchone()
    if worker:
        await state.update_data(worker_code=worker_code, worker_name=worker[1], chat_id=worker[2])
        await message.answer(f"Працівник {worker[1]} знайдений.\nВведіть номер кімнати (наприклад, 101):")
        await state.set_state(AssignRoomState.waiting_for_room_number)
    else:
        await message.answer("Працівника з таким кодом не знайдено. Спробуйте ще раз або відправте /cancel для скасування.")

@dp.message(AssignRoomState.waiting_for_room_number)
async def assign_room_get_number(message: types.Message, state: FSMContext):
    room_number = message.text.strip()
    data = await state.get_data()
    worker_code = data.get('worker_code')
    worker_name = data.get('worker_name')
    worker_chat_id = data.get('chat_id')
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("UPDATE workers SET room_number = %s WHERE unique_code = %s", (room_number, worker_code))
    # Надсилання повідомлення адміністратору та груповому чату
    await message.answer(f"Кімната {room_number} призначена працівнику {worker_name}.")
    await bot.send_message(ADMIN_ID, f"Працівнику {worker_name} назначено кімнату {room_number}.")
    await bot.send_message(GROUP_CHAT_ID, f"Працівнику {worker_name} назначено кімнату {room_number}.")
    # Надсилання повідомлення співробітнику, якщо chat_id встановлено
    if worker_chat_id:
        try:
            await bot.send_message(worker_chat_id, f"Вам призначена кімната {room_number}.")
        except Exception as e:
            await message.answer(f"Не вдалося надіслати повідомлення співробітнику: {e}")
    else:
        await message.answer("Співробітник ще не зареєстрований у боті – повідомлення не надіслано.")
    await state.clear()

# --- Перегляд працівників (адміністратор) ---

@dp.message(lambda message: message.text == "Переглянути працівників" and message.from_user.id == ADMIN_ID)
async def view_workers(message: types.Message):
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT name, room_number, unique_code FROM workers")
            workers = await cur.fetchall()
    if workers:
        workers_info = "\n".join(
            [f"{worker[0]} (Код: {worker[2]}) – Кімната: {worker[1] if worker[1] else 'не призначена'}" for worker in workers]
        )
        await message.answer(f"Наявні працівники:\n{workers_info}")
    else:
        await message.answer("Немає працівників у базі даних.")

# --- Завершення роботи (співробітник) ---

@dp.message(lambda message: message.text == "Завершити роботу")
async def finish_work(message: types.Message):
    await message.answer("Ваша робота завершена. Дякуємо за виконання завдання!")
    await bot.send_message(ADMIN_ID, f"Працівник {message.from_user.full_name} завершив свою роботу.")
    await bot.send_message(GROUP_CHAT_ID, f"Працівник {message.from_user.full_name} завершив свою роботу.")

# --- Реєстрація співробітника (оновлення chat_id) ---
@dp.message(lambda message: message.from_user.id != ADMIN_ID and len(message.text.strip()) == 6)
async def register_worker_chat_id(message: types.Message):
    worker_code = message.text.strip()
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id FROM workers WHERE unique_code = %s", (worker_code,))
            worker = await cur.fetchone()
            if worker:
                await cur.execute("UPDATE workers SET chat_id = %s WHERE unique_code = %s", (message.from_user.id, worker_code))
                await message.answer("Ви успішно зареєстровані у боті!")
            else:
                await message.answer("Працівник з таким кодом не знайдений.")

# --- Обробник /cancel для скасування поточного стану ---
@dp.message(Command("cancel"))
async def cancel_handler(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state:
        await state.clear()
        await message.answer("Операцію скасовано.")
    else:
        await message.answer("Нічого не скасовувати.")

# --- Запуск бота ---
async def main():
    await init_db()
    dp.startup.register(init_db)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
