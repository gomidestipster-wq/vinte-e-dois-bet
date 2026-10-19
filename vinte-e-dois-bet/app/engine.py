import math
import hashlib

PASSO = 0.02
MOV_MAX = 0.16
MIN_ODD = 1.01
MAX_ODD = 100.0
EDGE_CRASH = 0.01


def price(ps: dict, margin: float) -> dict:
    """probabilidades justas -> odds decimais com margem alvo."""
    ps = {k: max(float(p), 0.0001) for k, p in ps.items()}
    s = sum(ps.values())
    return {k: round(1.0 / ((1.0 + margin) * (p / s)), 2) for k, p in ps.items()}


def overround(odds: dict) -> float:
    return sum(1.0 / o for o in odds.values())


def rebalance(odds: dict, stakes: dict, teto: float = 25_000, mov_max: float = MOV_MAX, passo: float = PASSO) -> list:
    """Enquanto o spread de EV (lucro da casa por cenario) passar do teto,
    encurta o lado carregado e alonga o lado leve, mantendo o overround constante.
    stakes em centavos BRL (USDT ja convertido). Mutates odds; retorna os lances."""
    or_ref = overround(odds)
    pool = sum(stakes.values())
    if pool <= 0:
        return []

    def ev(k):
        return pool - odds[k] * stakes.get(k, 0)

    moves = []
    mv = {k: 0.0 for k in odds}
    for _ in range(80):
        evs = {k: ev(k) for k in odds}
        if max(evs.values()) - min(evs.values()) <= teto:
            break
        hot = min(evs, key=evs.get)
        cold = min((k for k in odds if k != hot), key=lambda k: stakes.get(k, 0))
        if mv[hot] >= mov_max or mv[cold] >= mov_max:
            break
        no = round(odds[hot] - passo, 2)
        if no <= MIN_ODD:
            break
        rest = sum(1.0 / odds[k] for k in odds if k not in (hot, cold))
        recip = or_ref - 1.0 / no - rest
        if recip <= 0:
            break
        nc = round(1.0 / recip, 2)
        if nc < MIN_ODD or nc > MAX_ODD:
            break
        moves.append({"hot": hot, "from": odds[hot], "to": no, "cold": cold, "cold_from": odds[cold], "cold_to": nc})
        mv[hot] += passo
        mv[cold] += abs(nc - odds[cold])
        odds[hot] = no
        odds[cold] = nc
    return moves


def cashout_value(stake_cents: int, odd_orig: float, odd_now: float, juice: float = 0.02) -> int:
    if odd_now <= 0:
        return 0
    v = stake_cents * odd_orig / odd_now * (1 - juice)
    return int(min(max(v, 0), stake_cents * odd_orig))


# ---------- Poisson (futebol: pre e live da mesma funcao) ----------

def _pmf(l, k):
    if l <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-l) * (l ** k) / math.factorial(k)


def probs(lh, la, cap=9):
    M = [[_pmf(lh, i) * _pmf(la, j) for j in range(cap + 1)] for i in range(cap + 1)]
    tot = sum(sum(r) for r in M) or 1.0
    res = {"H": 0.0, "D": 0.0, "A": 0.0, "O": 0.0, "AC": 0.0}
    for i in range(cap + 1):
        for j in range(cap + 1):
            p = M[i][j] / tot
            if i > j:
                res["H"] += p
            elif i == j:
                res["D"] += p
            else:
                res["A"] += p
            if i + j >= 3:
                res["O"] += p
            if i > 0 and j > 0:
                res["AC"] += p
    return res


def probs_live(sh, sa, lh_rem, la_rem, cap=9):
    M = [[_pmf(lh_rem, i) * _pmf(la_rem, j) for j in range(cap + 1)] for i in range(cap + 1)]
    tot = sum(sum(r) for r in M) or 1.0
    res = {"H": 0.0, "D": 0.0, "A": 0.0, "O": 0.0, "AC": 0.0}
    for i in range(cap + 1):
        for j in range(cap + 1):
            p = M[i][j] / tot
            fh, fa = sh + i, sa + j
            if fh > fa:
                res["H"] += p
            elif fh == fa:
                res["D"] += p
            else:
                res["A"] += p
            if fh + fa >= 3:
                res["O"] += p
            if fh > 0 and fa > 0:
                res["AC"] += p
    return res


# ---------- Crash (provably fair) ----------

def crash_point(server_seed: str, client_seed: str):
    h = hashlib.sha256(f"{server_seed}|{client_seed}".encode()).hexdigest()
    x = int(h, 16) / (16 ** 64)
    cp = math.floor(10000 * (1.0 - EDGE_CRASH) / (1.0 - x)) / 100
    return max(1.00, min(cp, 1000.00)), h


def crash_time(cp: float) -> float:
    if cp <= 1.001:
        return 1.5
    return min(30.0, max(1.5, math.log(cp) * 8.0))


def mult_at(cp: float, t: float) -> float:
    tc = crash_time(cp)
    if t >= tc:
        return cp
    return math.exp(math.log(max(cp, 1.0001)) * (t / tc))
