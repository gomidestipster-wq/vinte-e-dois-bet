import json
import hmac
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from .db import (
    Base, engine, SessionLocal, APP_SECRET, FX_USDT_BRL,
    User, LedgerEntry, Event, Market, Outcome, Bet, Tx, GameRound,
    utcnow, pkdf,
)
from . import engine as eng
from . import pix

Base.metadata.create_all(engine)
app = FastAPI(title="Vinte e Dois Bet")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "static")
USDT_ADDRESS = os.environ.get("USDT_ADDRESS", "")
CNPJ = "67.064.999/0001-03"


def get_db():
    d = SessionLocal()
    try:
        yield d
    finally:
        d.close()


def _sign(kind: str, key: str) -> str:
    return hmac.new(APP_SECRET.encode(), f"{kind}:{key}".encode(), "sha256").hexdigest()[:40]


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    tok = request.cookies.get("tok") or ""
    if ":" not in tok:
        raise HTTPException(401, "faça login")
    uid, sig = tok.split(":", 1)
    u = db.get(User, int(uid))
    if not u or sig != _sign("user", str(u.id)):
        raise HTTPException(401, "faça login")
    return u


def require_admin(request: Request):
    adm = os.environ.get("ADMIN_PASSWORD", "222222")
    tok = request.cookies.get("adm") or ""
    if tok != _sign("admin", adm):
        raise HTTPException(401, "área restrita")


def move_balance(db: Session, u: User, cur: str, cents: int, kind: str, ref: str = ""):
    attr = "balance_brl" if cur == "BRL" else "balance_usdt"
    new = getattr(u, attr) + cents
    if new < 0:
        raise HTTPException(400, "saldo insuficiente")
    setattr(u, attr, new)
    db.add(LedgerEntry(user_id=u.id, currency=cur, kind=kind, amount_cents=cents, balance_after_cents=new, ref=ref))
    db.flush()
    return new


# ---------- modelos de entrada ----------

class RegisterIn(BaseModel):
    name: str
    cpf: str
    birth_date: str
    password: str


class LoginIn(BaseModel):
    cpf: str
    password: str


class AdminLoginIn(BaseModel):
    password: str


class MoneyIn(BaseModel):
    currency: str = "BRL"
    amount_cents: int
    method: str = "PIX"
    dest: str = ""


class BetIn(BaseModel):
    market_id: int
    outcome_id: int
    stake_cents: int
    currency: str = "BRL"


class CrashStartIn(BaseModel):
    client_seed: str
    currency: str = "BRL"
    stake_cents: int


class EventIn(BaseModel):
    kind: str
    title: str
    league: str = ""
    starts_at: Optional[datetime] = None
    xg_home: float = 1.5
    xg_away: float = 1.1
    labels: List[str] = []
    fair: dict = {}
    margin: float = 0.12


class FairIn(BaseModel):
    ps: dict
    margin: Optional[float] = None


class LiveIn(BaseModel):
    minute: int
    sh: int
    sa: int


class ResolveIn(BaseModel):
    label: Optional[str] = None


# ---------- visões ----------

def market_cap_cents(m: Market) -> int:
    pool = sum(o.stake_brl + o.stake_usdt / FX_USDT_BRL for o in m.outcomes)
    if pool <= 0:
        return 500_000
    return int(min(500_000, max(5_000, pool * 0.10)))


def market_view(m: Market) -> dict:
    return {
        "id": m.id, "key": m.key, "title": m.title, "status": m.status,
        "outcomes": [{"id": o.id, "label": o.label, "odd": o.odd} for o in m.outcomes],
        "cap_cents": market_cap_cents(m),
        "stake_brl_cents": int(sum(o.stake_brl + o.stake_usdt / FX_USDT_BRL for o in m.outcomes)),
    }


def event_light(e: Event) -> dict:
    return {"id": e.id, "kind": e.kind, "title": e.title, "league": e.league,
            "starts_at": e.starts_at.isoformat() if e.starts_at else None, "status": e.status}


