"""Atlas EUR RC6.2: auditoria temporal fail-closed; nao produz sinais nem backtest.

Manifesto opcional (JSON): {"records":[{"source":"EU_HICP_EA21"|"US_CPIAUCNS",
 "reference_period":"YYYY-MM", "released_at_utc":"YYYY-MM-DDTHH:MM:SSZ",
 "evidence_url":"https://...", "vintage_id":"..."}]}
Os horarios sao fornecidos pelo operador, NAO inferidos de meses de referencia.
"""
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlparse
from atlas_eur_rc61 import evaluate as rc61_evaluate

VERSION = 'eur-rc6.2-temporal-integrity-0.6.2'
SOURCES = ('EU_HICP_EA21', 'US_CPIAUCNS')
MONTH = re.compile(r'^\d{4}-(0[1-9]|1[0-2])$')


def parse_utc(value):
    if not isinstance(value, str) or not value.endswith('Z'):
        raise ValueError('released_at_utc exige ISO8601 UTC com Z')
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None or dt.utcoffset().total_seconds() != 0:
        raise ValueError('timestamp nao UTC')
    return dt


def audit_manifest(manifest, asof):
    errors, indexed, accepted = [], {}, []
    records = manifest.get('records', []) if isinstance(manifest, dict) else []
    if not isinstance(records, list):
        return {'status': 'invalid', 'errors': ['records deve ser lista'], 'accepted_records': 0, 'records': []}, {}
    for i, item in enumerate(records):
        try:
            if not isinstance(item, dict):
                raise ValueError('registro nao e objeto')
            source, period = item.get('source'), item.get('reference_period')
            if source not in SOURCES or not isinstance(period, str) or not MONTH.fullmatch(period):
                raise ValueError('fonte ou mes invalido')
            released = parse_utc(item.get('released_at_utc'))
            if released > asof:
                raise ValueError('data de divulgacao futura em relacao a auditoria')
            if released.strftime('%Y-%m') < period:
                raise ValueError('divulgacao anterior ao mes de referencia')
            url = item.get('evidence_url', '')
            parsed = urlparse(url) if isinstance(url, str) else None
            if not parsed or parsed.scheme != 'https' or not parsed.netloc:
                raise ValueError('evidence_url HTTPS obrigatoria')
            vintage = item.get('vintage_id')
            if vintage is not None and (not isinstance(vintage, str) or not vintage.strip()):
                raise ValueError('vintage_id invalido')
            key = (source, period)
            if key in indexed:
                raise ValueError('registro duplicado: fonte/mes')
            indexed[key] = {'released_at_utc': released.isoformat().replace('+00:00', 'Z'),
                            'evidence_url': url, 'vintage_id': vintage}
            accepted.append({'source': source, 'reference_period': period,
                             'released_at_utc': indexed[key]['released_at_utc'],
                             'has_vintage_id': bool(vintage)})
        except (ValueError, TypeError, OverflowError) as exc:
            errors.append({'index': i, 'error': str(exc)[:160]})
    return {'status': 'invalid' if errors else ('provided_unverified' if accepted else 'empty'),
            'errors': errors, 'accepted_records': len(accepted), 'records': accepted,
            'note': 'Validacao de formato nao comprova autenticidade da fonte nem vintage historico.'}, indexed


def availability(indexed, period, at_utc):
    """Retorna disponibilidade documental; nao certifica que o valor era o publicado na epoca."""
    result = {}
    for source in SOURCES:
        record = indexed.get((source, period))
        if not record:
            result[source] = {'available': False, 'reason': 'release_timestamp_nao_documentado'}
        else:
            released = parse_utc(record['released_at_utc'])
            result[source] = {'available': at_utc >= released,
                              'reason': 'documented_release_time_reached' if at_utc >= released else 'not_yet_released',
                              'released_at_utc': record['released_at_utc'],
                              'vintage_documented': bool(record['vintage_id'])}
    return {'reference_period': period, 'asof_utc': at_utc.isoformat().replace('+00:00', 'Z'),
            'sources': result, 'both_documented_releases_reached': all(v['available'] for v in result.values()),
            'point_in_time_values_verified': False}


def evaluate(rc61_fetcher=rc61_evaluate, manifest=None, asof=None):
    now = asof or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset().total_seconds() != 0:
        raise ValueError('asof deve ser UTC')
    previous = rc61_fetcher()
    loaded = manifest if manifest is not None else {'records': []}
    audit, indexed = audit_manifest(loaded, now)
    latest = previous.get('source_audit', {}).get('latest_aligned_period')
    periods = sorted(set([p for _, p in indexed] + ([latest] if latest else [])))
    checks = [availability(indexed, period, now) for period in periods[-12:]]
    return {
        'model_version': VERSION, 'asof_utc': now.isoformat().replace('+00:00', 'Z'),
        'asset': 'EUR/USD', 'upstream_rc61': {
            'technical_diagnostic_ready': previous.get('technical_diagnostic_ready', False),
            'preferred_us_series': previous.get('source_audit', {}).get('preferred_us_series_for_diagnostic'),
            'latest_aligned_period': latest,
            'aligned_period_count': previous.get('source_audit', {}).get('aligned_period_count'),
        },
        'manifest_audit': audit,
        'release_time_checks': checks,
        'release_timestamp_per_observation_verified': False,
        'historical_vintage_per_observation_verified': False,
        'point_in_time_backtest_authorized': False,
        'eligibility': {'inflation': False, 'unemployment': False, 'rates': False, 'activity': False},
        'eligible_count': 0, 'coverage': 0.0, 'relative_score': None,
        'horizons': {'1d': {'score': None}, '5d': {'score': None}},
        'signals_generated': False, 'database_writes': False,
        'production_change_authorized': False, 'source_code_modified': False,
        'limitations': [
            'Sem manifesto, nenhum horario de divulgacao e presumido.',
            'Manifesto opcional verifica formato e cronologia, nao autenticidade nem valores vintage.',
            'Nao e permitido backtest ponto-no-tempo com dados atuais revisados.',
            'Nenhum score, sinal ou escrita em banco.',
        ],
    }


if __name__ == '__main__':
    path = os.environ.get('EUR_RELEASE_MANIFEST')
    manifest = None
    if path:
        with open(path, encoding='utf-8') as fh:
            manifest = json.load(fh)
    print(json.dumps(evaluate(manifest=manifest), ensure_ascii=False, indent=2))
