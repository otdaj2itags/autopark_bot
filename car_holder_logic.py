import logging
import os
import asyncio
import re
from math import ceil
from datetime import datetime, timedelta
from io import BytesIO

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine

from car_holder_base import Base, User, Request

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from aiogram.types import BufferedInputFile
import calendar


# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# Ваш токен Telegram-бота (установите его в переменной окружения)
API_TOKEN = '7546308673:AAFQI4zOYwjZtgM9Ra-uMURhdLYp9TMEwjY'

# Создание объектов бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Подключение к базе данных
engine = create_engine('sqlite:///autopark.db', echo=False)
Session = sessionmaker(bind=engine)
session = Session()

# Машина состояний для заявки
class RequestState(StatesGroup):
    waiting_for_employee_name = State()
    waiting_for_purpose = State()
    waiting_for_reason = State()
    waiting_for_datetime = State()
    waiting_for_time = State()
    waiting_for_address = State()
    waiting_for_trip_type = State()
    waiting_for_driver_choice = State()
    waiting_for_notes = State()
    waiting_for_file = State()
    waiting_for_file_confirmation = State()

# Машина состояний для примечаний после одобрения/отклонения заявки
class ApprovalState(StatesGroup):
    waiting_for_approval_note = State()
    waiting_for_rejection_note = State()

# Константы
USERS_PER_PAGE = 5
REQUESTS_PER_PAGE = 5

# Обработчик команды /start
@dp.message(Command(commands=["start"]))
async def start_command(message: Message):
    # Поиск пользователя в базе данных по его tg_id
    user = session.query(User).filter_by(tg_id=message.from_user.id).first()

    # Проверка наличия username
    username = message.from_user.username if message.from_user.username else "Не указан"

    if not user:
        # Если пользователь не найден, создаем нового с ролью "заказчик"
        full_name = message.from_user.first_name
        if message.from_user.last_name:
            full_name += f" {message.from_user.last_name}"

        # Новый пользователь получает роль "заказчик" по умолчанию
        new_user = User(tg_id=message.from_user.id, full_name=full_name, username=username, role='заказчик')
        session.add(new_user)
        session.commit()

        await message.answer(f"Добро пожаловать, {full_name}! Ваша роль установлена как 'заказчик'. "
                             "Для смены роли свяжитесь с администратором.")
        return
    else:
        # Обновление username, если он изменился
        if user.username != username:
            user.username = username
            session.commit()

    # Генерация меню на основе роли пользователя
    buttons = []

    if user.role == 'администратор':
        buttons = [
            [KeyboardButton(text="📓 Посмотреть все заявки")],
            [KeyboardButton(text="⛏️ Назначить роль пользователю")],
            [KeyboardButton(text="👀 Посмотреть роли пользователей")],
            [KeyboardButton(text="🗑️ Удалить пользователя")]
        ]

    elif user.role == 'управляющий делами':
        buttons = [
            [KeyboardButton(text="🔍 Посмотреть заявки на утверждение")]
        ]

    elif user.role == 'офицер безопасности':
        buttons = [
            [KeyboardButton(text="🔍 Посмотреть заявки на утверждение")]
        ]

    elif user.role == 'механик':
        buttons = [
            [KeyboardButton(text="🔍 Посмотреть утвержденные заявки")]
        ]

    elif user.role == 'заказчик':
        buttons = [
            [KeyboardButton(text="🖊️ Создать новую заявку")],
            [KeyboardButton(text="🔍 Посмотреть свои заявки")]
        ]

    # Создание ReplyKeyboardMarkup с кнопками
    markup = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

    await message.answer(f"Добро пожаловать обратно, {user.full_name}! Ваша роль: {user.role}", reply_markup=markup)

# Обработчик команды /whoami
@dp.message(Command(commands=["whoami"]))
async def whoami_command(message: Message):
    user = session.query(User).filter_by(tg_id=message.from_user.id).first()

    if user:
        await message.answer(f"Ваша роль: {user.role}")
    else:
        await message.answer("Вы еще не зарегистрированы в системе. Пожалуйста, используйте /start для начала.")

# Обработчик нажатия кнопки "Создать новую заявку"
@dp.message(lambda message: message.text == "🖊️ Создать новую заявку")
async def new_request_command(message: Message, state: FSMContext):

    current_state = await state.get_state()
    if current_state is not None:
        await message.answer("Завершите текущий процесс создания заявки перед началом новой.")
        return

    user = session.query(User).filter_by(tg_id=message.from_user.id).first()
    if not user or user.role != 'заказчик':
        await message.answer("У вас нет прав для создания заявки. Только пользователи с ролью 'заказчик' могут создавать заявки.")
        return

    logging.info(f"DEBUG: заявка создана пользователем {user.full_name} ({user.tg_id}).")

    # Добавляем кнопку "Отменить заявку" в клавиатуру
    markup = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Отменить заявку")]],
    resize_keyboard=True
)

    await message.answer("Введите ФИО сотрудника:", reply_markup=markup)
    await state.set_state(RequestState.waiting_for_employee_name)

