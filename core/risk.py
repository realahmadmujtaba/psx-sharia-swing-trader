import config


def calculate_risk_levels(close_price: float) -> tuple[float, float]:
    stop_loss = close_price * (1 - config.STOP_LOSS_PCT)
    take_profit = close_price * (1 + config.TAKE_PROFIT_PCT)
    return round(stop_loss, 2), round(take_profit, 2)
