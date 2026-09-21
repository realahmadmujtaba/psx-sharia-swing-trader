import math

import config


def calculate_risk_levels(close_price: float, atr_value: float) -> tuple[float, float]:
    stop_loss = close_price - config.ATR_STOP_MULT * atr_value
    take_profit = close_price + config.ATR_TARGET_MULT * atr_value
    return round(stop_loss, 2), round(take_profit, 2)


def position_size(close_price: float, atr_value: float | None = None,
                  equity: float | None = None) -> int | None:
    """Shares to buy so that a stop-out costs RISK_PER_TRADE_PCT of equity.

    Capped by MAX_POSITION_PCT, because a tight stop would otherwise ask for more
    cash than the account holds.
    """
    equity = equity or config.TRADING_CAPITAL
    if not equity:
        return None

    if not atr_value:
        return math.floor(equity * config.POSITION_PCT / close_price)

    risk_per_share = config.ATR_STOP_MULT * atr_value
    if risk_per_share <= 0:
        return None

    by_risk = equity * config.RISK_PER_TRADE_PCT / risk_per_share
    by_cash = equity * config.MAX_POSITION_PCT / close_price
    return math.floor(min(by_risk, by_cash))
