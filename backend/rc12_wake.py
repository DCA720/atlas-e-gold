"""Acorda o Render e verifica se o worker pode registrar sinais reais.

Nao cria sinais sinteticos, nao chama endpoints POST publicos e nao altera scores.
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
    request = urllib.request.Request(BASE + path, headers={'User-Agent': 'Atlas-RC12/1.0'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


# Render free pode demorar a iniciar; dar tempo para o worker coletar FRED.
for attempt in range(1, 5):
    try:
        health = get('/api/health')
        print('Render acessivel; health:', json.dumps({
            'postgresql': health.get('postgresql'),
            'last_success': health.get('last_success'),
        }, ensure_ascii=False))
        break
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        print(f'Tentativa {attempt}/4: {type(exc).__name__}', flush=True)
        if attempt == 4:
            raise
        time.sleep(20)

# O worker ja inicia automaticamente junto ao app; evitar POST /api/refresh
# porque essa rota e publica e pode ter efeitos operacionais.
time.sleep(120)
try:
    signals = get('/api/short-signals', timeout=30)
    print('Sinais observados:', signals.get('count', 'indisponivel'))
    print('Status PostgreSQL:', json.dumps(signals.get('postgresql', {}), ensure_ascii=False))
except (urllib.error.URLError, TimeoutError, ValueError) as exc:
    print('AVISO: nao foi possivel confirmar sinais:', type(exc).__name__)
    # Nao impede validacao dos sinais ja armazenados no PostgreSQL.