@dp.message(lambda message: message.text == "Отменить заявку")
async def cancel_request(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Процесс создания заявки отменен.", reply_markup=types.ReplyKeyboardRemove())

# Обработчик ввода ФИО сотрудника
@dp.message(RequestState.waiting_for_employee_name)
async def request_employee_name_entered(message: Message, state: FSMContext):
    await state.update_data(employee_name=message.text)
    await message.answer("Введите цель поездки:")
    await state.set_state(RequestState.waiting_for_purpose)

# Обработчик ввода цели поездки
@dp.message(RequestState.waiting_for_purpose)
async def request_purpose_entered(message: Message, state: FSMContext):
    await state.update_data(purpose=message.text)
    await message.answer("Введите основание для поездки:")
    await state.set_state(RequestState.waiting_for_reason)

# Обработчик ввода основания для поездки
@dp.message(RequestState.waiting_for_reason)
async def request_reason_entered(message: Message, state: FSMContext):
    await state.update_data(reason=message.text)
    await show_custom_calendar(message, state)  # Вызываем функцию показа календаря

# Генерация кастомного календаря
def generate_calendar(year: int, month: int) -> InlineKeyboardMarkup:
    # Создаем список для кнопок
    inline_keyboard = []
    
    # Заголовок с месяцем и годом
    inline_keyboard.append([InlineKeyboardButton(text=f"{calendar.month_name[month]} {year}", callback_data="ignore")])
    
    # Дни недели
    days_of_week = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    inline_keyboard.append([InlineKeyboardButton(text=day, callback_data="ignore") for day in days_of_week])
    
    # Дни месяца
    cal = calendar.monthcalendar(year, month)
    for week in cal:
        row = [InlineKeyboardButton(text=str(day) if day != 0 else " ", callback_data=f"day:{year}-{month:02d}-{day:02d}") for day in week]
        inline_keyboard.append(row)
    
    # Кнопки навигации между месяцами
    prev_button = InlineKeyboardButton(text="<", callback_data=f"change_month:{year}:{month - 1}")
    next_button = InlineKeyboardButton(text=">", callback_data=f"change_month:{year}:{month + 1}")
    inline_keyboard.append([prev_button, next_button])
    
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


# Функция для показа кастомного календаря
async def show_custom_calendar(message: Message, state: FSMContext):
    today = datetime.today()
    await message.answer("📅 Выберите дату:", reply_markup=generate_calendar(today.year, today.month))
    await state.set_state(RequestState.waiting_for_datetime)

# Обработчик выбора даты и навигации по календарю
@dp.callback_query(lambda c: c.data and (c.data.startswith("day:") or c.data.startswith("change_month:")))
async def process_custom_calendar(callback_query: CallbackQuery, state: FSMContext):
    data = callback_query.data.split(":")
    
    if data[0] == "day":  # Выбор конкретного дня
        selected_date = datetime.strptime(data[1], "%Y-%m-%d")
        await state.update_data(datetime_out=selected_date)
        
        # Убираем календарь и отправляем подтверждение
        await callback_query.message.edit_reply_markup(reply_markup=None)
        await callback_query.message.answer(f"Вы выбрали дату: {selected_date.strftime('%d-%m-%Y')}")
        
        # Переход к следующему этапу, запрос времени
        await state.set_state(RequestState.waiting_for_time)
        await callback_query.message.answer("Введите время (ЧЧ:ММ):")
        
    elif data[0] == "change_month":  # Навигация по месяцам
        year, month = int(data[1]), int(data[2])
        if month < 1:  # Если предыдущий месяц
            month, year = 12, year - 1
        elif month > 12:  # Если следующий месяц
            month, year = 1, year + 1
        # Обновляем календарь для нового месяца
        await callback_query.message.edit_reply_markup(reply_markup=generate_calendar(year, month))

    await callback_query.answer()

# Обработчик для ввода времени
@dp.message(RequestState.waiting_for_time)
async def get_time(message: Message, state: FSMContext):
    try:
        time_str = message.text.strip()
        request_date = (await state.get_data())['datetime_out']
        datetime_out = datetime.strptime(f"{request_date.date()} {time_str}", "%Y-%m-%d %H:%M")
        await state.update_data(datetime_out=datetime_out)
        await message.answer(f"✅ Вы выбрали дату и время: {datetime_out.strftime('%d-%m-%Y %H:%M')}")

        # Переход к следующему этапу
        await message.answer("Введите адрес назначения:")
        await state.set_state(RequestState.waiting_for_address)

    except ValueError:
        await message.answer("Неверный формат времени. Введите время в формате ЧЧ:ММ.")

# Обработчик ввода адреса назначения
@dp.message(RequestState.waiting_for_address)
async def request_address_entered(message: Message, state: FSMContext):
    await state.update_data(address=message.text)
    await prompt_for_trip_type(message)
    await state.set_state(RequestState.waiting_for_trip_type)

# Функция для запроса типа выезда с инлайн-кнопками
async def prompt_for_trip_type(message: Message):
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Служебный", callback_data="trip_type:служебный")],
            [InlineKeyboardButton(text="Личный", callback_data="trip_type:личный")]
        ]
    )
    await message.answer("Выберите тип выезда:", reply_markup=markup)

# Обработчик выбора типа выезда (служебный или личный)
@dp.callback_query(RequestState.waiting_for_trip_type, lambda c: c.data.startswith("trip_type:"))
async def handle_trip_type(callback_query: CallbackQuery, state: FSMContext):
    trip_type = callback_query.data.split(":")[1]
    await state.update_data(business_trip=(trip_type == "служебный"))
    await callback_query.message.edit_reply_markup()  # Убираем кнопки после выбора

    # Переход к выбору "С водителем" или "Без водителя"
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="С водителем", callback_data="driver_choice:с водителем")],
            [InlineKeyboardButton(text="Без водителя", callback_data="driver_choice:без водителя")]
        ]
    )
    await callback_query.message.answer("Выберите поездку с водителем или без:", reply_markup=markup)
    await state.set_state(RequestState.waiting_for_driver_choice)
    await callback_query.answer()

