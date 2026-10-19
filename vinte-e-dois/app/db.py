import os
import hashlib
from datetime import datetime, timezone

from sqlalchemy import create_engine, Column, ForeignKey, Integer, String, Float, DateTime, Text
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("VDB_DATA", os.path.join(ROOT, "data"))
os.makedirs(DATA_DIR, exist_ok=True)
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///" + os.path.join(DATA_DIR, "db.sqlite3"))
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
Base = declarative_base()

APP_SECRET = os.environ.get("APP_SECRET", "vd22-troque-em-producao")
FX_USDT_BRL = float(os.environ.get("FX_USDT_BRL", "6.0"))


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def pkdf(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String(120))
    cpf = Column(String(11), unique=True, index=True)
    birth_date = Column(String(10))
    password_salt = Column(String(32))
    password_hash = Column(String(120))
    balance_brl = Column(Integer, default=0)
    balance_usdt = Column(Integer, default=0)
    self_excluded_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class LedgerEntry(Base):
    __tablename__ = "ledger"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    currency = Column(String(5))
    kind = Column(String(20))
    amount_cents = Column(Integer)
    balance_after_cents = Column(Integer)
    ref = Column(String(60), default="")
    ts = Column(DateTime, default=utcnow)


class Event(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True)
    kind = Column(String(12))
    title = Column(String(200))
    league = Column(String(120), default="")
    starts_at = Column(DateTime, nullable=True)
    status = Column(String(12), default="SCHEDULED")
    xg_home = Column(Float, default=1.5)
    xg_away = Column(Float, default=1.1)
    state = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class Market(Base):
    __tablename__ = "markets"
    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, index=True)
    key = Column(String(10))
    title = Column(String(120))
    margin = Column(Float, default=0.06)
    status = Column(String(10), default="OPEN")
    fair_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    outcomes = relationship("Outcome", order_by="Outcome.id", cascade="all, delete-orphan")


class Outcome(Base):
    __tablename__ = "outcomes"
    id = Column(Integer, primary_key=True)
    market_id = Column(Integer, ForeignKey("markets.id"), index=True)
    label = Column(String(40))
    odd = Column(Float, default=2.0)
    stake_brl = Column(Integer, default=0)
    stake_usdt = Column(Integer, default=0)


class Bet(Base):
    __tablename__ = "bets"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    market_id = Column(Integer, index=True)
    outcome_id = Column(Integer)
    outcome_label = Column(String(40))
    currency = Column(String(5))
    stake_cents = Column(Integer)
    odd = Column(Float)
    potential_cents = Column(Integer)
    status = Column(String(10), default="OPEN")
    cashout_cents = Column(Integer, default=0)
    placed_at = Column(DateTime, default=utcnow)


class Tx(Base):
    __tablename__ = "txs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    kind = Column(String(10))
    currency = Column(String(5))
    amount_cents = Column(Integer)
    status = Column(String(10), default="PENDING")
    method = Column(String(8), default="PIX")
    external_ref = Column(String(40), default="", index=True)
    dest = Column(String(160), default="")
    openpix_charge_id = Column(String(60), nullable=True)
    ts = Column(DateTime, default=utcnow)
    done_ts = Column(DateTime, nullable=True)


class GameRound(Base):
    __tablename__ = "game_rounds"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    currency = Column(String(5))
    stake_cents = Column(Integer)
    client_seed = Column(String(80))
    server_seed = Column(String(80))
    seed_hash = Column(String(80))
    crash_point = Column(Float)
    started_at = Column(DateTime, default=utcnow)
    cashed_mult = Column(Float, nullable=True)
    payout_cents = Column(Integer, default=0)
    status = Column(String(10), default="RUNNING")
