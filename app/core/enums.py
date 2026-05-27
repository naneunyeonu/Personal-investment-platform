from enum import Enum


class UserRole(str, Enum):
    ADMIN = "ADMIN"
    USER = "USER"


class TransactionType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    DIVIDEND = "DIVIDEND"


class AssetClass(str, Enum):
    STOCK = "STOCK"
    ETF = "ETF"
    BOND = "BOND"
    CRYPTO = "CRYPTO"
    CASH = "CASH"


class MarketType(str, Enum):
    KRX = "KRX"        # 한국 거래소
    NASDAQ = "NASDAQ"
    NYSE = "NYSE"
    AMEX = "AMEX"
    OTHER = "OTHER"


class CurrencyCode(str, Enum):
    KRW = "KRW"
    USD = "USD"
    JPY = "JPY"
    EUR = "EUR"
    HKD = "HKD"
