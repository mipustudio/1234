#!/usr/bin/env python3
"""
🎅 Тайный Дедушка Мороз - Telegram бот для организации обмена подарками
Версия для aiogram 3.x с поддержкой переменных окружения (Bothost.ru)
"""

import asyncio
import logging
import secrets
import sqlite3
import random
import os
import html
from datetime import datetime
from typing import List, Tuple, Optional

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup,
    InlineKeyboardButton
)

# ==================== НАСТРОЙКА ЛОГГИРОВАНИЯ ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ (BOTHOST) ====================
# Получаем токен из переменных окружения Bothost
TOKEN = os.getenv('BOT_TOKEN')
if not TOKEN:
    logger.error("❌ Не найден BOT_TOKEN в переменных окружения!")
    logger.error("⚠️ Для работы бота необходимо:")
    logger.error("1. Зайти в панель Bothost")
    logger.error("2. Найти раздел 'Переменные окружения' или 'Environment Variables'")
    logger.error("3. Добавить переменную BOT_TOKEN со значением вашего токена")
    raise ValueError("Установите BOT_TOKEN в настройках Bothost")

# Дополнительные настройки из переменных окружения (опционально)
BOT_USERNAME = os.getenv('BOT_USERNAME', 'ваш_бот')  # Значение по умолчанию
ADMIN_IDS_STR = os.getenv('ADMIN_IDS', '')  # ID через запятую: "123456,789012"

# Преобразуем строку с ID администраторов в список
ADMIN_IDS = []
if ADMIN_IDS_STR:
    try:
        ADMIN_IDS = [int(id.strip()) for id in ADMIN_IDS_STR.split(',') if id.strip()]
    except ValueError:
        logger.warning(f"⚠️ Не удалось распарсить ADMIN_IDS: {ADMIN_IDS_STR}")
        ADMIN_IDS = []

# Если нужно установить ваш ID вручную в коде (раскомментируйте строку ниже):
ADMIN_IDS = [671065514]  # Ваш Telegram ID

logger.info(f"✅ Бот инициализирован. Администраторы: {ADMIN_IDS if ADMIN_IDS else 'не указаны'}")

