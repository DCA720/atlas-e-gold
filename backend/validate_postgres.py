"""Atlas RC9 — auditoria exploratória de sinais vs fechamentos diários UTC.

Uso: python backend/validate_postgres.py
Requer DATABASE_URL e psycopg (psycopg[binary]). Sem escrita por padrão.
--save grava somente agregados elegíveis em atlas_validations.
Não é um backtest validado nem definição de sessões de bolsa oficiais.
"""
import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

SYMBOLS = {'USD': 'DX-Y.NYB', 'GOLD': 'GC=F'}
SOURCE = 'yahoo_chart_unofficial_1h'
VERSION = '3.0-rc9-experimental-daily-utc-v1'


def summarize(signals, prices, threshold=20, min_sample=30):
    """Pure function: prices are (symbol, price, price_time, created_at)."""
    by_symbol_day = defaultdict(dict)
    for symbol, price, stamp, created in prices:
        if symbol not in SYMBOLS.values() or not stamp or price is None or float(price) <= 0:
            continue
        # Daily last close, by UTC date. Imported history is not prospectively observed.
        day = stamp.astimezone(timezone.utc).date()
        old = by_symbol_day[symbol].get(day)
        if old is None or stamp > old[0]:
            by_symbol_day[symbol][day] = (stamp, float(price), created)
    daily = {s: sorted(v.values(), key=lambda x: x[0]) for s, v in by_symbol_day.items()}
    groups = defaultdict(list)
    pending = defaultdict(int)
    neutral = defaultdict(int)
    for asset, horizon, score, observed, version, drivers in signals:
        if asset not in SYMBOLS or horizon not in (1, 5) or score is None or observed is None:
            continue
        key = (asset, horizon, version)
        score = float(score)
        if abs(score) < threshold:
            neutral[key] += 1
            continue
        # Entry: first completed hourly candle after signal, only if not excessively late.
        symbol = SYMBOLS[asset]
        candidates = [p for p in prices if p[0] == symbol and p[2] > observed]
        if not candidates:
            pending[key] += 1
            continue
        entry = min(candidates, key=lambda p: p[2])
        entry_time, entry_price = entry[2], float(entry[1])
        # Require entry within 2h of the signal, otherwise no plausible timely entry.
        if (entry_time - observed).total_seconds() > 7200 or entry_price <= 0:
            pending[key] += 1
            continue
        # Daily closes on *subsequent* UTC dates, not hourly bars.
        future_days = [x for x in daily.get(symbol, []) if x[0].date() > entry_time.date()]
        if len(future_days) < horizon:
            pending[key] += 1
            continue
        exit_time, exit_price, _ = future_days[horizon - 1]
        raw_return = (exit_price / entry_price - 1) * 100
        directional = raw_return * (1 if score > 0 else -1)
        groups[key].append(dict(observed=observed, entry_time=entry_time,
                                exit_time=exit_time, directional_return=directional,
                                raw_return=raw_return, score=score))
    all_keys = set(groups) | set(pending) | set(neutral)
    report = []
    for key in sorted(all_keys):
        rows = sorted(groups[key], key=lambda r: (r['observed'], r['entry_time']))
        selected, last_exit = [], None
        for row in rows:
            if last_exit is None or row['entry_time'] > last_exit:
                selected.append(row)
                last_exit = row['exit_time']
        n = len(selected)
        # No public hit rate until sample threshold; exploratory means still recorded in metrics.
        hit_rate = round(100 * sum(r['directional_return'] > 0 for r in selected) / n, 4) if n >= min_sample else None
        avg_return = round(sum(r['directional_return'] for r in selected) / n, 6) if n >= min_sample else None
        report.append(dict(asset=key[0], horizon=key[1], methodology_version=VERSION,
                           sample_size=n, hit_rate=hit_rate, average_return=avg_return,
                           metrics=dict(signal_methodology=key[2], threshold_abs=threshold,
                                        neutral_count=neutral[key], pending_count=pending[key],
                                        eligible_count=len(rows), non_overlapping=n,
                                        minimum_sample=min_sample, sufficient=n >= min_sample,
                                        horizon_unit='subsequent_utc_dates_with_data',
                                        entry_rule='first_closed_hourly_bar_after_signal_max_2h',
                                        exit_rule='last_hourly_close_of_nth_subsequent_utc_date',
                                        provider=SOURCE, gold_is_futures_not_spot=True,
                                        warning='UTC dates are not exchange sessions; hourly closes may be retroactively imported; experimental only')))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--save', action='store_true', help='Write aggregate rows to atlas_validations')
    parser.add_argument('--threshold', type=float, default=20, help='Provisional neutral threshold; confirm with Atlas score rules')
    parser.add_argument('--min-sample', type=int, default=30)
    args = parser.parse_args()
    if not 0 < args.threshold <= 100 or args.min_sample < 1:
        parser.error('Invalid threshold or sample size')
    url = os.environ.get('DATABASE_URL', '').strip()
    if not url:
        parser.error('DATABASE_URL environment secret is required')
    import psycopg
    with psycopg.connect(url, connect_timeout=15, sslmode='require') as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT asset,horizon,score,observed_at,methodology_version,drivers FROM public.atlas_signals ORDER BY observed_at')
            signals = cur.fetchall()
            cur.execute('SELECT symbol,price,price_time,created_at FROM public.atlas_market_prices WHERE symbol IN (%s,%s) AND source=%s ORDER BY price_time',
                        (SYMBOLS['USD'], SYMBOLS['GOLD'], SOURCE))
            prices = cur.fetchall()
        report = summarize(signals, prices, args.threshold, args.min_sample)
        print(json.dumps({'version': VERSION, 'mode': 'save' if args.save else 'dry_run',
                          'signals': len(signals), 'prices': len(prices), 'groups': report},
                         ensure_ascii=False, indent=2, default=str))
        if args.save:
            with conn.cursor() as cur:
                for row in report:
                    cur.execute('''INSERT INTO public.atlas_validations
                        (asset,horizon,methodology_version,sample_size,hit_rate,average_return,metrics,evaluated_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s)''',
                        (row['asset'], row['horizon'], row['methodology_version'], row['sample_size'],
                         row['hit_rate'], row['average_return'], json.dumps(row['metrics']), datetime.now(timezone.utc)))
            conn.commit()


if __name__ == '__main__':
    main()
