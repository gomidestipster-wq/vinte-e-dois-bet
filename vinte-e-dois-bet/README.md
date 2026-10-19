# VINTE E DOIS BET (22)

Casa de apostas completa: futebol (pré + live), política e cassino (crash provably fair),
com motor de odds próprio — sem feed de odds externo.

## Rodar (local)

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
# site:  http://localhost:8000
# console da casa: http://localhost:8000/console.html
```

## Rodar (Docker)

```bash
docker compose up --build
```

## Variáveis de ambiente

| var | padrão | uso |
|---|---|---|
| `APP_SECRET` | troque em produção | assina cookies e webhook PIX (`X-VD22-Signature` = HMAC-SHA256 do body) |
| `ADMIN_PASSWORD` | 222222 | senha do console da casa |
| `FX_USDT_BRL` | 6.0 | câmbio usado só p/ expor exposição (USDT→BRL); payout fica na moeda da aposta |
| `USDT_ADDRESS` | — | endereço USDT (**rede Solana**) exibido ao jogador no depósito |
| `OPENPIX_APP_ID` | — | **AppID da Woovi/OpenPix** (o bloco colado, exatamente como o painel entrega) — vai cru no header `Authorization` |
| `OPENPIX_CREDENTIALS` | — | o par base64 `Client_Id…:Client_Secret…` (descoberta/fallback) |
| `OPENPIX_BASE` | https://api.openpix.com.br | sandbox: `https://api.woovi-sandbox.com` |
| `DATABASE_URL` | sqlite em ./data | troque por postgres quando escalar |

## Primeiro dia da casa (console)

1. Login no console com a senha admin.
2. Criar partida (título + data + xg de cada lado) → os 3 mercados nascem precificados.
3. Criar mercado político (opções + chances, margem larga).
4. Jogador deposita PIX (sua gateway) → você clica CONFIRMAR (ou o webhook assina e cai sozinho).
5. Ao vivo: botões grandes (gol / intervalo / fim de jogo). Fim de jogo liquida tudo.
6. Saques: aprovar (PIX manual ou USDT).

## O motor (app/engine.py)

- `price(ps, margin)` — probabilidades justas → odds com margem alvo (overround constante).
- `rebalance(odds, stakes)` — a cada aposta/encontro, encurta o lado carregado e alonga o
  leve em passos de 0.02, teto de movimento 0.16 por ciclo, segurando o overround.
  Se o desequilíbrio estoura o teto, o teto de stake do mercado cai (liquidez).
- Poisson (pré e live da mesma função): xg × fração de tempo restante + placar atual.
- Cash-out: `stake × odd_original / odd_atual × 0.98`.
- Crash: `sha256(server_seed|client_seed)` → ponto de crash; prova exibida no fim.

Parâmetros (passo, tetos, margens) ficam aqui e no admin — política sua, auditável.

## Pix: Woovi/OpenPix — QR na hora + webhook + polling

Gateway contratada: **Woovi (OpenPix)**. Endpoints oficiais: produção
`https://api.openpix.com.br`, sandbox `https://api.woovi-sandbox.com`. Auth: header
`Authorization: {APP_ID}` (token único, sem Bearer).

**Como se pega o AppID (minutos):** login em app.woovi.com (ou app.openpix.com.br) →
menu lateral **API/Plugins** → **Nova API/Plugin** → nome (ex.: "22 BET") + tipo **API**
→ salvar (com 2FA) → copiar o AppID. Esse AppID é o que vai em `OPENPIX_APP_ID`.

Fluxo: jogador clica depositar → backend faz `POST /api/v1/charge`
(`correlationID = txid`, `value` em centavos) → site mostra **QR pronto pra escanear** +
copia-e-cola → confirmação por **webhook** (`POST /api/webhook/pix`, aceita payload com
`correlationID`/`entity`) E por **polling a cada 4 s** (`GET /api/wallet/deposit-status`
consulta o status da cobrança na Woovi). Botão CONFIRMAR no console fica como reserva.

Sem gateway configurada, o depósito entra como pendente (botão CONFIRMAR no console).
Quando me mandar o doc da API da sua gateway, eu encaixo o contrato real em `app/pix.py`.

## Roadmap (já sabendo do que falta)

- slots/live dealer via agregador (Pragmatic/Hacksaw/Evolution) quando houver contrato
- múltiplas (combinadas), mais esportes, feed de scores automático, PostgreSQL em produção