def event_view(e: Event, db: Session) -> dict:
    mkts = db.query(Market).filter(Market.event_id == e.id).order_by(Market.id).all()
    return {**event_light(e), "state": json.loads(e.state) if e.state else None,
            "markets": [market_view(m) for m in mkts]}


# ---------- motor ----------

def model_probs(ev: Event, m: Market):
    if ev.kind == "FOOTBALL":
        st = json.loads(ev.state) if ev.state else {}
        minute, sh, sa = st.get("minute", 0), st.get("sh", 0), st.get("sa", 0)
        f = max(0.0, (90 - minute) / 90.0)
        if minute > 0 and f > 0:
            p = eng.probs_live(sh, sa, ev.xg_home * f, ev.xg_away * f)
        elif f == 0:
            p = eng.probs_live(sh, sa, 0.0, 0.0)
        else:
            p = eng.probs(ev.xg_home, ev.xg_away)
        if m.key == "1X2":
            return {"H": p["H"], "D": p["D"], "A": p["A"]}
        if m.key == "OU25":
            return {"O": p["O"], "U": 1 - p["O"]}
        if m.key == "ACG":
            return {"SIM": p["AC"], "NAO": 1 - p["AC"]}
    if ev.kind == "POLITICS" and m.fair_json:
        return json.loads(m.fair_json)
    return None


def reprice_market(db: Session, ev: Event, m: Market, new_margin: Optional[float] = None) -> list:
    ps = model_probs(ev, m)
    if ps is None:
        return []
    margin = new_margin if new_margin is not None else m.margin
    if new_margin is not None:
        m.margin = new_margin
    odds = {o.label: o.odd for o in m.outcomes}
    probs = {k: ps.get(k, 1e-4) for k in odds}
    novo = eng.price(probs, margin)
    stakes = {o.label: o.stake_brl + o.stake_usdt / FX_USDT_BRL for o in m.outcomes}
    pool = sum(stakes.values())
    teto = min(250_000, max(2_500, pool * 0.05)) if pool > 0 else 2_500
    moves = eng.rebalance(novo, stakes, teto=teto)
    for o in m.outcomes:
        if o.label in novo:
            o.odd = novo[o.label]
    db.commit()
    return moves


def winning_label(m: Market, st: dict):
    sh, sa = st["sh"], st["sa"]
    if m.key == "1X2":
        return "H" if sh > sa else ("D" if sh == sa else "A")
    if m.key == "OU25":
        return "O" if sh + sa >= 3 else "U"
    if m.key == "ACG":
        return "SIM" if sh > 0 and sa > 0 else "NAO"
    return None


def settle_market(db: Session, ev: Event, m: Market, winner: Optional[str]):
    bets = db.query(Bet).filter(Bet.market_id == m.id, Bet.status == "OPEN").all()
    for b in bets:
        u = db.get(User, b.user_id)
        if winner is None:
            move_balance(db, u, b.currency, b.stake_cents, "BET_VOID", f"bet{b.id}")
            b.status = "VOID"
        elif b.outcome_label == winner:
            pay = int(b.stake_cents * b.odd)
            move_balance(db, u, b.currency, pay, "BET_WON", f"bet{b.id}")
            b.status = "WON"
        else:
            b.status = "LOST"
    for o in m.outcomes:
        pass
    m.status = "CLOSED"
    db.commit()


# ---------- rotas ----------

@app.get("/health")
def health():
    return {"ok": True, "brand": "Vinte e Dois Bet", "cnpj": CNPJ}


