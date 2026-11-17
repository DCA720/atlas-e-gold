"""Atlas EUR RC4.4 — auditoria de observações FRED, somente leitura.

Inspeciona valores brutos de meses específicos em consultas completas e restritas.
Não cria sinais, não modifica scores, não grava em banco e não expõe a chave.
"""
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from math import isfinite

VERSION = 'eur-rc4.4-fred-raw-audit'
SERIES = ('CPIAUCSL', 'UNRATE')
TARGET_DATES = ('2025-09-01', '2025-10-01', '2025-11-01', '2026-09-01', '2026-10-01')


def request_fred(series_id, api_key, start, end):
    params = urllib.parse.urlencode({
        'series_id': series_id,
        'api_key': api_key,
        'file_type': 'json',
        'observation_start': start,
        'observation_end': end,
        'sort_order': 'asc',
        'limit': 10000,
    })
    url = 'https://api.stlouisfed.org/fred/series/observations?' + params
    req = urllib.request.Request(url, headers={'User-Agent': 'Atlas-EUR-RC44-Audit/1.0'})
    with urllib.request.urlopen(req, timeout=35) as response:
        payload = json.load(response)
    if 'error_code' in payload:
        raise ValueError('FRED retornou erro de API')
    observations = payload.get('observations', [])
    if not isinstance(observations, list):
        raise ValueError('Resposta FRED sem lista de observações')
    return observations, {
        'api_count': payload.get('count'),
        'api_limit': payload.get('limit'),
        'api_offset': payload.get('offset'),
        'returned_count': len(observations),
    }


def inspect_value(raw):
    if raw is None:
        return {'raw_value': None, 'classification': 'missing_null'}
    raw_text = str(raw)
    try:
        number = float(raw_text)
    except (ValueError, TypeError):
        return {'raw_value': raw_text, 'classification': 'missing_dot' if raw_text == '.' else 'non_numeric'}
    if not isfinite(number):
        return {'raw_value': raw_text, 'classification': 'non_finite'}
    return {'raw_value': raw_text, 'classification': 'numeric_valid'}


def inspect_target(observations, date):
    matching = [row for row in observations if row.get('date') == date]
    if not matching:
        return {'date': date, 'classification': 'not_returned', 'matching_count': 0}
    return {
        'date': date,
        'matching_count': len(matching),
        'observations': [
            {'date': row.get('date'), **inspect_value(row.get('value'))}
            for row in matching
        ],
    }


def audit_series(series_id, api_key):
    full, full_meta = request_fred(series_id, api_key, '2024-01-01', '2026-12-31')
    narrow, narrow_meta = request_fred(series_id, api_key, '2025-09-01', '2025-11-30')
    return {
        'full_query': {
            'window': '2024-01-01/2026-12-31',
            'metadata': full_meta,
            'targets': [inspect_target(full, date) for date in TARGET_DATES],
        },
        'narrow_query': {
            'window': '2025-09-01/2025-11-30',
            'metadata': narrow_meta,
            'targets': [inspect_target(narrow, date) for date in TARGET_DATES[:3]],
        },
    }


def main():
    key = os.environ.get('FRED_API_KEY', '').strip()
    if not key:
        raise SystemExit('FRED_API_KEY nao configurada no GitHub Actions.')
    result = {
        'audit_version': VERSION,
        'checked_at_utc': datetime.now(timezone.utc).isoformat(),
        'scores_generated': False,
        'database_writes': False,
        'series': {},
    }
    for series_id in SERIES:
        try:
            result['series'][series_id] = audit_series(series_id, key)
        except Exception as exc:
            result['series'][series_id] = {
                'status': 'error',
                'error_type': type(exc).__name__,
                'note': 'Falha ao consultar a serie; nenhuma credencial e exibida.',
            }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if any(item.get('status') == 'error' for item in result['series'].values()):
        raise SystemExit('Falha em uma ou mais consultas; examine o JSON do artefato.')


if __name__ == '__main__':
    main()
