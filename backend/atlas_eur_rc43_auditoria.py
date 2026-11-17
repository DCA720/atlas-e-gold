"""Atlas EUR RC4.3 — auditoria somente leitura das séries FRED.

Não gera scores, não grava dados e não imprime a chave de API.
"""
import json
import os
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from math import isfinite

SERIES = {'CPIAUCSL': 'M', 'UNRATE': 'M', 'GDPC1': 'Q'}


def fetch(series_id, key):
    query = urllib.parse.urlencode({
        'series_id': series_id, 'api_key': key, 'file_type': 'json',
        'observation_start': '2024-01-01', 'sort_order': 'asc',
        'limit': 10000,
    })
    req = urllib.request.Request(
        'https://api.stlouisfed.org/fred/series/observations?' + query,
        headers={'User-Agent': 'Atlas-EUR-Auditoria/0.4.3'},
    )
    with urllib.request.urlopen(req, timeout=35) as response:
        payload = json.load(response)
    if payload.get('error_code'):
        raise ValueError('FRED retornou erro de API')
    today = date.today().isoformat()
    rows = []
    rejected = []
    for entry in payload.get('observations', []):
        period = entry.get('date', '')
        raw = entry.get('value')
        try:
            value = float(raw)
            if not isfinite(value) or period > today:
                raise ValueError('valor inválido ou futuro')
            rows.append({'date': period, 'value': value})
        except (ValueError, TypeError):
            rejected.append({'date': period, 'reason': 'ausente/inválido/futuro'})
    rows.sort(key=lambda x: x['date'])
    return rows, rejected, {
        'api_count': payload.get('count'),
        'api_limit': payload.get('limit'),
        'api_offset': payload.get('offset'),
        'returned_observations': len(payload.get('observations', [])),
    }


def month_before(period, months):
    year, month = map(int, period[:7].split('-'))
    index = year * 12 + month - 1 - months
    return f'{index // 12:04d}-{index % 12 + 1:02d}'


def audit_cpi(rows, rejected, meta):
    by_month = {r['date'][:7]: r['value'] for r in rows if r['value'] > 0}
    latest = max(by_month, default=None)
    pairs = []
    for period in sorted(by_month, reverse=True):
        base = month_before(period, 12)
        if base in by_month:
            pairs.append({'period': period, 'base_period': base,
                          'yoy_pct': round(100 * (by_month[period] / by_month[base] - 1), 3)})
    missing = []
    if latest:
        for period in [latest, month_before(latest, 1), month_before(latest, 2)]:
            base = month_before(period, 12)
            if period in by_month and base not in by_month:
                missing.append({'period': period, 'missing_base': base})
    return {'series': 'CPIAUCSL', 'meta': meta, 'valid_count': len(rows),
            'first_period': min(by_month, default=None), 'latest_period': latest,
            'oct_2025_present': '2025-10' in by_month,
            'oct_2025_rejected': any(x['date'].startswith('2025-10') for x in rejected),
            'latest_valid_yoy_pairs': pairs[:3],
            'missing_recent_pairs': missing,
            'rejected_recent': rejected[-8:],
            'note': 'CPIAUCSL é índice dessazonalizado; comparar com HICP requer ressalva metodológica.'}


def main():
    key = os.getenv('FRED_API_KEY', '').strip()
    if not key:
        raise SystemExit('FRED_API_KEY ausente no GitHub Actions (secrets).')
    result = {'audit_version': 'eur-rc4.3-fred-readonly',
              'checked_at_utc': datetime.now(timezone.utc).isoformat(),
              'scores_generated': False, 'database_writes': False, 'series': {}}
    for sid in SERIES:
        try:
            rows, rejected, meta = fetch(sid, key)
            if sid == 'CPIAUCSL':
                result['series'][sid] = audit_cpi(rows, rejected, meta)
            else:
                result['series'][sid] = {
                    'valid_count': len(rows), 'meta': meta,
                    'latest_period': rows[-1]['date'] if rows else None,
                    'previous_period': rows[-2]['date'] if len(rows) > 1 else None,
                    'rejected_recent': rejected[-5:],
                }
        except Exception as exc:
            result['series'][sid] = {'status': 'erro', 'error_type': type(exc).__name__}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if any(v.get('status') == 'erro' for v in result['series'].values()):
        raise SystemExit('Uma ou mais séries FRED falharam; consultar JSON.')


if __name__ == '__main__':
    main()
