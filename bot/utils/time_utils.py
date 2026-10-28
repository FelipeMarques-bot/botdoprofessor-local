from datetime import datetime, timedelta, timezone

BR_TZ = timezone(timedelta(hours=-3))


def now_local() -> datetime:
    """Data/hora atual em Brasilia (UTC-3), naive para compatibilidade com o banco."""
    return datetime.now(BR_TZ).replace(tzinfo=None)