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


class SupplyChainNodeType(str, Enum):
    """공급망 노드 유형 (architecture_plan.md §7.1)."""
    COMPANY = "COMPANY"                       # 상장 기업 본사
    FACTORY = "FACTORY"                       # 핵심 생산 공장
    PORT = "PORT"                             # 항구 / 물류 게이트웨이
    LOGISTICS_HUB = "LOGISTICS_HUB"          # 물류 허브 / 배송 센터
    RAW_MATERIAL_SITE = "RAW_MATERIAL_SITE"  # 원자재 생산지
    DISTRIBUTION_CENTER = "DISTRIBUTION_CENTER"  # 유통 센터


class SupplyChainRelationType(str, Enum):
    """공급망 에지(의존 관계) 유형."""
    SUPPLIES = "SUPPLIES"                     # A → B: A가 B에 부품/소재 공급
    MANUFACTURES_FOR = "MANUFACTURES_FOR"     # A → B: A가 B의 위탁 생산
    DISTRIBUTES_TO = "DISTRIBUTES_TO"         # A → B: A가 B로 물류 처리
    DEPENDS_ON = "DEPENDS_ON"                 # A → B: A가 B에 강하게 의존


class NodeRiskLevel(str, Enum):
    """지정학적/물리적 위험 수준."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