# Обработчик выбора поездки с водителем или без
@dp.callback_query(RequestState.waiting_for_driver_choice, lambda c: c.data.startswith("driver_choice:"))
async def handle_driver_choice(callback_query: CallbackQuery, state: FSMContext):
    driver_choice = callback_query.data.split(":")[1]
    await state.update_data(with_driver=(driver_choice == "с водителем"))
    await callback_query.message.edit_reply_markup()  # Убираем кнопки после выбора

    # Переход к шагу с примечанием
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Пропустить", callback_data="skip_note")]
        ]
    )
    await callback_query.message.answer("Введите примечание к поездке или нажмите 'Пропустить':", reply_markup=markup)
    await state.set_state(RequestState.waiting_for_notes)
    await callback_query.answer()

# Обработчик ввода примечаний или выбора "Пропустить"
@dp.message(RequestState.waiting_for_notes)
async def request_notes_prompt(message: Message, state: FSMContext):
    await state.update_data(notes=message.text)
    await prompt_for_file(message)

# Обработчик нажатия кнопки "Пропустить"
@dp.callback_query(RequestState.waiting_for_notes, lambda c: c.data == "skip_note")
async def skip_note_handler(callback_query: CallbackQuery, state: FSMContext):
    await state.update_data(notes="Нет")
    await callback_query.message.edit_reply_markup()  # Убираем кнопки после выбора
    await prompt_for_file(callback_query.message)
    await callback_query.answer()

# Функция для запроса прикрепления файла
async def prompt_for_file(message: Message):
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Прикрепить файл", callback_data="attach_file")],
        [InlineKeyboardButton(text="Без файла", callback_data="no_file")]
    ])
    await message.answer("Хотите прикрепить файл к заявке?", reply_markup=markup)

# Обработчик нажатия кнопки "Без файла"
@dp.callback_query(lambda c: c.data == "no_file")
async def handle_no_file(callback_query: CallbackQuery, state: FSMContext):
    await finalize_request(callback_query, state, with_file=False)
    await callback_query.answer()

# Обработчик нажатия кнопки "Прикрепить файл"
@dp.callback_query(lambda c: c.data == "attach_file")
async def handle_attach_file(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.message.answer("Пожалуйста, прикрепите файл (документ, изображение, PDF и т.д.)")
    await state.set_state(RequestState.waiting_for_file)
    await callback_query.answer()

# Обработчик для получения файла
@dp.message(RequestState.waiting_for_file, lambda message: message.content_type in [types.ContentType.DOCUMENT, types.ContentType.PHOTO])
async def handle_file_upload(message: Message, state: FSMContext):
    if message.document:
        file_id = message.document.file_id
        file_name = message.document.file_name
    elif message.photo:
        file_id = message.photo[-1].file_id
        file_name = "Фото"

    await state.update_data(file_id=file_id, file_name=file_name)
    await message.answer("Файл прикреплен.")
    await finalize_request(message, state, with_file=True)

# Функция для финальной обработки и подтверждения заявки
async def finalize_request(message_or_callback, state: FSMContext, with_file: bool):
    data = await state.get_data()

    # Подготовка сообщения о заявке с подтверждением или отменой
    request_info = (
        f"Заявка создана:\n"
        f"<b>ФИО: {data['employee_name']}</b>\n"
        f"<i>Цель: {data['purpose']}</i>\n"
        f"Основание: {data['reason']}\n"
        f"Дата и время: {data['datetime_out']}\n"
        f"Адрес: {data['address']}\n"
        f"Тип выезда: {'Служебный' if data['business_trip'] else 'Личный'}\n"
        f"С водителем: {'Да' if data['with_driver'] else 'Нет'}\n"
        f"Примечания: {data['notes']}\n"
    )

    if with_file:
        request_info += f"Файл: {data.get('file_name', 'Не указан')}\n"

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отправить заявку", callback_data="send_request")],
        [InlineKeyboardButton(text="Отменить заявку", callback_data="cancel_request")]
    ])

    # Отправка сообщения с подтверждением
    if isinstance(message_or_callback, Message):
        await message_or_callback.answer(request_info, reply_markup=markup, parse_mode='HTML')
    elif isinstance(message_or_callback, CallbackQuery):
        await message_or_callback.message.answer(request_info, reply_markup=markup, parse_mode='HTML')

    await state.set_state(RequestState.waiting_for_file_confirmation)

# Обработчик для подтверждения отправки или отмены заявки
@dp.callback_query(lambda c: c.data in ["send_request", "cancel_request"])
async def handle_request_confirmation(callback_query: CallbackQuery, state: FSMContext):
    data = await state.get_data()

    if callback_query.data == "send_request":
        user = session.query(User).filter_by(tg_id=callback_query.from_user.id).first()

        new_request = Request(
            employee_name=data['employee_name'],
            purpose=data['purpose'],
            reason=data['reason'],
            datetime_out=data['datetime_out'],
            address=data['address'],
            business_trip=data['business_trip'],
            with_driver=data['with_driver'],
            status='на согласовании',
            manager_approval_1=False,
            manager_approval_2=False,
            requester=user.id,
            notes=data['notes']
        )
        session.add(new_request)
        session.commit()

        if 'file_id' in data:
            await send_request_notifications(new_request.id, file_id=data['file_id'], file_name=data['file_name'])
        else:
            await send_request_notifications(new_request.id)

        await callback_query.message.answer("✅ Заявка отправлена на согласование!")
    else:
        await callback_query.message.answer("❌ Заявка отменена.")

    await callback_query.message.edit_reply_markup(reply_markup=None)
    await state.clear()
    await callback_query.answer()


