"""Acorda o Render e observa a sincronizacao antes da validacao RC12.

Somente GET: nao gera sinais, nao altera scores e nao aciona refresh.
A API atual nao oferece confirmacao transacional de fim de sincronizacao;
por isso os logs distinguem acessibilidade de sincronizacao confirmada.
"""
import json
import os
import time
import urllib.error
import urllib.request

BASE = os.environ.get('ATLAS_API_URL', '').rstrip('/')
if not BASE.startswith('https://'):
    raise SystemExit('ATLAS_API_URL deve usar HTTPS')


def get(path, timeout=70):
    request = urllib.request.Request(
        BASE + path,
        headers={'User-Agent': 'Atlas-RC12/1.1', 'Accept': 'application/json'},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def status_from(payload):
    pg = payload.get('postgresql') or {}
    return {
        'connected': pg.get('connected'),
        'last_success': pg.get('last_success'),
        'synced_count': pg.get('synced_count'),
    }


health = None
for attempt in range(1, 5):
    try:
        health = get('/api/health')
        print('Render acessivel; PostgreSQL:', json.dumps(status_from(health), ensure_ascii=False), flush=True)
        break
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        print(f'Tentativa {attempt}/4: {type(exc).__name__}', flush=True)
        if attempt == 4:
            raise
        time.sleep(20)

# Espera limitada; observa se o estado de sincronizacao evoluiu.
# Uma resposta HTTP 200, por si so, nao comprova que o worker terminou.
initial = status_from(health)
initial_success = initial['last_success']
confirmed_progress = False
for attempt in range(1, 7):
    time.sleep(20)
    try:
        signals = get('/api/short-signals', timeout=30)
        pg = status_from(signals)
        print(
            f'Observacao {attempt}/6: sinais={signals.get("count", "indisponivel")}; '
            f'postgresql={json.dumps(pg, ensure_ascii=False)}',
            flush=True,
        )
        if pg['connected'] is True and pg['last_success'] and pg['last_success'] != initial_success:
            confirmed_progress = True
            print('Foi observada nova sincronizacao PostgreSQL apos acordar o Render.', flush=True)
            break
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        print(f'AVISO: observacao {attempt}/6 falhou: {type(exc).__name__}', flush=True)

if not confirmed_progress:
    print(
        'AVISO: nao foi possivel confirmar nova sincronizacao durante a espera. '
        'Isso nao significa necessariamente falha: pode nao haver dados novos. '
        'A validacao seguinte usa apenas registros ja persistidos no PostgreSQL.',
        flush=True,
    )
