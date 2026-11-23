from datetime import date

from pydantic import Field

from .schemas import Input, Shift


class QuotaPlan(Input):
    region: str = Field(min_length=2, max_length=32)
    business_date: date
    shift: Shift
    capacity: int = Field(ge=0, le=60)


class ReschedulePlan(Input):
    business_date: date
    note: str = Field(min_length=12, max_length=400)