font_path = r"C:\Users\MIX\Desktop\dejavu\DejaVuSans.ttf"

# Функция генерации PDF для заявки
def generate_request_pdf(request):
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)

    # Регистрируем и устанавливаем шрифт
    pdfmetrics.registerFont(TTFont("FreeSans", font_path))
    pdf.setFont("FreeSans", 12)  # Используем шрифт FreeSans для поддержки кириллицы
    
    width, height = A4
    margin = 40  # Поля для улучшенного форматирования текста
    
    # Текст заявки
    text_content = (
        f"Заявка ID: {request.id}\n"
        f"ФИО: {request.employee_name}\n"
        f"Цель: {request.purpose}\n"
        f"Дата и время: {request.datetime_out.strftime('%d-%m-%Y %H:%M')}\n"
        f"Адрес: {request.address}\n"
        f"С водителем: {'Да' if request.with_driver else 'Нет'}\n"
        f"Примечания: {request.notes}"
    )

    # Позиционирование текста, начиная сверху страницы
    y_position = height - margin
    for line in text_content.split('\n'):
        pdf.drawString(margin, y_position, line)
        y_position -= 15  # Расстояние между строками

    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    return buffer

# Обработчик нажатия на кнопку "Посмотреть свои заявки"
@dp.message(lambda message: message.text == "🔍 Посмотреть свои заявки")
async def view_own_requests(message: Message, state: FSMContext):
    current_state = await state.get_state()
    # Если пользователь находится в машине состояний для создания заявки, сбросим это состояние
    if current_state and current_state.startswith("RequestState"):
        await state.clear()

    user = session.query(User).filter_by(tg_id=message.from_user.id).first()
    if not user or user.role != 'заказчик':
        await message.answer("❌ У вас нет прав для просмотра заявок.")
        return

    # Вывод заявок пользователя
    user_requests = session.query(Request).filter_by(requester=user.id).all()
    if not user_requests:
        await message.answer("У вас нет созданных заявок.")
        return

    response = "Ваши заявки:\n\n"
    for req in user_requests:
        response += (f"ID: {req.id}\n"
                     f"<b>ФИО: {req.employee_name}</b>\n"
                     f"<i>Цель: {req.purpose}</i>\n"
                     f"Дата и время: {req.datetime_out}\n"
                     f"Адрес: {req.address}\n"
                     f"С водителем: {'Да' if req.with_driver else 'Нет'}\n"
                     f"Статус: {req.status}\n\n")

    await message.answer(response, parse_mode='HTML')


# Обработчик отправки уведомлений при создании заявки
async def send_request_notifications(request_id: int, file_id=None, file_name=None):
    new_request = session.query(Request).filter_by(id=request_id).first()

    manager_users = session.query(User).filter(User.role.in_(['управляющий делами', 'офицер безопасности'])).all()
    for manager in manager_users:
        try:
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="Одобрить✅", callback_data=f"approve_request:{new_request.id}"),
                    InlineKeyboardButton(text="Отклонить❌", callback_data=f"reject_request:{new_request.id}")
                ]
            ])

            message_text = (
                f"Новая заявка на согласование:\n"
                f"<b>ФИО: {new_request.employee_name}</b>\n"
                f"<i>Цель: {new_request.purpose}</i>\n"
                f"Основание: {new_request.reason}\n"
                f"Дата и время: {new_request.datetime_out.strftime('%d-%m-%Y %H:%M') if new_request.datetime_out else 'Не указано'}\n"
                f"Адрес: {new_request.address}\n"
                f"Тип выезда: {'Служебный' if new_request.business_trip else 'Личный'}\n"
                f"С водителем: {'Да' if new_request.with_driver else 'Нет'}\n"
                f"Примечания: {new_request.notes}\n"
                f"Пожалуйста, одобрите или отклоните заявку."
            )

            if file_id:
                # Если есть файл, отправляем его
                await bot.send_document(
                    chat_id=manager.tg_id,
                    document=file_id,
                    caption=message_text,
                    reply_markup=markup,
                    parse_mode='HTML'
                )
            else:
                await bot.send_message(
                    chat_id=manager.tg_id,
                    text=message_text,
                    reply_markup=markup,
                    parse_mode='HTML'
                )

        except Exception as e:
            logging.error(f"Не удалось отправить сообщение менеджеру {manager.tg_id}: {e}")

# Обработчик для начала ввода примечания при одобрении
@dp.callback_query(lambda c: c.data.startswith("approve_request:"))
async def approve_request_start(callback_query: CallbackQuery, state: FSMContext):
    request_id = int(callback_query.data.split(":")[1])
    await state.update_data(request_id=request_id)

    # Убираем инлайн кнопки
    await callback_query.message.edit_reply_markup(reply_markup=None)

    # Добавляем кнопки для ввода примечания или пропуска
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пропустить", callback_data="skip_note")]
    ])

    await callback_query.message.answer("Пожалуйста, введите примечание к одобрению заявки или нажмите 'Пропустить'.", reply_markup=markup)
    await state.set_state(ApprovalState.waiting_for_approval_note)
    await callback_query.answer()

