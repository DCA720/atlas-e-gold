"""Optional durable storage for prospective Atlas signals (PostgreSQL/Supabase).

The SQLite state remains the RC6 runtime cache. PostgreSQL is the durable signal ledger.
No database URL or credentials are logged or returned by this module.
"""
import json
import os
from datetime import datetime, timezone


def configured():
    return bool(os.environ.get('DATABASE_URL', '').strip())


def _connect():
    import psycopg
    return psycopg.connect(os.environ['DATABASE_URL'], connect_timeout=5,
                           sslmode='require', autocommit=False)


def _row(record):
    observed_at = datetime.fromisoformat(record['signal_time_utc'].replace('Z', '+00:00'))
    if observed_at.tzinfo is None:
        raise ValueError('Sinal sem fuso horário UTC')
    asset = record['asset']
    horizon = {'1d': 1, '5d': 5, 1: 1, 5: 5}.get(record['horizon'])
    if asset not in ('USD', 'GOLD') or horizon is None:
        raise ValueError('Ativo ou horizonte inválido')
    score = record.get('score')
    if score is None:
        raise ValueError('Sinal sem pontuação')
    return (asset, horizon, score, record.get('bias'), record.get('coverage'),
            json.dumps({'window_end': record.get('window_end'),
                        'record_type': record.get('record_type', 'prospective_observation')},
                       ensure_ascii=False), record['model_version'], observed_at)


def push(records):
    """Idempotent write; returns attempted count, only after a committed transaction."""
    if not configured():
        return 0
    prepared = [_row(r) for r in records]
    if not prepared:
        return 0
    with _connect() as conn:
        with conn.cursor() as cur:
            for values in prepared:
                cur.execute('''INSERT INTO atlas_signals
                    (asset,horizon,score,bias,coverage,drivers,methodology_version,observed_at)
                    VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s)
                    ON CONFLICT (asset,horizon,methodology_version,observed_at) DO NOTHING''', values)
    return len(prepared)


def pull(limit=5000):
    """Recover prospective signals after an ephemeral Render filesystem reset."""
    if not configured():
        return []
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute('''SELECT asset,horizon,score,coverage,drivers,methodology_version,observed_at
                           FROM atlas_signals ORDER BY observed_at DESC LIMIT %s''', (limit,))
            rows = cur.fetchall()
    signals = []
    for asset,horizon,score,coverage,drivers,version,observed in reversed(rows):
        if isinstance(drivers, str):
            drivers = json.loads(drivers)
        signals.append({'signal_time_utc': observed.astimezone(timezone.utc).isoformat(),
                        'asset': asset, 'horizon': '1d' if horizon == 1 else '5d',
                        'score': float(score), 'coverage': float(coverage) if coverage is not None else None,
                        'window_end': drivers.get('window_end'),
                        'model_version': version,
                        'record_type': drivers.get('record_type', 'prospective_observation')})
    return signals


def merge(local, remote):
    """Preserve earliest recorded signal for each economic window and methodology."""
    by_window = {}
    for r in sorted([*remote, *local], key=lambda x: x['signal_time_utc']):
        key = (r['asset'], r['horizon'], r.get('window_end'), r['model_version'])
        by_window.setdefault(key, r)
    return sorted(by_window.values(), key=lambda x: x['signal_time_utc'])
