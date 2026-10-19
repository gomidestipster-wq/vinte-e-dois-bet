import base64
import io
import json
import os
import urllib.error
import urllib.request

# Gateway real: Woovi / OpenPix
#   producao: https://api.openpix.com.br   |  sandbox: https://api.woovi-sandbox.com
#   auth:     header  Authorization: {APP_ID}   (token unico, sem Bearer)
BASE = os.environ.get("OPENPIX_BASE", "https://api.openpix.com.br")
APP_ID = os.environ.get("OPENPIX_APP_ID", "")
CRED_BLOB = os.environ.get("OPENPIX_CREDENTIALS", "")  # base64 de Client_Id_...:Client_Secret_...
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def _app_id():
    """A Woovi autenticou o par colado no chat NO FORMATO BLOB BASE64 INTEIRO
    (Authorization: <bloco>). APP_ID vence se preenchido; senao usa o blob cru."""
    if APP_ID:
        return APP_ID.strip()
    return CRED_BLOB.strip()


def _req(method, path, body=None):
    token = _app_id()
    if not token:
        raise RuntimeError("openpix nao configurada (OPENPIX_APP_ID/OPENPIX_CREDENTIALS)")
    req = urllib.request.Request(
        BASE.rstrip("/") + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"User-Agent": UA, "Content-Type": "application/json",
                 "Authorization": _app_id()},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"openpix {e.code}: {e.read().decode()[:200]}")


def _pick(d):
    if isinstance(d, dict):
        return d.get("charge") or d.get("data") or d
    return {}


def create_charge(txid, amount_cents, comment="Deposito - Vinte e Dois Bet"):
    d = _req("POST", "/api/v1/charge",
             {"correlationID": str(txid), "value": int(amount_cents),
              "comment": comment[:80]})
    ch = _pick(d)
    cid = ch.get("id") or ch.get("chargeId") or ch.get("charge_id")
    emv = ch.get("qrCode") or ch.get("copiaECola") or ch.get("emv") or ch.get("brCode")
    qr_b64 = ch.get("qrCodeBase64") or ch.get("qrImageBase64")
    if cid and not emv:
        for sub in ("/qrCodeBase64", "/qrcode", "/payload"):
            try:
                extra = _req("GET", f"/api/v1/charge/{cid}{sub}")
                c2 = _pick(extra)
                qr_b64 = qr_b64 or c2.get("qrCodeBase64") or c2.get("base64")
                emv = emv or c2.get("qrCode") or c2.get("emv") or c2.get("payload")
            except Exception:
                pass
    return {"chargeId": cid, "emv": emv, "qrB64": qr_b64, "qrUrl": ch.get("qrCodeImage"), "raw": d}


def charge_status(charge_id):
    d = _req("GET", f"/api/v1/charge/{charge_id}")
    ch = _pick(d)
    return (ch.get("status") or ch.get("state") or "").upper()


def emv_to_qr_data_url(emv):
    import qrcode
    img = qrcode.make(emv)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