# Функция для обработки одобрения заявки и проверки двух подтверждений
async def process_request_approval(user, request, note):
    # Проставляем одобрение на основе роли пользователя
    if user.role == 'управляющий делами' and not request.manager_approval_1:
        request.manager_approval_1 = True
        request.notes = (request.notes or '') + f"\nПримечание от управляющего делами: {note}"
        logging.info(f"Заявка {request.id} одобрена управляющим делами")

    elif user.role == 'офицер безопасности' and not request.manager_approval_2:
        request.manager_approval_2 = True
        request.notes = (request.notes or '') + f"\nПримечание от офицера безопасности: {note}"
        logging.info(f"Заявка {request.id} одобрена офицером безопасности")

    else:
        logging.info(f"Заявка {request.id} не была изменена. Пользователь {user.full_name} ({user.role}) уже давал согласие или не имеет прав.")
        return "Заявка уже была одобрена вами или вы не имеете прав для ее одобрения."

    # Если оба менеджера одобрили, обновляем статус
    if request.manager_approval_1 and request.manager_approval_2:
        request.status = 'одобрена'
        logging.info(f"Заявка {request.id} полностью одобрена.")

         # Отправляем уведомление заказчику
        requester = session.query(User).filter_by(id=request.requester).first()
        if requester:
            try:
                await bot.send_message(
                    chat_id=requester.tg_id,
                    text=f"✅ Ваша заявка (ID: {request.id}) была одобрена управляющим делами и офицером безопасности"
                )
                logging.info(f"Уведомление отправлено заказчику {requester.full_name} (tg_id: {requester.tg_id})")
            except Exception as e:
                logging.error(f"Ошибка при отправке уведомления заказчику {requester.full_name} (tg_id: {requester.tg_id}): {e}")

    # Сохраняем изменения в базе данных
    session.commit()

    return "✅ Заявка успешно одобрена"

# Обработчик нажатия кнопки "Пропустить" при одобрении
@dp.callback_query(lambda c: c.data == "skip_note")
async def skip_note_handler(callback_query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    request_id = data.get('request_id')

    # Получаем пользователя
    user = session.query(User).filter_by(tg_id=callback_query.from_user.id).first()
    request = session.query(Request).filter_by(id=request_id).first()

    # Проставляем одобрение на основе роли пользователя
    result_message = await process_request_approval(user, request, note="")

    await callback_query.message.answer(result_message)
    await state.clear()
    await callback_query.answer()

# Обработчик ввода примечания и завершение одобрения
@dp.message(ApprovalState.waiting_for_approval_note)
async def approve_request_with_note(message: Message, state: FSMContext):
    note = message.text
    data = await state.get_data()
    request_id = data['request_id']
    user = session.query(User).filter_by(tg_id=message.from_user.id).first()
    request = session.query(Request).filter_by(id=request_id).first()

    # Обрабатываем одобрение и получаем результат
    result_message = await process_request_approval(user, request, note)
    await message.answer(result_message)

    # Завершаем состояние после обработки
    await state.clear()

# Обработчик для начала ввода примечания при отклонении
@dp.callback_query(lambda c: c.data.startswith("reject_request:"))
async def reject_request_start(callback_query: CallbackQuery, state: FSMContext):
    request_id = int(callback_query.data.split(":")[1])
    await state.update_data(request_id=request_id)

    # Убираем инлайн кнопки
    await callback_query.message.edit_reply_markup(reply_markup=None)

    # Добавляем кнопки для ввода примечания или пропуска
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пропустить", callback_data="skip_note_reject")]
    ])

    await callback_query.message.answer("Пожалуйста, введите примечание к отклонению заявки или нажмите 'Пропустить'.", reply_markup=markup)
    await state.set_state(ApprovalState.waiting_for_rejection_note)
    await callback_query.answer()

