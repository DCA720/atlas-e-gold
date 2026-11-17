"""Atlas EUR RC6.4: horario programado HICP e snapshots ALFRED por data.
Diagnostico somente; snapshots diarios nao provam horario intradiario nem primeiro vintage.
"""
import json
import math
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from atlas_eur_rc63 import build_evidence

VERSION = 'eur-rc6.4-hicp-schedule-alfred-vintage-audit-0.6.4'
FRED_URL = 'https://api.stlouisfed.org/fred/series/observations'
EU_MANUAL = 'https://ec.europa.eu/eurostat/documents/3859598/18594110/KS-GQ-24-003-EN-N.pdf'
EU_CALENDAR = 'https://ec.europa.eu/eurostat/news/euro-indicators/release-calendar'
FRED_DOCS = 'https://fred.stlouisfed.org/docs/api/fred/series_observations.html'
PERIODS = {'2026-09': ('2026-10-15', '2026-10-14'),
           '2026-10': ('2026-11-17', '2026-11-10')}


def euro_schedule():
    rows = []
    for period, (date, _) in PERIODS.items():
        local = datetime.fromisoformat(date + 'T11:00:00').replace(tzinfo=ZoneInfo('Europe/Luxembourg'))
        rows.append({
            'source': 'EU_HICP_EA21', 'reference_period': period,
            'scheduled_local': local.isoformat(),
            'scheduled_utc': local.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'calendar_date_url': EU_CALENDAR, 'general_time_rule_url': EU_MANUAL,
            'evidence_kind': 'inferred_scheduled_time_from_official_general_rule',
            'actual_release_timestamp_verified': False,
            'original_published_value_verified': False,
            'eligible_for_verified_release_manifest': False,
        })
    return rows


def fetch_alfred_snapshot(vintage_date, api_key, timeout=30):
    """Return raw index levels as known on one *date*, not intraday release values."""
    if vintage_date not in {'2026-10-14', '2026-11-10'}:
        raise ValueError('Data de vintage fora da lista de auditoria')
    if not api_key:
        return {'status': 'missing_api_key', 'vintage_date': vintage_date}
    params = {
        'series_id': 'CPIAUCNS', 'api_key': api_key, 'file_type': 'json',
        'observation_start': '2025-09-01', 'observation_end': '2026-10-31',
        'vintage_dates': vintage_date, 'output_type': '1',
    }
    request = urllib.request.Request(FRED_URL + '?' + urllib.parse.urlencode(params),
                                     headers={'User-Agent': 'AtlasEUR-RC64/0.6.4'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content = response.read(2_000_001)
    if len(content) > 2_000_000:
        raise ValueError('Resposta ALFRED maior que 2MB')
    payload = json.loads(content)
    obs = payload.get('observations')
    if not isinstance(obs, list):
        raise ValueError('ALFRED sem observations')
    levels, missing, realtime = {}, [], []
    for item in obs:
        month = str(item.get('date', ''))[:7]
        if len(month) != 7 or month[4] != '-':
            continue
        realtime.append({'month': month, 'realtime_start': item.get('realtime_start'),
                         'realtime_end': item.get('realtime_end')})
        try:
            value = float(item.get('value', '.'))
            if not math.isfinite(value) or value <= 0:
                raise ValueError('invalid')
            levels[month] = value
        except (TypeError, ValueError):
            missing.append(month)
    return {'status': 'ok', 'vintage_date': vintage_date,
            'index_levels': {p: levels.get(p) for p in ('2025-09', '2025-10', '2026-09', '2026-10')},
            'missing_or_invalid': sorted(set(missing)),
            'realtime_metadata': [r for r in realtime if r['month'] in ('2025-09', '2025-10', '2026-09', '2026-10')],
            'observations_count': len(obs), 'source_documentation': FRED_DOCS,
            'daily_snapshot_not_intraday': True}


def evaluate(fetcher=fetch_alfred_snapshot, api_key=None, now=None):
    now = now or datetime.now(timezone.utc)
    _, us_manifest = build_evidence()
    schedules = euro_schedule()
    key = os.getenv('FRED_API_KEY') if api_key is None else api_key
    snapshots = {}
    for date in ('2026-10-14', '2026-11-10'):
        try:
            snapshots[date] = fetcher(date, key)
        except Exception as exc:
            snapshots[date] = {'status': 'error', 'vintage_date': date,
                               'error': f'{type(exc).__name__}: {str(exc)[:300]}'}
    audit = []
    for period, (eu_date, us_date) in PERIODS.items():
        snap = snapshots[us_date]
        values = snap.get('index_levels') or {}
        current = values.get(period)
        base_period = f'{int(period[:4])-1}{period[4:]}'
        base = values.get(base_period)
        yoy = round(100*(current/base-1), 8) if isinstance(current, (int,float)) and isinstance(base,(int,float)) and base>0 else None
        audit.append({'reference_period': period, 'us_vintage_date': us_date,
                      'us_index_at_vintage': current, 'us_base_period': base_period,
                      'us_base_index_at_vintage': base, 'us_yoy_at_vintage_date': yoy,
                      'us_snapshot_available': snap.get('status') == 'ok',
                      'eu_scheduled_date': eu_date,
                      'release_time_verified_for_both': False,
                      'vintage_value_verified_for_both': False})
    return {
        'model_version': VERSION, 'asof_utc': now.isoformat().replace('+00:00','Z'),
        'asset': 'EUR/USD', 'official_evidence': {
            'eurostat_general_time_rule': 'HICP news releases scheduled at 11:00 CET/CEST',
            'eurostat_manual_url': EU_MANUAL, 'eurostat_calendar_url': EU_CALENDAR,
            'alfred_api_documentation_url': FRED_DOCS,
        }, 'eu_scheduled_releases': schedules,
        'us_documented_release_manifest': us_manifest['records'],
        'alfred_daily_snapshots': snapshots, 'period_audit': audit,
        'eu_general_release_time_rule_documented': True,
        'eu_actual_release_time_per_observation_verified': False,
        'us_intraday_vintage_verified': False,
        'historical_vintage_per_observation_verified': False,
        'point_in_time_backtest_authorized': False,
        'eligibility': {'inflation': False, 'unemployment': False, 'rates': False, 'activity': False},
        'eligible_count': 0, 'coverage': 0.0, 'relative_score': None,
        'horizons': {'1d': {'score': None}, '5d': {'score': None}},
        'signals_generated': False, 'database_writes': False,
        'production_change_authorized': False, 'source_code_modified': False,
        'limitations': [
            'Regra geral de 11:00 e horario programado, nao prova de publicacao efetiva individual.',
            'Snapshots ALFRED por dia nao comprovam valor disponivel exatamente as 08:30 locais.',
            'Snapshot de um dia nao e necessariamente primeiro vintage nem prova de ausencia de revisoes.',
            'HICP EA21 nao possui vintage historico comprovado neste diagnostico.',
            'CPIAUCNS e HICP nao possuem equivalencia de cesta comprovada.',
            'Sem score, sinais, backtest ou alteracao em producao.',
        ],
    }


if __name__ == '__main__':
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2))
