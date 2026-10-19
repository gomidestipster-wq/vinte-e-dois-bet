import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient

from app.db import Base, engine
from app import engine as eng
from app.main import app


@pytest.fixture(scope="session", autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


C = TestClient(app)
A = TestClient(app)
ADM_PW = os.environ.get("ADMIN_PASSWORD", "222222")


def test_price_and_rebalance():
    odds = eng.price({"H": 0.5, "D": 0.3, "A": 0.2}, 0.06)
    assert abs(eng.overround(odds) - 1.06) < 0.01
    od2 = dict(odds)
    moves = eng.rebalance(od2, {"H": 65000, "D": 25000, "A": 10000}, teto=25000)
    assert moves
    assert od2["H"] < odds["H"]
    assert abs(eng.overround(od2) - eng.overround(odds)) < 0.03


def test_poisson():
    p = eng.probs(1.8, 1.0)
    assert abs(p["H"] + p["D"] + p["A"] - 1) < 1e-6
    assert p["H"] > p["A"]
    pl = eng.probs_live(1, 0, 0.5, 0.3)
    assert pl["H"] > 0.8


def test_cashout_bounds():
    v = eng.cashout_value(10000, 2.00, 1.90)
    assert 0 < v < 10000 * 2.00
    assert v <= int(10000 * 2.00 / 1.90 * 0.98) + 1


def test_crash_math():
    cp, h = eng.crash_point("srv1", "cli1")
    cp2, h2 = eng.crash_point("srv1", "cli1")
    assert (cp, h) == (cp2, h2)
    assert 1.0 <= cp <= 1000
    tc = eng.crash_time(cp)
    m0 = eng.mult_at(cp, 0)
    assert m0 >= 1.0
    assert eng.mult_at(cp, tc / 2) >= m0
    assert abs(eng.mult_at(cp, tc) - cp) < 1e-9


def test_full_flow():
    A.post("/api/admin/login", json={"password": ADM_PW})
    C.post("/api/register", json={"name": "Ze", "cpf": "39053344705", "birth_date": "1990-05-05", "password": "1234"})
    C.post("/api/wallet/deposit", json={"currency": "BRL", "amount_cents": 100000})
    txs = A.get("/api/admin/deposits").json()["txs"]
    A.post(f"/api/admin/deposits/{txs[0]['id']}/confirm")

    r = A.post("/api/admin/events", json={"kind": "FOOTBALL", "title": "Flamengo x Palmeiras", "league": "Brasileirao", "xg_home": 1.7, "xg_away": 1.1}).json()
    eid = r["event_id"]
    ev = C.get(f"/api/events/{eid}").json()
    mk = [m for m in ev["markets"] if m["key"] == "1X2"][0]
    odds0 = {o["label"]: o["odd"] for o in mk["outcomes"]}
    oh = next(o for o in mk["outcomes"] if o["label"] == "H")
    oa = next(o for o in mk["outcomes"] if o["label"] == "A")

    rb = C.post("/api/bets", json={"market_id": mk["id"], "outcome_id": oh["id"], "stake_cents": 5000}).json()
    odd_h, pot_h = rb["odd"], rb["potential_cents"]
    assert pot_h == int(5000 * odd_h)

    ra = C.post("/api/bets", json={"market_id": mk["id"], "outcome_id": oa["id"], "stake_cents": 3000}).json()
    cash = C.post(f"/api/bets/{ra['bet_id']}/cashout").json()["cashout_cents"]
    assert cash > 0

    lv = A.post(f"/api/live/{eid}", json={"minute": 12, "sh": 1, "sa": 0}).json()
    assert not lv["finished"]
    ev2 = C.get(f"/api/events/{eid}").json()
    odds1 = {o["label"]: o["odd"] for o in [m for m in ev2["markets"] if m["key"] == "1X2"][0]["outcomes"]}
    assert odds1["H"] < odds0["H"]

    ft = A.post(f"/api/live/{eid}", json={"minute": 90, "sh": 1, "sa": 0}).json()
    assert ft["finished"]

    me = C.get("/api/me").json()
    assert me["balance_brl"] == 100000 - 5000 - 3000 + cash + pot_h

    cr = C.post("/api/crash/start", json={"client_seed": "abc", "stake_cents": 1000, "currency": "BRL"}).json()
    st = C.get(f"/api/crash/{cr['round_id']}").json()
    assert st["mult"] >= 1.0
    co = C.post(f"/api/crash/{cr['round_id']}/cashout").json()
    assert 950 <= co["cashout_cents"] <= 1100
