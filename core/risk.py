import math

import config


def calculate_risk_levels(close_price: float, atr_value: float) -> tuple[float, float]:
    stop_loss = close_price - config.ATR_STOP_MULT * atr_value
    take_profit = close_price + config.ATR_TARGET_MULT * atr_value
    return round(stop_loss, 2), round(take_profit, 2)


def position_size(close_price: float) -> int | None:
    if not config.TRADING_CAPITAL:
        return None
    return math.floor(config.TRADING_CAPITAL * config.POSITION_PCT / close_price)