# Обработчик нажатия кнопки "Пропустить" при отклонении
@dp.callback_query(lambda c: c.data == "skip_note_reject")
async def skip_note_reject_handler(callback_query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    request_id = data.get('request_id')

    # Получаем пользователя
    user = session.query(User).filter_by(tg_id=callback_query.from_user.id).first()
    request = session.query(Request).filter_by(id=request_id).first()

    # Отклоняем заявку
    request.status = 'отклонена'
    session.commit()

    await callback_query.message.answer(f"Заявка {request_id} отклонена без примечания.")

    # Уведомляем заказчика
    requester = session.query(User).filter_by(id=request.requester).first()
    if requester:
        await bot.send_message(
            chat_id=requester.tg_id,
            text=f"Ваша заявка (ID: {request_id}) была отклонена {user.role}. ❌"
        )

    await state.clear()
    await callback_query.answer()

# Обработчик ввода примечания и завершение отклонения
@dp.message(ApprovalState.waiting_for_rejection_note)
async def reject_request_with_note(message: Message, state: FSMContext):
    note = message.text
    data = await state.get_data()
    request_id = data['request_id']
    request = session.query(Request).filter_by(id=request_id).first()
    request.status = 'отклонена'
    request.notes = (request.notes or '') + f"\nПримечание при отклонении: {note}"
    session.commit()

    await message.answer(f"Заявка {request_id} отклонена. Примечание сохранено.")

    # Уведомляем заказчика о том, что заявка отклонена с примечанием
    user = session.query(User).filter_by(tg_id=message.from_user.id).first()
    requester = session.query(User).filter_by(id=request.requester).first()
    if requester:
        await bot.send_message(
            chat_id=requester.tg_id,
            text=f"❌ Ваша заявка (ID: {request_id}) была отклонена {user.role}. Примечание: {note}"
        )

    await state.clear()

# Обработчик нажатия кнопки "Посмотреть все заявки"
@dp.message(lambda message: message.text == "📓 Посмотреть все заявки")
async def requests_command(message: Message):
    user = session.query(User).filter_by(tg_id=message.from_user.id).first()

    if not user or user.role not in ['управляющий делами', 'офицер безопасности', 'механик', 'администратор']:
        await message.answer("❌ У вас нет прав для просмотра заявок.")
        return

    requests = session.query(Request).all()

    if not requests:
        await message.answer("Нет активных заявок.")
        return

    response = "Все заявки:\n\n"
    for req in requests:
        response += (f"ID: {req.id}, ФИО: {req.employee_name}, Цель: {req.purpose}, "
                     f"Основание: {req.reason}, Дата и время: {req.datetime_out.strftime('%d-%m-%Y %H:%M') if req.datetime_out else 'Не указано'}, "
                     f"Адрес: {req.address}, Статус: {req.status}, "
                     f"С водителем: {'Да' if req.with_driver else 'Нет'}\n")

    await message.answer(response)

# Обработчик нажатия на кнопку "Назначить роль пользователю"
@dp.message(lambda message: message.text == "⛏️ Назначить роль пользователю")
async def handle_set_user_role(message: Message):
    await message.answer("Введите ID пользователя и роль в формате: <tg_id> <роль>")

# Обработчик сообщения с вводом tg_id и роли
@dp.message(lambda message: re.match(r"^\d+ .+$", message.text))
async def process_role_assignment(message: Message):
    user = session.query(User).filter_by(tg_id=message.from_user.id).first()
    # admin_user = session.query(User).filter_by(tg_id=message.from_user.id).first()

    # if not admin_user or admin_user.role != 'администратор':
    #     await message.answer("У вас нет прав для назначения ролей.")
    #     return
    if not user:
        await message.answer("Вы не зарегистрированы в системе. Используйте /start для регистрации.⚒️")
        return

    try:
        # Разделяем строку: первая часть - tg_id, остальное - роль
        split_message = message.text.split(maxsplit=1)
        tg_id = int(split_message[0])
        role = split_message[1].strip()

        # Проверяем пользователя в базе данных
        user = session.query(User).filter_by(tg_id=tg_id).first()
        if not user:
            # Получаем данные из чата и добавляем нового пользователя
            chat_member = await bot.get_chat(tg_id)
            full_name = f"{chat_member.first_name} {chat_member.last_name}" if chat_member.last_name else chat_member.first_name
            username = chat_member.username if chat_member.username else "Не указан"

            new_user = User(tg_id=tg_id, full_name=full_name, username=username, role=role)
            session.add(new_user)
            session.commit()

            await message.answer(f"✅ Пользователь {full_name} добавлен с ролью: {role}")
        else:
            # Обновляем роль существующего пользователя
            user.role = role
            session.commit()
            await message.answer(f"✅ Роль пользователя {user.full_name} обновлена на: {role}")

    except ValueError:
        await message.answer("Неверный формат. Используйте формат: <tg_id> <роль>")
    except Exception as e:
        await message.answer(f"Произошла ошибка: {str(e)}")

# Обработчик нажатия кнопки "Посмотреть заявки на утверждение"
@dp.message(lambda message: message.text == "🔍 Посмотреть заявки на утверждение")
async def view_pending_requests(message: Message):
    user = session.query(User).filter_by(tg_id=message.from_user.id).first()

    if not user or user.role not in ['управляющий делами', 'офицер безопасности']:
        await message.answer("У вас нет прав для просмотра заявок на утверждение.")
        return

    # Фильтрация заявок на основе роли пользователя
    if user.role == 'управляющий делами':
        pending_requests = session.query(Request).filter_by(manager_approval_1=False).all()
    elif user.role == 'офицер безопасности':
        pending_requests = session.query(Request).filter_by(manager_approval_2=False).all()

    if not pending_requests:
        await message.answer("Нет заявок на утверждение.")
        return

    # Формируем ответ с заявками на утверждение
    response = "Заявки на утверждение:\n\n"
    for req in pending_requests:
        response += (f"ID: {req.id}, ФИО: {req.employee_name}, Цель: {req.purpose}, "
                     f"Основание: {req.reason}, Дата и время: {req.datetime_out.strftime('%d-%m-%Y %H:%M') if req.datetime_out else 'Не указано'}, "
                     f"Адрес: {req.address}, Статус: {req.status}, "
                     f"С водителем: {'Да' if req.with_driver else 'Нет'}\n\n")

    await message.answer(response)

# Обработчик нажатия кнопки "Посмотреть утвержденные заявки"
@dp.message(lambda message: message.text == "🔍 Посмотреть утвержденные заявки")
async def view_approved_requests_by_month(message: Message):
    user = session.query(User).filter_by(tg_id=message.from_user.id).first()

    if not user or user.role != 'механик':
        await message.answer("У вас нет прав для просмотра утвержденных заявок.")
        return

    # Создаем список месяцев, начиная с текущего и до следующих 12 месяцев
    today = datetime.today()
    months = [(today + timedelta(days=30*i)).strftime("%B %Y") for i in range(12)]

    # Создаем кнопки для выбора месяца
    buttons = [[InlineKeyboardButton(text=month.capitalize(), callback_data=f"select_month:{month}")] for month in months]
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer("Выберите месяц для просмотра утвержденных заявок:", reply_markup=markup)

# Обработчик для выбора месяца
@dp.callback_query(lambda callback_query: callback_query.data.startswith("select_month:"))
async def handle_month_selection(callback_query: CallbackQuery):
    selected_month = callback_query.data.split(":")[1]

    # Запрашиваем первую страницу заявок для выбранного месяца
    await paginate_requests(callback_query.message, selected_month, page=1)
    await callback_query.answer()

# Функция для пагинации заявок с началом от самых старых к новым
async def paginate_requests(message: Message, selected_month: str, page: int = None):
    # Получаем месяц в формате datetime для фильтрации
    month_start = datetime.strptime(selected_month, "%B %Y")
    next_month = month_start + timedelta(days=31)

    # Фильтрация заявок за выбранный месяц, отсортированных от новых к старым
    approved_requests = session.query(Request).filter(
        Request.manager_approval_1 == True,
        Request.manager_approval_2 == True,
        Request.datetime_out >= month_start,
        Request.datetime_out < next_month
    ).order_by(Request.datetime_out.desc()).all()

    if not approved_requests:
        await message.answer(f"Нет утвержденных заявок за {selected_month}.")
        return

    # Рассчитываем количество страниц
    total_pages = ceil(len(approved_requests) / REQUESTS_PER_PAGE)
    
    # Если страница не указана, начинаем с последней (самой старой)
    if page is None:
        page = total_pages

    # Получаем заявки для текущей страницы
    start_index = (total_pages - page) * REQUESTS_PER_PAGE
    end_index = start_index + REQUESTS_PER_PAGE
    current_requests = approved_requests[start_index:end_index]

    # Формируем ответ с информацией о заявках
    response = f"Утвержденные заявки за {selected_month} (Страница {page}/{total_pages}):\n\n"
    for req in current_requests:
        response += (f"ID: {req.id}, ФИО: {req.employee_name}, Цель: {req.purpose}, "
                     f"Основание: {req.reason}, Дата и время: {req.datetime_out.strftime('%d-%m-%Y %H:%M')}, "
                     f"Адрес: {req.address}, С водителем: {'Да' if req.with_driver else 'Нет'}\n\n")

    # Кнопки для навигации (пагинация)
    buttons = []
    if page > 1:
        buttons.append(InlineKeyboardButton(text="⬅️ Вперед", callback_data=f"requests_page:{selected_month}:{page-1}"))
    if page < total_pages:
        buttons.append(InlineKeyboardButton(text="Назад ➡️", callback_data=f"requests_page:{selected_month}:{page+1}"))

    markup = InlineKeyboardMarkup(inline_keyboard=[buttons] if buttons else [])

    # Отправляем сообщение с заявками и пагинацией
    await message.answer(response, reply_markup=markup)

# Обработчик для смены страницы заявок
@dp.callback_query(lambda callback_query: callback_query.data.startswith("requests_page:"))
async def handle_request_pagination(callback_query: CallbackQuery):
    data = callback_query.data.split(":")
    selected_month = data[1]
    page = int(data[2])

    await paginate_requests(callback_query.message, selected_month, page)
    await callback_query.answer()

# Обработчик нажатия кнопки "Посмотреть роли пользователей"
@dp.message(lambda message: message.text == "👀 Посмотреть роли пользователей")
async def show_roles_command(message: Message):
    admin_user = session.query(User).filter_by(tg_id=message.from_user.id).first()

    if not admin_user or admin_user.role != 'администратор':
        await message.answer("У вас нет прав для выполнения этой команды.")
        return
    
    users = session.query(User).all()

    if not users:
        await message.answer("В базе данных нет пользователей.")
        return
    
    response = "Список пользователей:\n\n"
    for user in users:
        username = user.username if user.username else "Не указан"
        response += f"ID: {user.tg_id}, Full Name: {user.full_name}, Username: {username}, Роль: {user.role}\n"

    await message.answer(response)


# Обработчик нажатия кнопки "Удалить пользователя"
@dp.message(lambda message: message.text == "🗑️ Удалить пользователя")
async def start_user_deletion(message: Message):
    await show_user_page_with_rights_check(message, page=1)

# Функция для отображения страницы с пользователями с проверкой прав
async def show_user_page_with_rights_check(message: Message, page: int = 1):
    admin_user = session.query(User).filter_by(tg_id=message.from_user.id).first()

    if not admin_user or admin_user.role != 'администратор':
        await message.answer("У вас нет прав для выполнения этой команды.")
        return

    await show_user_page_without_rights_check(message, page)

# Функция для отображения страницы с пользователями без проверки прав
async def show_user_page_without_rights_check(message: Message, page: int = 1):
    users = session.query(User).all()

    if not users:
        await message.answer("В базе данных нет пользователей.")
        return

    # Рассчитываем количество страниц
    total_pages = ceil(len(users) / USERS_PER_PAGE)

    # Получаем пользователей для текущей страницы
    start_index = (page - 1) * USERS_PER_PAGE
    end_index = start_index + USERS_PER_PAGE
    current_users = users[start_index:end_index]

    # Создаем кнопки для пользователей
    buttons = [
        [InlineKeyboardButton(text=f"{user.full_name} ({user.username})", callback_data=f"delete_user:{user.tg_id}")]
        for user in current_users
    ]

    # Кнопки навигации для пагинации
    navigation_buttons = []
    if page > 1:
        navigation_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"user_page:{page - 1}"))
    if page < total_pages:
        navigation_buttons.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"user_page:{page + 1}"))

    if navigation_buttons:
        buttons.append(navigation_buttons)

    markup = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(f"Страница {page} из {total_pages}. Выберите пользователя для удаления:", reply_markup=markup)

