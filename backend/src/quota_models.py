from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column as col, relationship

from .db import Base
from .models import Station, utcnow


class ShiftQuota(Base):
    """同片区、同营业日、同班次共用的一队人可派名额。"""
    __tablename__ = 'shift_quotas'
    __table_args__ = (
        UniqueConstraint('region', 'business_date', 'shift'),
        CheckConstraint('capacity BETWEEN 0 AND 60'),
    )
    id: Mapped[int] = col(primary_key=True)
    region: Mapped[str] = col(String(32))
    business_date: Mapped[date] = col(Date)
    shift: Mapped[str] = col(Enum('morning', 'afternoon', 'evening'))
    capacity: Mapped[int]
    updated_by: Mapped[str] = col(ForeignKey('users.username'))
    updated_at: Mapped[datetime] = col(DateTime, default=utcnow, onupdate=utcnow)
    allocations: Mapped[list['ShiftAllocation']] = relationship(back_populates='quota',
                                                                order_by='ShiftAllocation.id')


class ShiftAllocation(Base):
    """一张支援单或补派单对某班次名额的一次占用；核销核验后按实到人数结算。"""
    __tablename__ = 'shift_allocations'
    __table_args__ = (
        UniqueConstraint('kind', 'order_id', 'cycle'),
        CheckConstraint('planned BETWEEN 1 AND 6'),
        CheckConstraint('actual IS NULL OR actual BETWEEN 1 AND planned'),
        CheckConstraint("(state = 'held' AND actual IS NULL AND settled_at IS NULL) OR "
                        "(state = 'settled' AND actual IS NOT NULL AND settled_at IS NOT NULL)"),
    )
    id: Mapped[int] = col(primary_key=True)
    quota_id: Mapped[int] = col(ForeignKey('shift_quotas.id'), index=True)
    kind: Mapped[str] = col(Enum('support', 'recovery'))
    order_id: Mapped[int]
    cycle: Mapped[int] = col(default=1)
    station_code: Mapped[str] = col(ForeignKey('stations.code'))
    planned: Mapped[int]
    actual: Mapped[int | None]
    state: Mapped[str] = col(Enum('held', 'settled'), default='held')
    created_at: Mapped[datetime] = col(DateTime, default=utcnow)
    settled_at: Mapped[datetime | None] = col(DateTime)
    quota: Mapped[ShiftQuota] = relationship(back_populates='allocations')
    station: Mapped[Station] = relationship()
