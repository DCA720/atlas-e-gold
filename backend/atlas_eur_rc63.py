"""Atlas EUR RC6.3: calendario oficial, evidencias parciais e bloqueio fail-closed.

As entradas sao referencias curadas a documentos oficiais, NAO prova automatica de
publicacao efetiva ou de valor vintage. Nunca gera scores ou sinais.
"""
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from atlas_eur_rc62 import audit_manifest, availability, evaluate as rc62_evaluate

VERSION = 'eur-rc6.3-official-release-evidence-0.6.3'
EVIDENCE = [
    {'source': 'US_CPIAUCNS', 'reference_period': '2026-09',
     'local_date': '2026-10-14', 'local_time': '08:30:00',
     'timezone': 'America/New_York', 'evidence_kind': 'official_release_calendar',
     'evidence_url': 'https://www.bls.gov/schedule/news_release/cpi.htm',
     'note': 'Calendario do BLS; nao comprova vintage do indice.'},
    {'source': 'US_CPIAUCNS', 'reference_period': '2026-10',
     'local_date': '2026-11-10', 'local_time': '08:30:00',
     'timezone': 'America/New_York', 'evidence_kind': 'official_release_and_calendar',
     'evidence_url': 'https://www.bls.gov/news.release/cpi.htm',
     'note': 'Comunicado do BLS confirma embargo; nao restaura base de outubro de 2025.'},
    {'source': 'EU_HICP_EA21', 'reference_period': '2026-09',
     'local_date': '2026-10-15', 'local_time': None,
     'timezone': 'Europe/Luxembourg', 'evidence_kind': 'official_release_calendar_date_only',
     'evidence_url': 'https://ec.europa.eu/eurostat/news/euro-indicators/release-calendar',
     'note': 'Calendario informa data; hora exata ainda nao comprovada.'},
    {'source': 'EU_HICP_EA21', 'reference_period': '2026-10',
     'local_date': '2026-11-17', 'local_time': None,
     'timezone': 'Europe/Luxembourg', 'evidence_kind': 'official_release_calendar_date_only',
     'evidence_url': 'https://ec.europa.eu/eurostat/news/euro-indicators/release-calendar',
     'note': 'Calendario informa data; hora exata ainda nao comprovada.'},
]


def build_evidence(evidence=EVIDENCE):
    rows, manifest = [], {'records': []}
    for item in evidence:
        row = dict(item)
        if item['local_time'] is None:
            row['status'] = 'date_only_not_eligible_for_manifest'
            row['released_at_utc'] = None
        else:
            local = datetime.fromisoformat(item['local_date'] + 'T' + item['local_time']).replace(
                tzinfo=ZoneInfo(item['timezone']))
            utc = local.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
            row['status'] = 'calendar_time_documented_vintage_unverified'
            row['released_at_utc'] = utc
            manifest['records'].append({
                'source': item['source'], 'reference_period': item['reference_period'],
                'released_at_utc': utc, 'evidence_url': item['evidence_url']})
        rows.append(row)
    return rows, manifest


def evaluate(rc62_fetcher=rc62_evaluate, asof=None):
    now = asof or datetime.now(timezone.utc)
    rows, manifest = build_evidence()
    audit, indexed = audit_manifest(manifest, now)
    upstream = rc62_fetcher()
    periods = ['2026-09', '2026-10']
    checks = [availability(indexed, p, now) for p in periods]
    return {
        'model_version': VERSION, 'asof_utc': now.isoformat().replace('+00:00', 'Z'),
        'asset': 'EUR/USD',
        'upstream_rc62': {'technical_diagnostic_ready': upstream['upstream_rc61']['technical_diagnostic_ready'],
                          'latest_aligned_period': upstream['upstream_rc61']['latest_aligned_period']},
        'official_evidence': rows, 'manifest_audit': audit,
        'release_time_checks': checks,
        'us_release_times_documented': len(manifest['records']) == 2 and not audit['errors'],
        'eu_release_times_documented': False,
        'all_release_timestamps_verified': False,
        'historical_vintage_per_observation_verified': False,
        'point_in_time_backtest_authorized': False,
        'eligibility': {'inflation': False, 'unemployment': False, 'rates': False, 'activity': False},
        'eligible_count': 0, 'coverage': 0.0, 'relative_score': None,
        'horizons': {'1d': {'score': None}, '5d': {'score': None}},
        'signals_generated': False, 'database_writes': False,
        'production_change_authorized': False, 'source_code_modified': False,
        'limitations': [
            'Datas do calendario nao provam publicacao efetiva nem valor inicialmente divulgado.',
            'Eurostat: data documentada, hora nao confirmada; nenhum horario inventado.',
            'Manifesto do RC6.2 valida formato, nao autenticidade documental.',
            'Falta historico de vintages e revisoes; backtest e score bloqueados.',
            'Calendarios podem ser atualizados; fontes e evidencias exigem auditoria historica.'
        ]
    }


if __name__ == '__main__':
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2))
