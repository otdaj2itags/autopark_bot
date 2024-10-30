from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()

# Модель пользователя
class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)  # Уникальный идентификатор пользователя
    tg_id = Column(Integer, unique=True)    # Telegram ID пользователя
    full_name = Column(String)              # ФИО пользователя
    username = Column(String, nullable=True)  # Никнейм пользователя (опционально)
    role = Column(String)                   # Роль пользователя (заказчик, менеджер, механик, безопасность)

    requests = relationship("Request", back_populates="user")  # Связь с заявками

# Модель заявки
class Request(Base):
    __tablename__ = 'requests'
    id = Column(Integer, primary_key=True)  # Уникальный идентификатор заявки
    employee_name = Column(String)          # ФИО сотрудника
    purpose = Column(String)                # Цель поездки
    reason = Column(String)                 # Основание для поездки
    datetime_out = Column(DateTime)         # Дата и время выезда
    address = Column(String)                # Адрес назначения
    business_trip = Column(Boolean)         # Служебный (True) или личный (False) выезд
    with_driver = Column(Boolean)           # С водителем (True) или без (False)
    notes = Column(String, nullable=True)   # Примечания (опционально)
    status = Column(String)                 # Статус заявки (создана, на согласовании, одобрена, отклонена)
    manager_approval_1 = Column(Boolean)    # Одобрение первого менеджера
    manager_approval_2 = Column(Boolean)    # Одобрение второго менеджера
    requester = Column(Integer, ForeignKey('users.id'))  # ID пользователя, создавшего заявку
    log = Column(String, nullable=True)     # Лог действий для заявки
    notified_mechanics = Column(Boolean, default=False) 

    user = relationship("User", back_populates="requests")  # Связь с пользователем

# Создание и настройка базы данных
engine = create_engine('sqlite:///autopark.db', echo=True)

# Создаём таблицы, если они ещё не созданы
Base.metadata.create_all(engine)