# ==================== БАЗА ДАННЫХ ====================
class Database:
    def __init__(self, db_name='santa.db'):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.create_tables()
    
    def create_tables(self):
        cursor = self.conn.cursor()
        
        # Пользователи
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                first_name TEXT,
                last_name TEXT DEFAULT '',
                wishlist TEXT DEFAULT '',
                address TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1
            )
        ''')
        
        # Комнаты
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                owner_id INTEGER NOT NULL,
                invite_code TEXT UNIQUE NOT NULL,
                max_participants INTEGER DEFAULT 30,
                is_active BOOLEAN DEFAULT 1,
                exchange_started BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Участники комнат
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS room_participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(room_id, user_id)
            )
        ''')
        
        # Пары Тайного Дедушки Мороза
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS santa_pairs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL,
                santa_id INTEGER NOT NULL,
                recipient_id INTEGER NOT NULL,
                notified BOOLEAN DEFAULT 0
            )
        ''')
        
        # Рассылки (история)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS broadcasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                total_users INTEGER DEFAULT 0,
                sent_users INTEGER DEFAULT 0,
                failed_users INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        self.conn.commit()
        logger.info("✅ Таблицы базы данных созданы/проверены")
    
    def execute(self, query: str, params=()):
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        self.conn.commit()
        return cursor
    
    def fetchone(self, query: str, params=()):
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchone()
    
    def fetchall(self, query: str, params=()):
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()

# Глобальный объект базы данных
db = Database()

# ==================== СОСТОЯНИЯ (FSM) ====================
class UserStates(StatesGroup):
    """Состояния для пользователей"""
    editing_wishlist = State()
    editing_address = State()
    waiting_room_name = State()

class AdminStates(StatesGroup):
    """Состояния для администраторов"""
    waiting_broadcast_message = State()
    waiting_broadcast_confirmation = State()

# ==================== РОУТЕРЫ ====================
router = Router()
admin_router = Router()

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def generate_invite_code():
    """Генерирует уникальный код приглашения"""
    return secrets.token_urlsafe(8)[:8].upper()

def get_user(tg_id: int):
    """Получить пользователя по TG ID"""
    return db.fetchone("SELECT * FROM users WHERE tg_id = ?", (tg_id,))

def create_user(tg_id: int, username: str, first_name: str, last_name: str = ""):
    """Создать нового пользователя"""
    db.execute(
        "INSERT OR IGNORE INTO users (tg_id, username, first_name, last_name, is_active) VALUES (?, ?, ?, ?, ?)",
        (tg_id, username, first_name, last_name, 1)
    )
    return get_user(tg_id)

def get_room(room_id: int):
    """Получить комнату по ID"""
    return db.fetchone("SELECT * FROM rooms WHERE id = ?", (room_id,))

def get_room_by_code(invite_code: str):
    """Получить комнату по коду приглашения"""
    return db.fetchone(
        "SELECT * FROM rooms WHERE invite_code = ? AND is_active = 1",
        (invite_code,)
    )

def get_user_rooms(tg_id: int):
    """Получить все комнаты пользователя"""
    user = get_user(tg_id)
    if not user:
        return []
    
    # Комнаты где владелец
    owned = db.fetchall(
        "SELECT * FROM rooms WHERE owner_id = ? ORDER BY created_at DESC",
        (user['id'],)
    )
    
    # Комнаты где участник
    participated = db.fetchall('''
        SELECT r.* FROM rooms r
        JOIN room_participants rp ON r.id = rp.room_id
        WHERE rp.user_id = ? AND r.id NOT IN (
            SELECT id FROM rooms WHERE owner_id = ?
        )
        ORDER BY rp.joined_at DESC
    ''', (user['id'], user['id']))
    
    return list(owned) + list(participated)

def count_room_participants(room_id: int):
    """Посчитать участников комнаты"""
    result = db.fetchone(
        "SELECT COUNT(*) as count FROM room_participants WHERE room_id = ?",
        (room_id,)
    )
    return result['count'] if result else 0

def is_room_owner(tg_id: int, room_id: int):
    """Проверить, является ли пользователь владельцем комнаты"""
    user = get_user(tg_id)
    if not user:
        return False
    
    room = db.fetchone(
        "SELECT owner_id FROM rooms WHERE id = ?",
        (room_id,)
    )
    return room and room['owner_id'] == user['id']

def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь администратором"""
    return user_id in ADMIN_IDS

def get_all_users(active_only: bool = True):
    """Получить всех пользователей"""
    if active_only:
        return db.fetchall("SELECT * FROM users WHERE is_active = 1")
    else:
        return db.fetchall("SELECT * FROM users")

def count_all_users():
    """Посчитать всех пользователей"""
    result = db.fetchone("SELECT COUNT(*) as count FROM users")
    return result['count'] if result else 0

def get_user_by_id(user_id: int):
    """Получить пользователя по ID"""
    return db.fetchone("SELECT * FROM users WHERE id = ?", (user_id,))

# ==================== ОСНОВНЫЕ КОМАНДЫ ====================
@router.message(CommandStart())
async def cmd_start(message: Message):
    """Начало работы с ботом - команда /start"""
    user = message.from_user
    db_user = create_user(user.id, user.username, user.first_name, user.last_name or "")
    
    # Проверяем, есть ли параметр приглашения
    if len(message.text.split()) > 1:
        param = message.text.split()[1]
        if param.startswith('invite_'):
            invite_code = param.replace('invite_', '')
            await join_room_by_code(message, invite_code)
            return
    
    welcome_text = (
        f"🎅 Привет, {user.first_name}!\n"
        f"Я бот для организации Тайного Дедушки Мороза.\n\n"
        f"Основные команды:\n"
        f"/create_room - Создать новую комнату\n"
        f"/join - Присоединиться к комнате\n"
        f"/my_rooms - Мои комнаты\n"
        f"/profile - Настроить профиль\n"
        f"/help - Помощь\n\n"
        f"Создай комнату и пригласи друзей!"
    )
    
    await message.answer(welcome_text)

@router.message(Command("help"))
async def cmd_help(message: Message):
    """Помощь - команда /help"""
    help_text = (
        "🎄 Тайный Дедушка Мороз - Помощь\n\n"
        
        "Для всех:\n"
        "• /start - Начало работы\n"
        "• /profile - Настроить профиль (список желаний, адрес)\n"
        "• /join - Присоединиться к комнате по коду\n"
        "• /my_rooms - Мои комнаты\n"
        "• /leave_room - Покинуть комнату\n\n"
        
        "Для создания комнаты:\n"
        "• /create_room - Создать новую комнату\n"
        "• /room_info - Информация о комнате\n"
        "• /start_exchange - Начать распределение подарков\n\n"
        
        "После распределения:\n"
        "• Вы получите сообщение с именем получателя\n"
        "• Профиль получателя поможет выбрать подарок\n"
        "• Обмен подарками происходит оффлайн"
    )
    
    await message.answer(help_text)

@router.message(Command("profile"))
async def cmd_profile(message: Message):
    """Настройка профиля - команда /profile"""
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала запустите /start")
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📝 Список желаний", callback_data="edit_wishlist"),
            InlineKeyboardButton(text="🏠 Адрес", callback_data="edit_address")
        ],
        [
            InlineKeyboardButton(text="👤 Мой профиль", callback_data="view_profile")
        ]
    ])
    
    profile_text = (
        f"👤 Ваш профиль\n\n"
        f"Имя: {user['first_name']}\n"
        f"Username: @{user['username'] or 'не указан'}\n"
        f"Список желаний: {'✅' if user['wishlist'] else '❌'}\n"
        f"Адрес: {'✅' if user['address'] else '❌'}\n\n"
        f"Заполните профиль, чтобы Дедушке Морозу было проще выбрать подарок!"
    )
    
    await message.answer(profile_text, reply_markup=keyboard)

# ==================== СИСТЕМА КОМНАТ ====================
@router.message(Command("create_room"))
async def cmd_create_room(message: Message, state: FSMContext):
    """Создание новой комнаты"""
    await message.answer("Введите название для новой комнаты (до 50 символов):")
    await state.set_state(UserStates.waiting_room_name)

@router.message(UserStates.waiting_room_name)
async def process_room_name(message: Message, state: FSMContext):
    """Обработка названия комнаты"""
    room_name = message.text.strip()[:50]
    
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("Ошибка: пользователь не найден")
        await state.clear()
        return
    
    # Генерируем уникальный код
    invite_code = generate_invite_code()
    while get_room_by_code(invite_code):
        invite_code = generate_invite_code()
    
    # Создаем комнату
    db.execute(
        "INSERT INTO rooms (name, owner_id, invite_code) VALUES (?, ?, ?)",
        (room_name, user['id'], invite_code)
    )
    
    room_id = db.fetchone("SELECT last_insert_rowid() as id")['id']
    
    # Добавляем создателя как участника
    db.execute(
        "INSERT INTO room_participants (room_id, user_id) VALUES (?, ?)",
        (room_id, user['id'])
    )
    
    # Формируем ссылку
    invite_link = f"https://t.me/{BOT_USERNAME}?start=invite_{invite_code}"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🔗 Поделиться ссылкой",
                url=f"https://t.me/share/url?url={invite_link}&text=Присоединяйся к Тайному Дедушке Морозу!"
            )
        ],
        [
            InlineKeyboardButton(text="👥 Участники", callback_data=f"room_users_{room_id}"),
            InlineKeyboardButton(text="⚙️ Настройки", callback_data=f"room_settings_{room_id}")
        ]
    ])
    
    await message.answer(
        f"🎄 Комната создана!\n\n"
        f"Название: {room_name}\n"
        f"Код приглашения: {invite_code}\n"
        f"Ссылка: {invite_link}\n\n"
        f"Отправьте ссылку друзьям или дайте им код для входа через /join",
        reply_markup=keyboard
    )
    
    await state.clear()

@router.message(Command("join"))
async def cmd_join(message: Message):
    """Присоединиться к комнате"""
    args = message.text.split()
    
    if len(args) < 2:
        await message.answer(
            "Введите код комнаты:\n"
            "/join ABC12345\n\n"
            "Или перейдите по пригласительной ссылке."
        )
        return
    
    invite_code = args[1].strip().upper()
    await join_room_by_code(message, invite_code)

async def join_room_by_code(message: Message, invite_code: str):
    """Присоединиться по коду"""
    room = get_room_by_code(invite_code)
    
    if not room:
        await message.answer("❌ Комната не найдена или закрыта")
        return
    
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала запустите /start")
        return
    
    # Проверяем, не состоит ли уже в комнате
    existing = db.fetchone(
        "SELECT 1 FROM room_participants WHERE room_id = ? AND user_id = ?",
        (room['id'], user['id'])
    )
    
    if existing:
        await message.answer("✅ Вы уже в этой комнате!")
        return
    
    # Проверяем лимит участников
    participants_count = count_room_participants(room['id'])
    if participants_count >= room['max_participants']:
        await message.answer(f"❌ Комната заполнена ({room['max_participants']}/{room['max_participants']})")
        return
    
    # Проверяем, начат ли уже обмен
    if room['exchange_started']:
        await message.answer("❌ Обмен в этой комнате уже начат, нельзя присоединиться")
        return
    
    # Добавляем участника
    db.execute(
        "INSERT INTO room_participants (room_id, user_id) VALUES (?, ?)",
        (room['id'], user['id'])
    )
    
    # Получаем владельца
    owner = db.fetchone("SELECT * FROM users WHERE id = ?", (room['owner_id'],))
    
    await message.answer(
        f"✅ Вы присоединились к комнате {room['name']}!\n"
        f"Владелец: {owner['first_name']}\n"
        f"Участников: {participants_count + 1}/{room['max_participants']}\n\n"
        f"Заполните профиль через /profile чтобы Дедушке Морозу было проще выбрать подарок!"
    )
    
    # Уведомляем владельца
    if owner['tg_id'] != message.from_user.id:
        try:
            bot = message.bot
            await bot.send_message(
                owner['tg_id'],
                f"👤 Новый участник!\n"
                f"В комнате {room['name']} присоединился:\n"
                f"{message.from_user.first_name} (@{message.from_user.username or 'нет'})\n"
                f"Всего участников: {participants_count + 1}"
            )
        except:
            pass

@router.message(Command("my_rooms"))
async def cmd_my_rooms(message: Message):
    """Показать мои комнаты"""
    rooms = get_user_rooms(message.from_user.id)
    
    if not rooms:
        await message.answer(
            "У вас пока нет комнат.\n"
            "Создайте свою через /create_room\n"
            "Или присоединитесь через /join <код>"
        )
        return
    
    if len(rooms) == 1:
        await show_room_info(message, rooms[0]['id'])
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        for room in rooms:
            participants = count_room_participants(room['id'])
            emoji = "👑" if room['owner_id'] == get_user(message.from_user.id)['id'] else "👤"
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=f"{emoji} {room['name']} ({participants}/{room['max_participants']})",
                    callback_data=f"room_{room['id']}"
                )
            ])
        
        await message.answer("🎄 Ваши комнаты:", reply_markup=keyboard)

async def show_room_info(message: Message, room_id: int):
    """Показать информацию о комнате"""
    room = get_room(room_id)
    if not room:
        await message.answer("❌ Комната не найдена")
        return
    
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("Ошибка пользователя")
        return
    
    # Получаем владельца
    owner = db.fetchone("SELECT * FROM users WHERE id = ?", (room['owner_id'],))
    
    # Получаем участников
    participants = db.fetchall('''
        SELECT u.* FROM users u
        JOIN room_participants rp ON u.id = rp.user_id
        WHERE rp.room_id = ?
        ORDER BY rp.joined_at
    ''', (room_id,))
    
    participants_count = len(participants)
    
    # Формируем список участников
    participants_list = []
    for idx, p in enumerate(participants, 1):
        status = "✅" if p['wishlist'] and p['address'] else "⚠️" if p['wishlist'] or p['address'] else "❌"
        prefix = "👑" if p['id'] == room['owner_id'] else f"{idx}."
        participants_list.append(f"{prefix} {status} {p['first_name']}")
    
    participants_text = "\n".join(participants_list) if participants_list else "Нет участников"
    
    # Создаем клавиатуру
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    if user['id'] == room['owner_id']:
        # Кнопки для владельца
        if not room['exchange_started']:
            keyboard.inline_keyboard.extend([
                [
                    InlineKeyboardButton(text="🔗 Пригласить", callback_data=f"invite_{room_id}"),
                    InlineKeyboardButton(text="👥 Участники", callback_data=f"room_users_{room_id}")
                ],
                [
                    InlineKeyboardButton(text="🎁 Начать обмен", callback_data=f"start_exchange_{room_id}"),
                    InlineKeyboardButton(text="⚙️ Настройки", callback_data=f"room_settings_{room_id}")
                ]
            ])
        else:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(text="🔗 Пригласить", callback_data=f"invite_{room_id}"),
                InlineKeyboardButton(text="👥 Участники", callback_data=f"room_users_{room_id}"),
                InlineKeyboardButton(text="📊 Результаты", callback_data=f"exchange_results_{room_id}")
            ])
    else:
        # Кнопки для участника
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text="🚪 Покинуть", callback_data=f"leave_room_{room_id}"),
            InlineKeyboardButton(text="👤 Профиль", callback_data="profile")
        ])
    
    status_emoji = "🎄" if room['exchange_started'] else "🕐"
    status_text = "Обмен начат!" if room['exchange_started'] else "Ожидание начала"
    
    await message.answer(
        f"Комната: {room['name']}\n"
        f"Владелец: {'Вы' if user['id'] == room['owner_id'] else owner['first_name']}\n"
        f"Участников: {participants_count}/{room['max_participants']}\n"
        f"Статус: {status_emoji} {status_text}\n"
        f"Код: {room['invite_code']}\n\n"
        f"Участники:\n{participants_text}",
        reply_markup=keyboard
    )

# ==================== АДМИН-ПАНЕЛЬ ====================
@admin_router.message(Command("admin"))
async def cmd_admin(message: Message):
    """Панель администратора"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к админ-панели")
        return
    
    total_users = count_all_users()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📢 Создать рассылку", callback_data="admin_broadcast"),
            InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")
        ],
        [
            InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users"),
            InlineKeyboardButton(text="🏠 Комнаты", callback_data="admin_rooms")
        ]
    ])
    
    stats_text = (
        f"👑 АДМИН-ПАНЕЛЬ\n\n"
        f"📊 Статистика бота:\n"
        f"• Пользователей: {total_users}\n"
        f"• Администраторов: {len(ADMIN_IDS)}\n\n"
        f"Выберите действие:"
    )
    
    await message.answer(stats_text, reply_markup=keyboard)

@admin_router.callback_query(F.data == "admin_broadcast")
async def callback_admin_broadcast(callback: CallbackQuery, state: FSMContext):
    """Начать создание рассылки"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    
    await callback.message.answer(
        "📢 СОЗДАНИЕ РАССЫЛКИ\n\n"
        "Введите сообщение для рассылки всем пользователям.\n"
        "Можно использовать эмодзи.\n\n"
        "Чтобы отменить, отправьте /cancel"
    )
    
    await state.set_state(AdminStates.waiting_broadcast_message)
    await callback.answer()

@admin_router.message(AdminStates.waiting_broadcast_message)
async def process_broadcast_message(message: Message, state: FSMContext):
    """Обработка сообщения для рассылки"""
    if message.text == '/cancel':
        await message.answer("❌ Рассылка отменена")
        await state.clear()
        return
    
    users = get_all_users()
    total_users = len(users)
    
    if total_users == 0:
        await message.answer("❌ Нет пользователей для рассылки")
        await state.clear()
        return
    
    # Сохраняем сообщение в состоянии
    await state.update_data(broadcast_message=message.text, total_users=total_users)
    
    # Показываем предпросмотр
    preview_text = (
        f"📢 ПРЕДПРОСМОТР РАССЫЛКИ\n\n"
        f"Сообщение:\n{message.text}\n\n"
        f"📊 Статистика:\n"
        f"• Получателей: {total_users} пользователей\n\n"
        f"Начать рассылку?"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, начать", callback_data="broadcast_confirm_yes"),
            InlineKeyboardButton(text="❌ Нет, отменить", callback_data="broadcast_confirm_no")
        ]
    ])
    
    await message.answer(preview_text, reply_markup=keyboard)
    await state.set_state(AdminStates.waiting_broadcast_confirmation)

@admin_router.callback_query(F.data == "broadcast_confirm_yes")
async def callback_broadcast_confirm_yes(callback: CallbackQuery, state: FSMContext):
    """Подтверждение начала рассылки"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    
    data = await state.get_data()
    broadcast_message = data.get('broadcast_message')
    total_users = data.get('total_users', 0)
    
    if not broadcast_message or total_users == 0:
        await callback.message.answer("❌ Ошибка: данные рассылки не найдены")
        await state.clear()
        return
    
    # Создаем запись о рассылке
    admin_user = get_user(callback.from_user.id)
    db.execute(
        "INSERT INTO broadcasts (admin_id, message, total_users) VALUES (?, ?, ?)",
        (admin_user['id'], broadcast_message, total_users)
    )
    
    broadcast_id = db.fetchone("SELECT last_insert_rowid() as id")['id']
    
    # Отправляем сообщение о начале рассылки
    await callback.message.edit_text(
        f"🔄 НАЧАЛАСЬ РАССЫЛКА\n\n"
        f"Отправка сообщения {total_users} пользователям...\n"
        f"Это может занять некоторое время."
    )
    
    # Запускаем асинхронную рассылку
    asyncio.create_task(
        send_broadcast(
            callback.bot,
            broadcast_message,
            total_users,
            broadcast_id,
            callback.message.chat.id
        )
    )
    
    await state.clear()
    await callback.answer()

async def send_broadcast(bot: Bot, message: str, total_users: int, broadcast_id: int, admin_chat_id: int):
    """Асинхронная отправка рассылки"""
    users = get_all_users()
    sent_count = 0
    failed_count = 0
    
    for user in users:
        try:
            # Экранируем HTML-сущности для безопасности
            safe_message = html.escape(message)
            
            await bot.send_message(
                chat_id=user['tg_id'],
                text=safe_message
            )
            sent_count += 1
            
            # Обновляем статус каждые 10 отправленных сообщений
            if sent_count % 10 == 0 or sent_count == total_users:
                await bot.send_message(
                    chat_id=admin_chat_id,
                    text=f"📊 Прогресс рассылки: {sent_count}/{total_users} ({sent_count/total_users*100:.1f}%)"
                )
            
            # Небольшая задержка, чтобы не превысить лимиты Telegram
            await asyncio.sleep(0.1)
            
        except Exception as e:
            logger.error(f"Failed to send broadcast to {user['tg_id']}: {e}")
            failed_count += 1
            continue
    
    # Обновляем статистику в базе данных
    db.execute(
        "UPDATE broadcasts SET sent_users = ?, failed_users = ? WHERE id = ?",
        (sent_count, failed_count, broadcast_id)
    )
    
    # Отправляем финальный отчет
    success_rate = (sent_count / total_users * 100) if total_users > 0 else 0
    
    report_text = (
        f"✅ РАССЫЛКА ЗАВЕРШЕНА\n\n"
        f"📊 Результаты:\n"
        f"• Всего получателей: {total_users}\n"
        f"• Успешно отправлено: {sent_count}\n"
        f"• Не удалось отправить: {failed_count}\n"
        f"• Успешность: {success_rate:.1f}%\n\n"
        f"ID рассылки: #{broadcast_id}"
    )
    
    await bot.send_message(chat_id=admin_chat_id, text=report_text)

# ==================== ОБРАБОТЧИКИ CALLBACK ====================
@router.callback_query(F.data == "edit_wishlist")
async def callback_edit_wishlist(callback: CallbackQuery, state: FSMContext):
    """Редактирование списка желаний"""
    await callback.message.answer(
        "📝 Список желаний\n\n"
        "Напишите, что бы вы хотели получить в подарок.\n"
        "Можно перечислить несколько вариантов."
    )
    await state.set_state(UserStates.editing_wishlist)
    await callback.answer()

@router.callback_query(F.data == "edit_address")
async def callback_edit_address(callback: CallbackQuery, state: FSMContext):
    """Редактирование адреса"""
    await callback.message.answer(
        "🏠 Адрес для доставки\n\n"
        "Укажите адрес, куда можно доставить подарок.\n"
        "Для офлайн встреч можно указать 'Встречаемся лично'."
    )
    await state.set_state(UserStates.editing_address)
    await callback.answer()

@router.message(UserStates.editing_wishlist)
async def process_wishlist(message: Message, state: FSMContext):
    """Обработка списка желаний"""
    wishlist = message.text.strip()[:500]
    
    db.execute(
        "UPDATE users SET wishlist = ? WHERE tg_id = ?",
        (wishlist, message.from_user.id)
    )
    
    await message.answer(
        "✅ Список желаний сохранен!\n"
        "Теперь Дедушке Морозу будет проще выбрать для вас подарок."
    )
    await state.clear()

@router.message(UserStates.editing_address)
async def process_address(message: Message, state: FSMContext):
    """Обработка адреса"""
    address = message.text.strip()[:200]
    
    db.execute(
        "UPDATE users SET address = ? WHERE tg_id = ?",
        (address, message.from_user.id)
    )
    
    await message.answer(
        "✅ Адрес сохранен!\n"
        "Теперь Дедушка Мороз знает, куда доставить подарок."
    )
    await state.clear()

# ... (остальные callback-обработчики из предыдущих версий кода) ...

# ==================== ФУНКЦИИ ДЛЯ ОБМЕНА ====================
def create_santa_pairs(user_ids: List[int], room_id: int) -> List[Tuple[int, int]]:
    """
    Создает пары Тайного Дедушки Мороза
    Возвращает список кортежей (santa_id, recipient_id)
    """
    if len(user_ids) < 2:
        return []
    
    # Перемешиваем список
    shuffled = user_ids.copy()
    random.shuffle(shuffled)
    
    # Создаем пары: каждый дарит следующему, последний - первому
    pairs = []
    for i in range(len(shuffled)):
        santa = shuffled[i]
        recipient = shuffled[(i + 1) % len(shuffled)]
        pairs.append((santa, recipient))
    
    return pairs

# ==================== ЗАПУСК БОТА ====================
async def main():
    """Основная функция запуска бота"""
    # Создаем объекты бота и диспетчера
    bot = Bot(token=TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    # Включаем роутеры
    dp.include_router(router)
    dp.include_router(admin_router)
    
    # Устанавливаем команды меню
    await bot.set_my_commands([
        {"command": "start", "description": "Запустить бота"},
        {"command": "create_room", "description": "Создать комнату"},
        {"command": "join", "description": "Присоединиться к комнате"},
        {"command": "my_rooms", "description": "Мои комнаты"},
        {"command": "profile", "description": "Мой профиль"},
        {"command": "help", "description": "Помощь"},
    ])
    
    logger.info("✅ Бот Тайный Дедушка Мороз запущен!")
    
    # Запускаем поллинг
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())

