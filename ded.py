#!/usr/bin/env python3
"""
🎅 Тайный Дедушка Мороз - Telegram бот для организации обмена подарками
Версия с сохранением данных в постоянном хранилище для Bothost.ru
"""

import asyncio
import logging
import secrets
import sqlite3
import random
import os
import html
import shutil
import time
from datetime import datetime, timedelta
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

# ==================== НАСТРОЙКА ПОСТОЯННОГО ХРАНИЛИЩА ====================
# Получаем путь для хранения данных из переменных окружения
# На Bothost установите переменную DATA_PATH=/app/data
DATA_DIR = os.getenv('DATA_PATH', '.')  # По умолчанию текущая директория

# Создаем директории если их нет
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR, exist_ok=True)
    logger.info(f"📁 Создана директория для данных: {DATA_DIR}")

# Путь к базе данных (в постоянном хранилище)
DB_PATH = os.path.join(DATA_DIR, 'santa.db')
logger.info(f"📍 База данных будет храниться в: {DB_PATH}")

# Путь для логов действий пользователей
LOG_DIR = os.path.join(DATA_DIR, 'logs')
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR, exist_ok=True)
    logger.info(f"📁 Создана директория для логов: {LOG_DIR}")

# ==================== БАЗА ДАННЫХ ====================
class Database:
    def __init__(self, db_path='santa.db'):
        self.db_path = db_path
        
        # Создаем директорию для БД если её нет
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            logger.info(f"📁 Создана директория для БД: {db_dir}")
        
        # Подключаемся к базе данных
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.create_tables()
        self.check_database_integrity()
        logger.info(f"✅ База данных подключена: {self.db_path}")
        logger.info(f"📊 Размер файла БД: {os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0} байт")
    
    def check_database_integrity(self):
        """Проверяет целостность базы данных"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()
            if result and result[0] == 'ok':
                logger.info("✅ Проверка целостности БД: OK")
            else:
                logger.warning(f"⚠️ Проблемы с целостностью БД: {result}")
        except Exception as e:
            logger.error(f"❌ Ошибка при проверке целостности БД: {e}")
    
    def create_tables(self):
        """Создает все необходимые таблицы"""
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
                is_active BOOLEAN DEFAULT 1,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                notified BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        
        # Действия пользователей (лог)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Создаем индексы для ускорения поиска
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_tg_id ON users(tg_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_created ON users(created_at)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_rooms_owner ON rooms(owner_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_room_participants_room ON room_participants(room_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_room_participants_user ON room_participants(user_id)')
        
        self.conn.commit()
        logger.info("✅ Таблицы базы данных созданы/проверены")
    
    def backup_database(self):
        """Создает резервную копию базы данных"""
        backup_dir = os.path.join(DATA_DIR, 'backups')
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir, exist_ok=True)
        
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(backup_dir, f"santa_backup_{timestamp}.db")
        
        try:
            # Закрываем соединение для копирования
            self.conn.close()
            
            # Копируем файл
            shutil.copy2(self.db_path, backup_path)
            
            # Восстанавливаем соединение
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            
            # Удаляем старые бэкапы (оставляем последние 5)
            backups = sorted([f for f in os.listdir(backup_dir) if f.startswith('santa_backup_')])
            if len(backups) > 5:
                for old_backup in backups[:-5]:
                    os.remove(os.path.join(backup_dir, old_backup))
            
            logger.info(f"✅ Создана резервная копия БД: {backup_path}")
            return backup_path
        except Exception as e:
            logger.error(f"❌ Ошибка резервного копирования БД: {e}")
            # Восстанавливаем соединение в случае ошибки
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            return None
    
    def execute(self, query: str, params=()):
        """Выполняет SQL запрос"""
        cursor = self.conn.cursor()
        try:
            cursor.execute(query, params)
            self.conn.commit()
            return cursor
        except Exception as e:
            logger.error(f"❌ Ошибка выполнения запроса: {e}\nЗапрос: {query}\nПараметры: {params}")
            self.conn.rollback()
            raise
    
    def fetchone(self, query: str, params=()):
        """Получает одну запись"""
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchone()
    
    def fetchall(self, query: str, params=()):
        """Получает все записи"""
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()
    
    def get_database_info(self):
        """Возвращает информацию о базе данных"""
        try:
            info = {}
            
            # Количество записей в таблицах
            tables = ['users', 'rooms', 'room_participants', 'santa_pairs', 'broadcasts']
            for table in tables:
                result = self.fetchone(f"SELECT COUNT(*) as count FROM {table}")
                info[table] = result['count'] if result else 0
            
            # Размер файла
            if os.path.exists(self.db_path):
                info['file_size'] = os.path.getsize(self.db_path)
                info['file_modified'] = datetime.fromtimestamp(os.path.getmtime(self.db_path))
            
            return info
        except Exception as e:
            logger.error(f"❌ Ошибка получения информации о БД: {e}")
            return {}

# Глобальный объект базы данных
db = Database(DB_PATH)

# ==================== ФУНКЦИИ ДЛЯ ЛОГИРОВАНИЯ ДЕЙСТВИЙ ====================
def log_user_action_to_file(user_id: int, username: str, action: str, details: str = ""):
    """Логирует действия пользователя в текстовый файл"""
    try:
        log_file = os.path.join(LOG_DIR, "user_actions.log")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        log_entry = f"[{timestamp}] UserID: {user_id} (@{username}) - {action}"
        if details:
            log_entry += f" - {details}"
        
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(log_entry + "\n")
        
        logger.debug(f"📝 Логировано действие в файл: {action}")
    except Exception as e:
        logger.error(f"❌ Ошибка записи в лог-файл: {e}")

def log_user_action_to_db(user_id: int, action_type: str, details: str = ""):
    """Логирует действия пользователя в базу данных"""
    try:
        user = get_user(user_id)
        if user:
            db.execute(
                "INSERT INTO user_actions (user_id, action_type, details) VALUES (?, ?, ?)",
                (user['id'], action_type, details)
            )
    except Exception as e:
        logger.error(f"❌ Ошибка записи действия в БД: {e}")

def log_user_action(user_id: int, username: str, action_type: str, details: str = ""):
    """Логирует действия пользователя (в файл и БД)"""
    log_user_action_to_file(user_id, username, action_type, details)
    log_user_action_to_db(user_id, action_type, details)

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
    try:
        user = db.fetchone("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
        if user:
            logger.debug(f"✅ Пользователь найден: tg_id={tg_id}, username={user['username']}")
            return user
        else:
            logger.debug(f"⚠️ Пользователь не найден в БД: tg_id={tg_id}")
            return None
    except Exception as e:
        logger.error(f"❌ Ошибка при поиске пользователя tg_id={tg_id}: {e}")
        return None

def create_user(tg_id: int, username: str, first_name: str, last_name: str = ""):
    """Создать нового пользователя"""
    try:
        db.execute(
            "INSERT OR IGNORE INTO users (tg_id, username, first_name, last_name, is_active, last_seen) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (tg_id, username, first_name, last_name, 1)
        )
        
        # Обновляем last_seen для существующего пользователя
        db.execute(
            "UPDATE users SET last_seen = CURRENT_TIMESTAMP WHERE tg_id = ?",
            (tg_id,)
        )
        
        logger.info(f"✅ Создан/обновлен пользователь: {first_name} (id: {tg_id})")
        
        # Логируем создание пользователя
        log_user_action(tg_id, username, "user_registered", f"name: {first_name}")
        
        return get_user(tg_id)
    except Exception as e:
        logger.error(f"❌ Ошибка при создании пользователя {tg_id}: {e}")
        return None

def get_or_create_user(tg_id: int, username: str, first_name: str, last_name: str = ""):
    """Получить существующего пользователя или создать нового"""
    user = get_user(tg_id)
    if not user:
        user = create_user(tg_id, username, first_name, last_name)
    return user

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
    try:
        if active_only:
            users = db.fetchall("SELECT * FROM users WHERE is_active = 1")
        else:
            users = db.fetchall("SELECT * FROM users")
        
        logger.debug(f"📊 Получено пользователей: {len(users) if users else 0}")
        return users or []
    except Exception as e:
        logger.error(f"❌ Ошибка при получении пользователей: {e}")
        return []

def count_all_users():
    """Посчитать всех пользователей"""
    try:
        result = db.fetchone("SELECT COUNT(*) as count FROM users")
        if result and 'count' in result:
            count = result['count']
            logger.debug(f"📊 Всего пользователей в БД: {count}")
            return count
        else:
            logger.warning("⚠️ Запрос COUNT(*) вернул None или пустой результат")
            return 0
    except Exception as e:
        logger.error(f"❌ Ошибка при подсчете пользователей: {e}")
        return 0

def count_active_users():
    """Посчитать активных пользователей"""
    try:
        result = db.fetchone("SELECT COUNT(*) as count FROM users WHERE is_active = 1")
        return result['count'] if result and 'count' in result else 0
    except Exception as e:
        logger.error(f"❌ Ошибка при подсчете активных пользователей: {e}")
        return 0

def get_user_by_id(user_id: int):
    """Получить пользователя по ID"""
    return db.fetchone("SELECT * FROM users WHERE id = ?", (user_id,))

def get_room_stats():
    """Получить статистику по комнатам"""
    try:
        total_rooms = db.fetchone("SELECT COUNT(*) as count FROM rooms")
        active_rooms = db.fetchone("SELECT COUNT(*) as count FROM rooms WHERE is_active = 1")
        exchanges_started = db.fetchone("SELECT COUNT(*) as count FROM rooms WHERE exchange_started = 1")
        
        stats = {
            'total_rooms': total_rooms['count'] if total_rooms else 0,
            'active_rooms': active_rooms['count'] if active_rooms else 0,
            'exchanges_started': exchanges_started['count'] if exchanges_started else 0
        }
        
        logger.debug(f"📊 Статистика комнат: {stats}")
        return stats
    except Exception as e:
        logger.error(f"❌ Ошибка при получении статистики комнат: {e}")
        return {'total_rooms': 0, 'active_rooms': 0, 'exchanges_started': 0}

def get_new_users_last_days(days: int = 7):
    """Получить количество новых пользователей за последние N дней"""
    try:
        date_threshold = datetime.now() - timedelta(days=days)
        result = db.fetchone(
            "SELECT COUNT(*) as count FROM users WHERE created_at > ?",
            (date_threshold.strftime('%Y-%m-%d %H:%M:%S'),)
        )
        return result['count'] if result and 'count' in result else 0
    except Exception as e:
        logger.error(f"❌ Ошибка при подсчете новых пользователей: {e}")
        return 0

def export_users_to_file():
    """Экспортирует список пользователей в текстовый файл"""
    try:
        export_file = os.path.join(DATA_DIR, "users_export.txt")
        users = get_all_users(active_only=False)
        
        with open(export_file, "w", encoding="utf-8") as f:
            f.write(f"=== Экспорт пользователей Тайного Дедушки Мороза ===\n")
            f.write(f"Дата экспорта: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Всего пользователей: {len(users)}\n")
            f.write("=" * 60 + "\n\n")
            
            for user in users:
                f.write(f"ID: {user['id']}\n")
                f.write(f"Telegram ID: {user['tg_id']}\n")
                f.write(f"Имя: {user['first_name']} {user['last_name']}\n")
                f.write(f"Username: @{user['username'] or 'нет'}\n")
                f.write(f"Зарегистрирован: {user['created_at']}\n")
                f.write(f"Активен: {'Да' if user['is_active'] else 'Нет'}\n")
                f.write(f"Список желаний: {user['wishlist'] or 'не указан'}\n")
                f.write(f"Адрес: {user['address'] or 'не указан'}\n")
                f.write("-" * 40 + "\n")
        
        logger.info(f"✅ Экспорт пользователей создан: {export_file}")
        return export_file
    except Exception as e:
        logger.error(f"❌ Ошибка при экспорте пользователей: {e}")
        return None

# ==================== ОСНОВНЫЕ КОМАНДЫ ====================
@router.message(CommandStart())
async def cmd_start(message: Message):
    """Начало работы с ботом - команда /start"""
    user = message.from_user
    
    # Получаем или создаем пользователя
    db_user = get_or_create_user(user.id, user.username, user.first_name, user.last_name or "")
    
    if not db_user:
        await message.answer("❌ Не удалось создать ваш профиль. Попробуйте снова.")
        return
    
    # Логируем действие
    log_user_action(user.id, user.username, "bot_started")
    
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
    # Логируем действие
    log_user_action(message.from_user.id, message.from_user.username, "help_requested")
    
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
    # Логируем действие
    log_user_action(message.from_user.id, message.from_user.username, "profile_viewed")
    
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
    # Логируем действие
    log_user_action(message.from_user.id, message.from_user.username, "room_creation_started")
    
    # Получаем или создаем пользователя
    user = get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name or ""
    )
    
    if not user:
        await message.answer("❌ Ошибка: не удалось создать ваш профиль.")
        return
    
    await message.answer("Введите название для новой комнаты (до 50 символов):")
    await state.set_state(UserStates.waiting_room_name)

@router.message(UserStates.waiting_room_name)
async def process_room_name(message: Message, state: FSMContext):
    """Обработка названия комнаты"""
    room_name = message.text.strip()[:50]
    
    # Получаем пользователя (он должен быть создан в cmd_create_room)
    user = get_user(message.from_user.id)
    
    if not user:
        # Если пользователь все же не найден, создаем его
        logger.warning(f"🔄 Пользователь не найден при создании комнаты, создаем...")
        user_data = message.from_user
        user = create_user(
            user_data.id, 
            user_data.username, 
            user_data.first_name, 
            user_data.last_name or ""
        )
    
    if not user:
        await message.answer("❌ Критическая ошибка: не удалось найти или создать ваш профиль.")
        await state.clear()
        return
    
    # Генерируем уникальный код
    invite_code = generate_invite_code()
    while get_room_by_code(invite_code):
        invite_code = generate_invite_code()
    
    # Создаем комнату
    try:
        db.execute(
            "INSERT INTO rooms (name, owner_id, invite_code, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
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
        
        logger.info(f"✅ Создана новая комната: '{room_name}' (ID: {room_id}) пользователем {user['first_name']}")
        
        # Логируем создание комнаты
        log_user_action(message.from_user.id, message.from_user.username, "room_created", f"name: {room_name}, id: {room_id}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при создании комнаты: {e}")
        await message.answer("❌ Произошла ошибка при создании комнаты. Попробуйте еще раз.")
    
    await state.clear()

# ... (остальной код бота остается таким же как в предыдущей версии) ...
# Для экономии места, остальные функции (join, my_rooms, admin-панель и т.д.)
# остаются без изменений, просто добавьте логирование действий в ключевых местах

# ==================== АДМИН-ПАНЕЛЬ ====================
@admin_router.message(Command("admin"))
async def cmd_admin(message: Message):
    """Панель администратора"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к админ-панели")
        return
    
    # Логируем действие
    log_user_action(message.from_user.id, message.from_user.username, "admin_panel_opened")
    
    total_users = count_all_users()
    active_users = count_active_users()
    new_users_week = get_new_users_last_days(7)
    room_stats = get_room_stats()
    
    # Получаем информацию о базе данных
    db_info = db.get_database_info()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📢 Создать рассылку", callback_data="admin_broadcast"),
            InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")
        ],
        [
            InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users"),
            InlineKeyboardButton(text="🏠 Комнаты", callback_data="admin_rooms")
        ],
        [
            InlineKeyboardButton(text="💾 Экспорт данных", callback_data="admin_export"),
            InlineKeyboardButton(text="🔄 Резервная копия", callback_data="admin_backup")
        ]
    ])
    
    stats_text = (
        f"👑 АДМИН-ПАНЕЛЬ\n\n"
        f"📊 Статистика бота:\n"
        f"• Всего пользователей: {total_users}\n"
        f"• Активных пользователей: {active_users}\n"
        f"• Новых за неделю: {new_users_week}\n"
        f"• Всего комнат: {room_stats['total_rooms']}\n"
        f"• Активных комнат: {room_stats['active_rooms']}\n"
        f"• Начатых обменов: {room_stats['exchanges_started']}\n\n"
        f"💾 Информация о БД:\n"
        f"• Путь: {DB_PATH}\n"
        f"• Размер: {db_info.get('file_size', 0) // 1024} KB\n"
    )
    
    await message.answer(stats_text, reply_markup=keyboard)

