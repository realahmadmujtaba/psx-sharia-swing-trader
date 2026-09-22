import math

import config


def calculate_risk_levels(close_price: float, atr_value: float, setup: str = "MEAN_REVERSION",
                          ema_50: float | None = None) -> tuple[float, float]:
    """Entry-time volatility stop and mean-reversion target."""
    take_profit = close_price + config.ATR_TARGET_MULT * atr_value
    stop_loss = close_price - config.ATR_STOP_MULT * atr_value

    return round(stop_loss, 2), round(take_profit, 2)


def position_size(close_price: float, atr_value: float | None = None,
                  equity: float | None = None, stop_loss: float | None = None) -> int | None:
    """Shares to buy so that a stop-out costs RISK_PER_TRADE_PCT of equity.

    Capped by MAX_POSITION_PCT, because a tight stop would otherwise ask for more
    cash than the account holds.
    """
    equity = equity or config.TRADING_CAPITAL
    if not equity:
        return None

    if stop_loss is not None:
        risk_per_share = close_price - stop_loss
    elif atr_value:
        risk_per_share = config.ATR_STOP_MULT * atr_value
    else:
        return math.floor(equity * config.POSITION_PCT / close_price)

    if risk_per_share <= 0:
        return None

    by_risk = equity * config.RISK_PER_TRADE_PCT / risk_per_share
    by_cash = equity * config.MAX_POSITION_PCT / close_price
    return math.floor(min(by_risk, by_cash))
