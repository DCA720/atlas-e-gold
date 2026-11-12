"""Atlas RC8: coleta horária experimental e armazenamento durável de preços.

Yahoo Finance chart é fonte NÃO OFICIAL. DX-Y.NYB é proxy do DXY; GC=F
é futuro de ouro, NÃO XAU/USD spot. Candles são registrados somente depois
que fecham. Dados importados retroativamente não são provas prospectivas.
"""
import argparse
import csv
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FIELDS = ['timestamp', 'USD', 'GOLD']
DEFAULT_SYMBOLS = {'USD': 'DX-Y.NYB', 'GOLD': 'GC=F'}
SOURCE = 'yahoo_chart_unofficial_1h'


def parse_chart(payload, now=None):
    now = now or datetime.now(timezone.utc)
    chart = payload.get('chart', {})
    if chart.get('error'):
        raise ValueError('Erro do provedor')
    results = chart.get('result') or []
    if len(results) != 1:
        raise ValueError('Resposta sem série única')
    result = results[0]
    timestamps = result.get('timestamp') or []
    closes = (result.get('indicators', {}).get('quote') or [{}])[0].get('close') or []
    if len(timestamps) != len(closes):
        raise ValueError('Timestamps e fechamentos inconsistentes')
    granularity = result.get('meta', {}).get('dataGranularity', '')
    if granularity and granularity not in ('1h', '60m'):
        raise ValueError('Granularidade inesperada')
    rows = {}
    for ts, close in zip(timestamps, closes):
        if isinstance(ts, bool) or not isinstance(ts, (int, float)):
            continue
        if isinstance(close, bool) or not isinstance(close, (int, float)) or not math.isfinite(close) or close <= 0:
            continue
        # Yahoo marca a ABERTURA do candle; armazenar a hora de FECHAMENTO.
        if ts + 3600 > now.timestamp():
            continue
        closed_at = datetime.fromtimestamp(ts + 3600, timezone.utc)
        rows[closed_at.isoformat()] = float(close)
    return rows


def fetch_prices(symbol, timeout=15, opener=None):
    url = ('https://query1.finance.yahoo.com/v8/finance/chart/'
           + urllib.parse.quote(symbol, safe='') + '?interval=1h&range=60d')
    req = urllib.request.Request(url, headers={
        'User-Agent': 'AtlasMacroValidation/3.0', 'Accept': 'application/json'})
    opener = opener or urllib.request.urlopen
    with opener(req, timeout=timeout) as response:
        return parse_chart(json.load(response))


def merge_csv(path, fetched):
    existing = {}
    if path.exists():
        with path.open(newline='', encoding='utf-8-sig') as file:
            reader = csv.DictReader(file)
            if reader.fieldnames != FIELDS:
                raise ValueError('CSV existente com colunas inesperadas; não sobrescrever')
            for row in reader:
                dt = datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00'))
                if dt.tzinfo is None:
                    raise ValueError('Timestamp sem fuso')
                key = dt.astimezone(timezone.utc).isoformat()
                if key in existing:
                    raise ValueError('CSV com timestamp duplicado')
                existing[key] = {'timestamp': key, 'USD': row['USD'], 'GOLD': row['GOLD']}
    added = 0
    for asset, points in fetched.items():
        for ts, price in points.items():
            row = existing.setdefault(ts, {'timestamp': ts, 'USD': '', 'GOLD': ''})
            if not row[asset]:
                row[asset] = str(price)
                added += 1
    if added:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + '.tmp')
        try:
            with tmp.open('w', newline='', encoding='utf-8') as file:
                writer = csv.DictWriter(file, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(existing[key] for key in sorted(existing))
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink()
    return added


def push_postgres(fetched, symbols):
    """Insere candles fechados sem modificar registros existentes.

    Requer índice UNIQUE(symbol,price_time,source), disponibilizado no SQL RC8.
    """
    url = os.getenv('DATABASE_URL', '').strip()
    if not url:
        print('DATABASE_URL ausente: PostgreSQL ignorado.', file=sys.stderr)
        return None
    import psycopg
    rows = []
    for asset, points in fetched.items():
        for ts, price in points.items():
            rows.append((symbols[asset], price, datetime.fromisoformat(ts), SOURCE))
    if not rows:
        return 0
    with psycopg.connect(url, connect_timeout=10, sslmode='require') as conn:
        with conn.cursor() as cur:
            cur.executemany('''INSERT INTO public.atlas_market_prices
                (symbol,price,price_time,source)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT (symbol,price_time,source) DO NOTHING''', rows)
    return len(rows)  # Quantidade tentada, não quantidade efetivamente inserida.


def cycle(args):
    fetched, errors = {}, {}
    symbols = {'USD': args.usd_symbol, 'GOLD': args.gold_symbol}
    for asset, symbol in symbols.items():
        try:
            fetched[asset] = fetch_prices(symbol)
        except (OSError, ValueError, KeyError, TypeError, TimeoutError) as exc:
            errors[asset] = type(exc).__name__
    if not fetched:
        print('Nenhuma fonte respondeu; dados anteriores preservados.', file=sys.stderr)
        return False
    try:
        attempted = push_postgres(fetched, symbols)
        print(f'PostgreSQL: {attempted} registros tentados (duplicados ignorados).')
    except Exception as exc:
        print(f'Falha ao gravar no PostgreSQL: {type(exc).__name__}', file=sys.stderr)
        # Não mascarar falha do banco como sucesso.
        attempted = None
    added = merge_csv(Path(args.prices), fetched)
    print(f'CSV: {added} novos preços; ativos consultados: {list(fetched)}')
    if errors:
        print(f'Fontes indisponíveis: {errors}', file=sys.stderr)
    if args.validate_local:
        from validate_history import evaluate, load_prices, load_signals
        db = Path(args.db)
        if db.exists():
            report = evaluate(load_signals(db), load_prices(args.prices))
            report['market_data'] = {
                'provider': 'Yahoo Finance chart (não oficial)',
                'symbols': symbols, 'granularity': '1h; candles fechados',
                'warning': 'GC=F é futuro de ouro, não XAU/USD spot. Histórico importado não é validação prospectiva.',
                'generated_at_utc': datetime.now(timezone.utc).isoformat()}
            out = Path(args.out).with_suffix('.json')
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix('.json.tmp')
            try:
                tmp.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
                os.replace(tmp, out)
            finally:
                if tmp.exists(): tmp.unlink()
        else:
            print('SQLite local ausente: validação local adiada.', file=sys.stderr)
    return attempted is not None or not os.getenv('DATABASE_URL')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prices', default=str(ROOT / 'precos_mercado.csv'))
    p.add_argument('--db', default=str(ROOT / 'atlas.db'))
    p.add_argument('--out', default=str(ROOT / 'validacao_atlas'))
    p.add_argument('--usd-symbol', default=DEFAULT_SYMBOLS['USD'])
    p.add_argument('--gold-symbol', default=DEFAULT_SYMBOLS['GOLD'])
    p.add_argument('--interval-minutes', type=int, default=60)
    p.add_argument('--loop', action='store_true')
    p.add_argument('--validate-local', action='store_true', help='Executar validação SQLite legada')
    args = p.parse_args()
    if args.interval_minutes < 15:
        p.error('Intervalo mínimo: 15 minutos')
    while True:
        try:
            cycle(args)
        except Exception as exc:
            print(f'Falha de coleta: {type(exc).__name__}', file=sys.stderr)
        if not args.loop:
            break
        time.sleep(args.interval_minutes * 60)


if __name__ == '__main__':
    main()
