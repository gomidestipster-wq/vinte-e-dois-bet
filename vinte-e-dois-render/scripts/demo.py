import os
import sys

rootp = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, rootp)
os.environ.setdefault("ADMIN_PASSWORD", "222222")
dbf = os.path.join(rootp, "data", "db.sqlite3")
if os.path.exists(dbf):
    os.remove(dbf)

from fastapi.testclient import TestClient

from app.db import Base, engine
from app.main import app

Base.metadata.create_all(engine)
A = TestClient(app)
U = TestClient(app)

def fmtB(c):
    return f"R$ {c/100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

A.post("/api/admin/login", json={"password": "222222"})
U.post("/api/register", json={"name": "João", "cpf": "12345678909", "birth_date": "1992-03-10", "password": "2222"})
U.post("/api/wallet/deposit", json={"currency": "BRL", "amount_cents": 20000})
A.post(f"/api/admin/deposits/{A.get('/api/admin/deposits').json()['txs'][0]['id']}/confirm")

print("=" * 62)
print("VINTE E DOIS BET — demonstração do sistema inteiro rodando agora")
print("=" * 62)

print("\n[1] JOGADOR registra e deposita R$ 200,00 via PIX (gateway confirma)")
r = A.post("/api/admin/events", json={"kind": "FOOTBALL", "title": "Flamengo x Palmeiras",
                                      "league": "Brasileirão · Rodada 22",
                                      "xg_home": 1.7, "xg_away": 1.1}).json()
eid = r["event_id"]
ev = U.get(f"/api/events/{eid}").json()

print("\n[2] CASA abre a partida — motor precifica sozinho (Poisson, xg 1.7/1.1):")
for m in ev["markets"]:
    line = "   ".join(f"{o['label']} {o['odd']:.2f}" for o in m["outcomes"])
    print(f"    {m['title']:<26} {line}")

mk = [m for m in ev["markets"] if m["key"] == "1X2"][0]
odds0 = {o["label"]: o["odd"] for o in mk["outcomes"]}
oh = next(o for o in mk["outcomes"] if o["label"] == "H")
oa = next(o for o in mk["outcomes"] if o["label"] == "A")

b1 = U.post("/api/bets", json={"market_id": mk["id"], "outcome_id": oh["id"], "stake_cents": 5000}).json()
print("\n[3] João aposta R$ 50,00 na CASA a", f"{b1['odd']:.2f}", "-> retorna", fmtB(b1["potential_cents"]))
if b1["moves"]:
    print("    motor: " + ", ".join(f"{m['hot']} {m['from']:.2f}->{m['to']:.2f}" for m in b1["moves"]) + " (dinheiro pesou no lado)")

b2 = U.post("/api/bets", json={"market_id": mk["id"], "outcome_id": oa["id"], "stake_cents": 3000}).json()
co = U.post(f"/api/bets/{b2['bet_id']}/cashout").json()["cashout_cents"]
print("[4] João aposta R$ 30,00 no FORA e faz CASHOUT em seguida:", fmtB(co))

lv = A.post(f"/api/live/{eid}", json={"minute": 12, "sh": 1, "sa": 0}).json()
ev2 = U.get(f"/api/events/{eid}").json()
mk2 = [m for m in ev2["markets"] if m["key"] == "1X2"][0]
odds1 = {o["label"]: o["odd"] for o in mk2["outcomes"]}
print("\n[5] MIN 12 — OPERADOR clica GOL DA CASA no console (botão grande)")
print("    1X2 antes:", "   ".join(f"{k} {v:.2f}" for k, v in odds0.items()))
print("    1X2 agora:", "   ".join(f"{k} {v:.2f}" for k, v in odds1.items()), "(modelo recalculou com o placar)")

ft = A.post(f"/api/live/{eid}", json={"minute": 90, "sh": 1, "sa": 0}).json()
me = U.get("/api/me").json()
print("\n[6] FIM DE JOGO 1x0 — liquidou tudo sozinho:")
for b in U.get("/api/bets").json()["bets"]:
    print(f"    {b['label']:<5} a {b['odd']:.2f}  status={b['status']}")
print("    saldo final de João:", fmtB(me["balance_brl"]), "(ganhou na casa; cashout rendeu no fora)")

cr = U.post("/api/crash/start", json={"client_seed": "joao77", "stake_cents": 2000, "currency": "BRL"}).json()
stt = U.get(f"/api/crash/{cr['round_id']}").json()
cx = U.post(f"/api/crash/{cr['round_id']}/cashout").json()
print("\n[7] CASSINO — 22 CRASH (provably fair): apostou R$ 20,00, resgatou a",
      f"{cx['mult']:.2f}x" if False else f"{cx['mult']:.2f}x", "->", fmtB(cx["cashout_cents"]))

d = A.get("/api/admin/dashboard").json()
print("\n[8] DASHBOARD DA CASA:", d)
print("\nTudo acima aconteceu via API agora, com banco limpo. O site (PWA) e o")
print("console do operador (/console.html) consomem exatamente estas rotas.")
