"""上海证券交易时段的唯一常量定义。"""

from __future__ import annotations

from datetime import datetime

MORNING_CONTINUOUS_START_HHMM = 930
MORNING_SESSION_END_HHMM = 1130
AFTERNOON_SESSION_START_HHMM = 1300
CLOSING_AUCTION_END_HHMM = 1500
POST_CLOSE_FIXED_PRICE_END_HHMM = 1530


def hhmm(value: datetime) -> int:
    return value.hour * 100 + value.minute


def is_quote_trading_session(value: datetime) -> bool:
    current = hhmm(value)
    return (
        MORNING_CONTINUOUS_START_HHMM <= current <= MORNING_SESSION_END_HHMM
        or AFTERNOON_SESSION_START_HHMM <= current <= POST_CLOSE_FIXED_PRICE_END_HHMM
    )


def is_after_trading_day_complete(value: datetime) -> bool:
    return hhmm(value) > POST_CLOSE_FIXED_PRICE_END_HHMM