# Обработчик для смены страницы с пользователями
@dp.callback_query(lambda callback_query: callback_query.data.startswith("user_page:"))
async def paginate_users(callback_query: CallbackQuery):
    page = int(callback_query.data.split(":")[1])
    await show_user_page_without_rights_check(callback_query.message, page)
    await callback_query.answer()

# Обработчик удаления пользователя
@dp.callback_query(lambda callback_query: callback_query.data.startswith("delete_user:"))
async def delete_user(callback_query: CallbackQuery):
    tg_id = int(callback_query.data.split(":")[1])

    user = session.query(User).filter_by(tg_id=tg_id).first()

    if not user:
        await callback_query.message.answer("Пользователь не найден.")
        await callback_query.answer()
        return

    session.delete(user)
    session.commit()

    await callback_query.message.answer(f"Пользователь {user.full_name} был удален.✔️")
    await callback_query.answer()

    # Обновляем список пользователей без повторной проверки прав
    await show_user_page_without_rights_check(callback_query.message, page=1)

# Добавляем новую функцию фоновой задачи для уведомления механиков
async def notify_mechanics_background():
    while True:
        await asyncio.sleep(10)  # Проверяем каждые 10 секунд

        approved_requests = session.query(Request).filter(
            Request.status == 'одобрена',
            Request.notified_mechanics == False
        ).all()

        for request in approved_requests:
            mechanic_users = session.query(User).filter_by(role='механик').all()

            if not mechanic_users:
                requester = session.query(User).filter_by(id=request.requester).first()
                if requester:
                    await bot.send_message(
                        chat_id=requester.tg_id,
                        text=f"Нет доступных механиков для заявки {request.id}."
                    )
                request.notified_mechanics = True
                session.commit()
                continue
            
            # Генерация PDF как BufferedInputFile
            pdf_file = generate_request_pdf(request)
            pdf_input_file = BufferedInputFile(pdf_file.getvalue(), filename="request_details.pdf")

            for mechanic in mechanic_users:
                try:
                    await bot.send_message(
                        chat_id=mechanic.tg_id,
                        text=(
                            f"Заявка {request.id} была одобрена:✅\n"
                            f"ФИО: {request.employee_name}\n"
                            f"Цель: {request.purpose}\n"
                            f"Дата и время: {request.datetime_out.strftime('%d-%m-%Y %H:%M')}\n"
                            f"Адрес: {request.address}\n"
                            f"С водителем: {'Да' if request.with_driver else 'Нет'}\n"
                            f"Примечания: {request.notes}\n"
                            f"Пожалуйста, подготовьте автомобиль."
                        )
                    )
                    
                    # Отправляем PDF файл через BufferedInputFile
                    await bot.send_document(
                        chat_id=mechanic.tg_id,
                        document=pdf_input_file,
                        caption="Подробности заявки в приложенном PDF."
                    )

                    logging.info(f"Уведомление отправлено механику {mechanic.full_name} (tg_id: {mechanic.tg_id})")
                except Exception as e:
                    logging.error(f"Ошибка при отправке сообщения механику {mechanic.full_name} (tg_id: {mechanic.tg_id}): {e}")

            request.notified_mechanics = True
            session.commit()