@admin_router.callback_query(F.data == "admin_backup")
async def callback_admin_backup(callback: CallbackQuery):
    """Создание резервной копии"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    
    # Логируем действие
    log_user_action(callback.from_user.id, callback.from_user.username, "backup_requested")
    
    await callback.message.answer("🔄 Создание резервной копии базы данных...")
    
    backup_path = db.backup_database()
    
    if backup_path:
        await callback.message.answer(f"✅ Резервная копия создана:\n{backup_path}")
        log_user_action(callback.from_user.id, callback.from_user.username, "backup_created", f"path: {backup_path}")
    else:
        await callback.message.answer("❌ Не удалось создать резервную копию")
    
    await callback.answer()

@admin_router.callback_query(F.data == "admin_export")
async def callback_admin_export(callback: CallbackQuery):
    """Экспорт данных пользователей"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    
    # Логируем действие
    log_user_action(callback.from_user.id, callback.from_user.username, "export_requested")
    
    await callback.message.answer("📤 Экспорт данных пользователей...")
    
    export_file = export_users_to_file()
    
    if export_file and os.path.exists(export_file):
        file_size = os.path.getsize(export_file)
        await callback.message.answer(
            f"✅ Экспорт создан:\n"
            f"Файл: {export_file}\n"
            f"Размер: {file_size} байт\n\n"
            f"Файл сохранен в постоянном хранилище."
        )
        log_user_action(callback.from_user.id, callback.from_user.username, "export_created", f"file: {export_file}")
    else:
        await callback.message.answer("❌ Не удалось создать экспорт")
    
    await callback.answer()

# ... (остальная часть кода admin-панели) ...

# ==================== ЗАПУСК БОТА ====================
async def main():
    """Основная функция запуска бота"""
    # Создаем резервную копию при запуске (если БД существует)
    if os.path.exists(DB_PATH):
        db.backup_database()
    
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
    logger.info(f"📍 Путь к базе данных: {DB_PATH}")
    logger.info(f"📊 Статистика при запуске:")
    logger.info(f"  • Пользователей: {count_all_users()}")
    logger.info(f"  • Комнат: {get_room_stats()['total_rooms']}")
    logger.info(f"  • Администраторов: {len(ADMIN_IDS)}")
    
    # Запускаем поллинг
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
