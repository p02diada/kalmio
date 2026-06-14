from typing import Literal

from ninja import Schema

FeedbackKind = Literal["useful", "not_useful", "charger_busy", "wrong_data", "wrong_price"]


class FeedbackIn(Schema):
    route_plan_id: str
    kind: FeedbackKind
    comment: str = ""


class FeedbackOut(Schema):
    id: int
    status: str