# Добавляем функцию для запуска фоновой задачи
async def on_startup():
    asyncio.create_task(notify_mechanics_background())
    logging.info("Фоновая задача для уведомления механиков запущена.")

# Функция для добавления администратора (если требуется)
async def add_admin():
    admin_tg_id = 726797566  # Замените на ваш Telegram ID

    # Проверяем, есть ли администратор с таким Telegram ID
    existing_admin = session.query(User).filter_by(tg_id=admin_tg_id).first()

    if not existing_admin:
        # Получаем данные администратора из Telegram
        try:
            chat_member = await bot.get_chat(admin_tg_id)
            full_name = f"{chat_member.first_name} {chat_member.last_name}" if chat_member.last_name else chat_member.first_name
            username = chat_member.username if chat_member.username else "Не указан"

            # Создаем администратора с правильным именем
            admin_user = User(tg_id=admin_tg_id, full_name=full_name, username=username, role='администратор')
            session.add(admin_user)
            session.commit()
            logging.info(f"Пользователь с Telegram ID {admin_tg_id} добавлен как администратор.")
        except Exception as e:
            logging.error(f"Не удалось добавить администратора: {e}")
    else:
        logging.info(f"Пользователь с Telegram ID {admin_tg_id} уже существует в базе.")

# Основная функция запуска бота
async def main():
    # Добавляем администратора, если необходимо
    await add_admin()

    # Запускаем фоновую задачу
    await on_startup()

    # Запускаем бота
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())

