from fastapi import HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from .models import Station, audit, utcnow
from .quota_models import ShiftAllocation, ShiftQuota

SHIFT_NAMES = {'morning': '早班', 'afternoon': '午后班', 'evening': '晚班'}
KIND_LABELS = {'support': '支援单', 'recovery': '补派单'}


def shift_label(quota):
    return f'{quota.region} {quota.business_date} {SHIFT_NAMES[quota.shift]}'


def lock_quota(db, region, day, shift):
    """锁定该片区该营业日班次的名额行；占用、改期、结算都在这把锁下串行。"""
    quota = db.scalar(
        select(ShiftQuota)
        .where(ShiftQuota.region == region, ShiftQuota.business_date == day, ShiftQuota.shift == shift)
        .with_for_update()
    )
    if quota is None:
        raise HTTPException(409, f'{region} {day} {SHIFT_NAMES[shift]}尚未配置可派人数，请先在名额台账设置')
    return quota


def occupied(db, quota_id):
    """在途占用按计划人数计，已结算按实到人数计。"""
    query = select(func.coalesce(func.sum(case(
        (ShiftAllocation.state == 'held', ShiftAllocation.planned), else_=ShiftAllocation.actual
    )), 0)).where(ShiftAllocation.quota_id == quota_id)
    return int(db.scalar(query))


def occupy(db, station_code, kind, order_id, headcount, day, shift):
    """支援获批、补派发出时占用名额。调用方已持有单据行锁，这里再锁名额行，两边同时提交也不会超派。"""
    region = db.get(Station, station_code).region
    quota = lock_quota(db, region, day, shift)
    used = occupied(db, quota.id)
    if used + headcount > quota.capacity:
        raise HTTPException(409, f'{shift_label(quota)}可派名额不足：还可派 {quota.capacity - used} 人，'
                                 f'本单需占 {headcount} 人')
    cycle = db.scalar(select(func.coalesce(func.max(ShiftAllocation.cycle), 0))
                      .where(ShiftAllocation.kind == kind, ShiftAllocation.order_id == order_id)) + 1
    db.add(ShiftAllocation(quota_id=quota.id, kind=kind, order_id=order_id, cycle=cycle,
                           station_code=station_code, planned=headcount))
    return quota


def held_allocation(db, kind, order_id):
    return db.scalar(select(ShiftAllocation).where(
        ShiftAllocation.kind == kind, ShiftAllocation.order_id == order_id,
        ShiftAllocation.state == 'held').with_for_update())


def settle(db, kind, order_id, actual):
    """核销或核验时按实到人数结算，空出的名额立即可再派。"""
    allocation = held_allocation(db, kind, order_id)
    if allocation is None:
        raise HTTPException(409, f'{KIND_LABELS[kind]}没有在途占用的名额可结算')
    if actual > allocation.planned:
        raise HTTPException(422, '实到人数不能超过已占名额')
    allocation.actual = actual
    allocation.state = 'settled'
    allocation.settled_at = utcnow()
    return allocation


def move(db, kind, order_id, station_code, day, shift):
    """改期：新班次有名额才把占用转过去并释放旧班次；失败抛错，原排班不动。"""
    allocation = held_allocation(db, kind, order_id)
    if allocation is None:
        raise HTTPException(409, f'{KIND_LABELS[kind]}没有在途占用的名额，不能改期')
    region = db.get(Station, station_code).region
    target = lock_quota(db, region, day, shift)
    if allocation.quota_id == target.id:
        return target
    used = occupied(db, target.id)
    if used + allocation.planned > target.capacity:
        raise HTTPException(409, f'{shift_label(target)}可派名额不足：还可派 {target.capacity - used} 人，'
                                 f'本单需占 {allocation.planned} 人，已保留原排班')
    allocation.quota_id = target.id
    return target


def allocation_record(row):
    return {
        'kind': row.kind, 'order_id': row.order_id, 'cycle': row.cycle,
        'station_code': row.station_code, 'station_name': row.station.name,
        'planned': row.planned, 'actual': row.actual, 'state': row.state,
        'created_at': row.created_at, 'settled_at': row.settled_at,
    }


def quota_record(row):
    held = sum(item.planned for item in row.allocations if item.state == 'held')
    settled = sum(item.actual for item in row.allocations if item.state == 'settled')
    return {
        'id': row.id, 'region': row.region, 'business_date': row.business_date, 'shift': row.shift,
        'capacity': row.capacity, 'held': held, 'settled': settled,
        'available': row.capacity - held - settled,
        'updated_by': row.updated_by, 'updated_at': row.updated_at,
        'allocations': [allocation_record(item) for item in row.allocations],
    }


def ledger(db, window, region=None):
    query = (select(ShiftQuota)
             .options(selectinload(ShiftQuota.allocations).joinedload(ShiftAllocation.station))
             .where(ShiftQuota.business_date.between(window.start, window.end))
             .order_by(ShiftQuota.business_date, ShiftQuota.region, ShiftQuota.shift))
    if region:
        query = query.where(ShiftQuota.region == region)
    return {'quotas': [quota_record(row) for row in db.scalars(query)]}


def save_quota(db, payload, actor):
    if not db.scalar(select(Station.code).where(Station.region == payload.region).limit(1)):
        raise HTTPException(422, '片区不存在')
    row = db.scalar(select(ShiftQuota).where(
        ShiftQuota.region == payload.region, ShiftQuota.business_date == payload.business_date,
        ShiftQuota.shift == payload.shift).with_for_update())
    used = occupied(db, row.id) if row else 0
    if payload.capacity < used:
        raise HTTPException(409, f'该班次已占用 {used} 人，可派人数不能调低到 {payload.capacity} 人')
    if row is None:
        row = ShiftQuota(region=payload.region, business_date=payload.business_date,
                         shift=payload.shift, capacity=payload.capacity, updated_by=actor)
        db.add(row)
    else:
        row.capacity = payload.capacity
        row.updated_by = actor
    db.flush()
    audit(db, actor, 'quota_saved', f'quota:{row.id}', region=row.region, date=str(row.business_date),
          shift=row.shift, capacity=row.capacity)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(409, '该班次名额正在更新，请重试') from error
    return quota_record(row)
