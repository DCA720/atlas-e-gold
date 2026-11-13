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
            cur.execute('''SELECT asset,horizon,score,bias,coverage,drivers,methodology_version,observed_at
                           FROM atlas_signals ORDER BY observed_at DESC LIMIT %s''', (limit,))
            rows = cur.fetchall()
    signals = []
    for asset,horizon,score,bias,coverage,drivers,version,observed in reversed(rows):
        if isinstance(drivers, str):
            drivers = json.loads(drivers)
        signals.append({'signal_time_utc': observed.astimezone(timezone.utc).isoformat(),
                        'asset': asset, 'horizon': '1d' if horizon == 1 else '5d',
                        'score': float(score), 'bias': bias, 'coverage': float(coverage) if coverage is not None else None,
                        'window_end': drivers.get('window_end'),
                        'model_version': version,
                        'record_type': drivers.get('record_type', 'prospective_observation')})
    return signals


def merge(local, remote):
    """RC13: preserve legacy records; deduplicate daily observations by UTC date.

    A prior legacy signal on the same UTC day takes precedence over a new
    daily observation, preventing accidental duplication during migration.
    """
    ordered = sorted([*remote, *local], key=lambda x: x['signal_time_utc'])
    by_key = {}
    occupied_days = set()
    for r in ordered:
        day = datetime.fromisoformat(r['signal_time_utc'].replace('Z', '+00:00')).astimezone(timezone.utc).date().isoformat()
        daily_key = (r['asset'], r['horizon'], r['model_version'], day)
        if r.get('record_type') == 'prospective_daily_observation_rc13':
            key = ('daily', *daily_key)
            if daily_key in occupied_days:
                continue
        else:
            key = ('legacy', r['asset'], r['horizon'], r.get('window_end'), r['model_version'])
        if key in by_key:
            continue
        by_key[key] = r
        occupied_days.add(daily_key)
    return sorted(by_key.values(), key=lambda x: x['signal_time_utc'])