@app.post("/api/register")
def register(b: RegisterIn, response: Response, db: Session = Depends(get_db)):
    cpf = "".join(ch for ch in b.cpf if ch.isdigit())
    if len(cpf) != 11:
        raise HTTPException(400, "CPF inválido")
    if db.query(User).filter(User.cpf == cpf).first():
        raise HTTPException(400, "CPF já cadastrado")
    try:
        bd = datetime.strptime(b.birth_date, "%Y-%m-%d").date()
        age = (utcnow().date() - bd).days // 365.25
    except ValueError:
        raise HTTPException(400, "data inválida")
    if age < 18:
        raise HTTPException(400, "é preciso ter 18 anos ou mais")
    salt = secrets.token_hex(8)
    u = User(name=b.name[:120], cpf=cpf, birth_date=b.birth_date,
             password_salt=salt, password_hash=pkdf(b.password, salt))
    db.add(u)
    db.commit()
    response.set_cookie("tok", f"{u.id}:{_sign('user', str(u.id))}", httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
    return {"ok": True}


@app.post("/api/login")
def login(b: LoginIn, response: Response, db: Session = Depends(get_db)):
    cpf = "".join(ch for ch in b.cpf if ch.isdigit())
    u = db.query(User).filter(User.cpf == cpf).first()
    if not u or u.password_hash != pkdf(b.password, u.password_salt):
        raise HTTPException(401, "CPF ou senha errados")
    response.set_cookie("tok", f"{u.id}:{_sign('user', str(u.id))}", httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
    return {"ok": True}


@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie("tok")
    return {"ok": True}


@app.get("/api/me")
def me(u: User = Depends(current_user)):
    return {"name": u.name, "cpf": u.cpf, "birth_date": u.birth_date,
            "balance_brl": u.balance_brl, "balance_usdt": u.balance_usdt,
            "self_excluded_until": u.self_excluded_until.isoformat() if u.self_excluded_until else None}


@app.post("/api/me/self-exclude")
def self_exclude(days: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    u.self_excluded_until = utcnow() + timedelta(days=max(1, min(days, 365)))
    db.commit()
    return {"ok": True}


@app.post("/api/wallet/deposit")
def deposit(b: MoneyIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if b.amount_cents < 100:
        raise HTTPException(400, "mínimo R$ 1,00 / 1 USDT")
    tx = Tx(user_id=u.id, kind="DEPOSIT", currency=b.currency, amount_cents=b.amount_cents,
            method=b.method.upper()[:4], external_ref=secrets.token_urlsafe(9).upper())
    db.add(tx)
    db.commit()
    out = {"txid": tx.external_ref}
    if b.currency == "USDT":
        out["usdt_address"] = USDT_ADDRESS
        out["usdt_network"] = "solana"
    else:
        ch, err = None, ""
        try:
            ch = pix.create_charge(tx.external_ref, b.amount_cents)
        except Exception as ex:
            err = str(ex)
        if ch and ch.get("chargeId"):
            tx.openpix_charge_id = ch["chargeId"]
            db.commit()
        if ch and (ch.get("emv") or ch.get("qrB64")):
            out["qr"] = ("data:image/png;base64," + ch["qrB64"]) if ch.get("qrB64") \
                else pix.emv_to_qr_data_url(ch["emv"])
            if ch.get("qrUrl"):
                out["qr"] = ch["qrUrl"]
            if ch.get("emv"):
                out["emv"] = ch["emv"]
        elif err:
            out["warn"] = "gateway: " + err[:140]
    return out


@app.post("/api/wallet/withdraw")
def withdraw(b: MoneyIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if b.amount_cents < 100:
        raise HTTPException(400, "mínimo R$ 1,00 / 1 USDT")
    tx = Tx(user_id=u.id, kind="WITHDRAW", currency=b.currency, amount_cents=b.amount_cents,
            method="MANUAL", dest=b.dest[:160])
    db.add(tx)
    db.commit()
    return {"ok": True}


@app.get("/api/wallet/txs")
def txs(u: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(LedgerEntry).filter(LedgerEntry.user_id == u.id).order_by(LedgerEntry.id.desc()).limit(30).all()
    return {"txs": [{"kind": r.kind, "amount_cents": r.amount_cents, "currency": r.currency} for r in rows]}


@app.get("/api/events")
def events(kind: str = "", status: str = "", db: Session = Depends(get_db)):
    q = db.query(Event)
    if kind:
        q = q.filter(Event.kind == kind)
    if status:
        q = q.filter(Event.status == status)
    evs = q.order_by(func.coalesce(Event.starts_at, Event.created_at).asc(), Event.id.asc()).all()
    return {"events": [event_light(e) for e in evs]}


@app.get("/api/events/{eid}")
def event_detail(eid: int, db: Session = Depends(get_db)):
    e = db.get(Event, eid)
    if not e:
        raise HTTPException(404, "não existe")
    return event_view(e, db)


@app.post("/api/bets")
def place_bet(b: BetIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if b.currency not in ("BRL", "USDT"):
        raise HTTPException(400, "moeda inválida")
    if u.self_excluded_until and u.self_excluded_until > utcnow():
        raise HTTPException(400, "conta em autoexclusão")
    m = db.get(Market, b.market_id)
    e = db.get(Event, m.event_id) if m else None
    if not m or not e or m.status != "OPEN" or e.status in ("FINISHED", "CANCELLED"):
        raise HTTPException(400, "mercado fechado")
    o = db.get(Outcome, b.outcome_id)
    if not o or o.market_id != m.id:
        raise HTTPException(400, "mercado não existe")
    cap = market_cap_cents(m)
    if b.stake_cents < 10:
        raise HTTPException(400, "stake mínima de 10 centavos")
    if b.stake_cents > cap:
        raise HTTPException(400, f"stake acima do limite do mercado ({cap // 100} reais)")
    db.execute(select(User).where(User.id == u.id).with_for_update())
    odd = o.odd
    pot = int(b.stake_cents * odd)
    move_balance(db, u, b.currency, -b.stake_cents, "BET_PLACED", f"bet-{b.market_id}-{o.id}")
    bet = Bet(user_id=u.id, market_id=m.id, outcome_id=o.id, outcome_label=o.label, currency=b.currency,
              stake_cents=b.stake_cents, odd=odd, potential_cents=pot)
    db.add(bet)
    db.flush()
    if b.currency == "BRL":
        o.stake_brl += b.stake_cents
    else:
        o.stake_usdt += b.stake_cents
    db.commit()
    moves = reprice_market(db, e, m)
    now = {oo.label: oo.odd for oo in m.outcomes}
    return {"bet_id": bet.id, "odd": odd, "potential_cents": pot, "moves": moves, "odds": now}


@app.post("/api/bets/{bid}/cashout")
def cashout(bid: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    b = db.get(Bet, bid)
    if not b or b.user_id != u.id or b.status != "OPEN":
        raise HTTPException(400, "aposta não encontrada")
    e = db.get(Event, b.market_id and db.get(Market, b.market_id).event_id)
    if e and e.status in ("FINISHED", "CANCELLED"):
        raise HTTPException(400, "mercado já encerrou")
    o = db.get(Outcome, b.outcome_id)
    v = eng.cashout_value(b.stake_cents, b.odd, o.odd)
    if v < 10:
        raise HTTPException(400, "sem valor de resgate neste momento")
    move_balance(db, u, b.currency, v, "CASHOUT", f"bet{b.id}")
    if b.currency == "BRL":
        o.stake_brl -= b.stake_cents
    else:
        o.stake_usdt -= b.stake_cents
    b.status = "CASHED"
    b.cashout_cents = v
    db.commit()
    m = db.get(Market, b.market_id)
    reprice_market(db, e, m)
    return {"cashout_cents": v}


@app.get("/api/bets")
def my_bets(u: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(Bet).filter(Bet.user_id == u.id).order_by(Bet.id.desc()).limit(40).all()
    return {"bets": [{"id": b.id, "market_id": b.market_id, "label": b.outcome_label, "odd": b.odd,
                      "stake_cents": b.stake_cents, "status": b.status, "currency": b.currency,
                      "potential_cents": b.potential_cents, "cashout_cents": b.cashout_cents} for b in rows]}


# ---------- crash ----------

@app.post("/api/crash/start")
def crash_start(b: CrashStartIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if u.self_excluded_until and u.self_excluded_until > utcnow():
        raise HTTPException(400, "conta em autoexclusão")
    if b.stake_cents < 10:
        raise HTTPException(400, "stake mínima de 10 centavos")
    srv = secrets.token_hex(16)
    cp, h = eng.crash_point(srv, b.client_seed[:80])
    db.execute(select(User).where(User.id == u.id).with_for_update())
    move_balance(db, u, b.currency, -b.stake_cents, "CRASH_STAKE", f"round-")
    g = GameRound(user_id=u.id, currency=b.currency, stake_cents=b.stake_cents,
                  client_seed=b.client_seed[:80], server_seed=srv, seed_hash=h, crash_point=cp)
    db.add(g)
    db.commit()
    return {"round_id": g.id}


def _crash_view(g: GameRound, reveal: bool):
    t = (utcnow() - g.started_at).total_seconds()
    crashed = t >= eng.crash_time(g.crash_point)
    out = {"round_id": g.id, "stake_cents": g.stake_cents,
           "status": "CRASHED" if crashed else ("CASHED" if g.cashed_mult else "RUNNING"),
           "mult": round(g.crash_point if crashed else eng.mult_at(g.crash_point, t), 3),
           "seed_hash": g.seed_hash[:16], "client_seed": g.client_seed,
           "cashed_mult": g.cashed_mult, "payout_cents": g.payout_cents}
    if crashed or reveal:
        out["crash_point"] = g.crash_point
        out["server_seed"] = g.server_seed
    return out


@app.get("/api/crash/{gid}")
def crash_get(gid: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    g = db.get(GameRound, gid)
    if not g or g.user_id != u.id:
        raise HTTPException(404, "rodada não existe")
    return _crash_view(g, reveal=False)


@app.post("/api/crash/{gid}/cashout")
def crash_cashout(gid: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    g = db.get(GameRound, gid)
    if not g or g.user_id != u.id:
        raise HTTPException(404, "rodada não existe")
    if g.cashed_mult:
        raise HTTPException(400, "já resgatou")
    t = (utcnow() - g.started_at).total_seconds()
    tc = eng.crash_time(g.crash_point)
    if t >= tc:
        raise HTTPException(400, "deu crash antes")
    m = eng.mult_at(g.crash_point, t)
    pay = int(g.stake_cents * m)
    move_balance(db, u, g.currency, pay, "CRASH_PAYOUT", f"round{g.id}")
    g.cashed_mult = round(m, 3)
    g.payout_cents = pay
    db.commit()
    return {"cashout_cents": pay, "mult": round(m, 3)}


# ---------- admin / console da casa ----------

@app.post("/api/admin/login")
def admin_login(b: AdminLoginIn, response: Response):
    adm = os.environ.get("ADMIN_PASSWORD", "222222")
    if b.password != adm:
        raise HTTPException(401, "senha errada")
    response.set_cookie("adm", _sign("admin", adm), httponly=True, samesite="lax", max_age=60 * 60 * 24 * 7)
    return {"ok": True}


@app.post("/api/admin/events")
def admin_create_event(b: EventIn, db: Session = Depends(get_db), _a=None, request: Request = None):
    require_admin_from(request)
    e = Event(kind=b.kind.upper(), title=b.title[:200], league=b.league[:120],
              starts_at=b.starts_at or (utcnow() + timedelta(hours=2)), xg_home=b.xg_home, xg_away=b.xg_away)
    db.add(e)
    db.commit()
    if e.kind == "FOOTBALL":
        specs = [("1X2", "Resultado (90 min)", [("H", "Casa"), ("D", "Empate"), ("A", "Fora")], 0.06),
                 ("OU25", "Mais/Menos 2.5 gols", [("O", "Mais 2.5"), ("U", "Menos 2.5")], 0.065),
                 ("ACG", "Ambas marcam", [("SIM", "Sim"), ("NAO", "Não")], 0.065)]
        for key, title, outs, mg in specs:
            m = Market(event_id=e.id, key=key, title=title, margin=mg)
            db.add(m)
            db.flush()
            for lab, lbl in outs:
                db.add(Outcome(market_id=m.id, label=lab, odd=2.0))
            db.flush()
            reprice_market(db, e, m)
    elif e.kind == "POLITICS":
        labs = b.labels[:8]
        if len(labs) < 2:
            raise HTTPException(400, "política precisa de pelo menos 2 opções")
        fair = {l: float(b.fair.get(l, 1.0 / len(labs))) for l in labs}
        m = Market(event_id=e.id, key="WINNER", title=b.title[:120], margin=b.margin, fair_json=json.dumps(fair))
        db.add(m)
        db.flush()
        for l in labs:
            db.add(Outcome(market_id=m.id, label=l, odd=2.0))
        db.flush()
        reprice_market(db, e, m)
    else:
        raise HTTPException(400, "tipo inválido (FOOTBALL|POLITICS)")
    db.commit()
    return {"event_id": e.id}


def require_admin_from(request: Request):
    if request is None:
        return
    require_admin(request)


@app.post("/api/admin/markets/{mid}/fair")
def admin_fair(mid: int, b: FairIn, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    m = db.get(Market, mid)
    if not m:
        raise HTTPException(404, "não existe")
    e = db.get(Event, m.event_id)
    if e.kind == "POLITICS":
        m.fair_json = json.dumps({o.label: float(b.ps.get(o.label, 1e-4)) for o in m.outcomes})
    moves = reprice_market(db, e, m, b.margin)
    return {"moves": moves}


@app.post("/api/admin/markets/{mid}/resolve")
def admin_resolve(mid: int, b: ResolveIn, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    m = db.get(Market, mid)
    if not m or m.status != "OPEN":
        raise HTTPException(400, "mercado fechado")
    e = db.get(Event, m.event_id)
    winner = None
    if b.label is not None:
        if e.kind == "FOOTBALL":
            st = json.loads(e.state) if e.state else {}
            winner = winning_label(m, st)
        else:
            valid = [o.label for o in m.outcomes]
            if b.label not in valid:
                raise HTTPException(400, "opção inválida")
            winner = b.label
    settle_market(db, e, m, winner)
    e.status = "FINISHED" if all(x.status != "OPEN" for x in db.query(Market).filter(Market.event_id == e.id).all()) else e.status
    db.commit()
    return {"ok": True}


@app.post("/api/live/{eid}")
def live_state(eid: int, b: LiveIn, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    e = db.get(Event, eid)
    if not e:
        raise HTTPException(404, "não existe")
    old = json.loads(e.state) if e.state else {"minute": 0, "sh": 0, "sa": 0}
    if b.sh < old["sh"] or b.sa < old["sa"] or b.minute < old["minute"]:
        raise HTTPException(400, "estado inconsistente")
    st = {"minute": b.minute, "sh": b.sh, "sa": b.sa}
    e.state = json.dumps(st)
    e.status = "LIVE"
    done = b.minute >= 90
    if done:
        e.status = "FINISHED"
    db.commit()
    moves = []
    for m in db.query(Market).filter(Market.event_id == eid).all():
        if m.status == "OPEN":
            if done:
                settle_market(db, e, m, winning_label(m, st) if m.key != "WINNER" else None)
            else:
                moves += reprice_market(db, e, m)
    return {"event_id": eid, "state": st, "finished": done, "moves": moves}


@app.get("/api/admin/deposits")
def admin_deposits(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    rows = db.query(Tx).filter(Tx.kind == "DEPOSIT").order_by(Tx.id.desc()).limit(50).all()
    return {"txs": [{"id": t.id, "user_id": t.user_id, "currency": t.currency, "amount_cents": t.amount_cents,
                     "status": t.status, "txid": t.external_ref} for t in rows]}


@app.get("/api/admin/withdrawals")
def admin_withdrawals(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    rows = db.query(Tx).filter(Tx.kind == "WITHDRAW").order_by(Tx.id.desc()).limit(50).all()
    return {"txs": [{"id": t.id, "user_id": t.user_id, "currency": t.currency, "amount_cents": t.amount_cents,
                     "status": t.status, "dest": t.dest} for t in rows]}


def _finalize_tx(db: Session, tx: Tx):
    if tx.status != "PENDING":
        raise HTTPException(400, "já processada")
    u = db.get(User, tx.user_id)
    if tx.kind == "DEPOSIT":
        move_balance(db, u, tx.currency, tx.amount_cents, "DEPOSIT", f"tx{tx.id}")
    else:
        move_balance(db, u, tx.currency, -tx.amount_cents, "WITHDRAW", f"tx{tx.id}")
    tx.status = "DONE"
    tx.done_ts = utcnow()
    db.commit()


@app.post("/api/admin/deposits/{tid}/confirm")
def admin_confirm_deposit(tid: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    tx = db.get(Tx, tid)
    if not tx or tx.kind != "DEPOSIT":
        raise HTTPException(404, "não existe")
    _finalize_tx(db, tx)
    return {"ok": True}


@app.post("/api/admin/withdrawals/{tid}/approve")
def admin_approve_withdraw(tid: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    tx = db.get(Tx, tid)
    if not tx or tx.kind != "WITHDRAW":
        raise HTTPException(404, "não existe")
    _finalize_tx(db, tx)
    return {"ok": True}


@app.get("/api/admin/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    users = db.query(func.count(User.id)).scalar()
    open_bets = db.query(Bet).filter(Bet.status == "OPEN").all()
    exposure = sum(b.stake_cents + (b.stake_cents / FX_USDT_BRL if b.currency == "USDT" else 0) for b in open_bets)
    won = db.query(func.sum(LedgerEntry.amount_cents)).filter(LedgerEntry.kind == "BET_WON").scalar() or 0
    staked = -db.query(func.sum(LedgerEntry.amount_cents)).filter(LedgerEntry.kind == "BET_PLACED").scalar() or 0
    rounds = db.query(func.count(GameRound.id)).scalar()
    return {"usuarios": users, "apostas_abertas": len(open_bets), "exposicao_aberta_brl": round(exposure / 100, 2),
            "apostado_brl": round(staked / 100, 2), "pago_brl": round(won / 100, 2), "rodadas_crash": rounds}


@app.post("/api/webhook/pix")
async def webhook_pix(request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    sig = request.headers.get("X-VD22-Signature", "")
    if sig:
        expect = hmac.new(APP_SECRET.encode(), body, "sha256").hexdigest()
        if not hmac.compare_digest(sig, expect):
            raise HTTPException(401, "assinatura inválida")
    try:
        d = json.loads(body)
    except Exception:
        raise HTTPException(400, "json inválido")
    refs = [d.get("txid"), d.get("correlationID")]
    ent = d.get("entity") or d.get("data") or {}
    if isinstance(ent, dict):
        refs += [ent.get("correlationID"), ent.get("referenceId"), ent.get("id")]
    tx = None
    for ref in refs:
        if not ref:
            continue
        tx = db.query(Tx).filter(Tx.kind == "DEPOSIT", Tx.status == "PENDING",
                                 Tx.external_ref == str(ref)).first()
        if not tx:
            tx = db.query(Tx).filter(Tx.kind == "DEPOSIT", Tx.status == "PENDING",
                                     Tx.openpix_charge_id == str(ref)).first()
        if tx:
            break
    if not tx:
        raise HTTPException(404, "tx não encontrada")
    _finalize_tx(db, tx)
    return {"ok": True}


@app.get("/api/wallet/deposit-status")
def deposit_status(txid: str, u: User = Depends(current_user), db: Session = Depends(get_db)):
    tx = db.query(Tx).filter(Tx.user_id == u.id, Tx.kind == "DEPOSIT",
                             Tx.external_ref == txid).first()
    if not tx:
        raise HTTPException(404, "não existe")
    if tx.status == "PENDING" and tx.openpix_charge_id:
        try:
            st = pix.charge_status(tx.openpix_charge_id)
            if st in ("PAID", "PAGO", "SUCCESS", "COMPLETED", "SETTLED"):
                _finalize_tx(db, tx)
        except Exception:
            pass
    db.refresh(u)
    return {"status": tx.status, "balance_brl": u.balance_brl, "balance_usdt": u.balance_usdt}


app.mount("/", StaticFiles(directory=STATIC, html=True), name="spa")
