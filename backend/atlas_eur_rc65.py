"""Atlas EUR RC6.5: auditoria de revisoes do CPI via ALFRED e lacunas HICP.
Somente diagnostico: vintage por dia nao comprova divulgacao intradiaria.
"""
import json
import os
from datetime import datetime, timezone
from atlas_eur_rc64 import fetch_alfred_snapshot, euro_schedule

VERSION = 'eur-rc6.5-cpi-revision-eu-archive-audit-0.6.5'
DATES = ('2026-10-14', '2026-11-10', '2026-11-17')
MONTHS = ('2025-09', '2025-10', '2026-09', '2026-10')


def get_snapshot(date, key):
    """RC6.4 limita datas; aqui usamos a mesma consulta com data adicional autorizada."""
    if date in ('2026-10-14', '2026-11-10'):
        return fetch_alfred_snapshot(date, key)
    if date != '2026-11-17':
        raise ValueError('Data nao autorizada')
    import urllib.parse
    import urllib.request
    import math
    params = {'series_id': 'CPIAUCNS', 'api_key': key, 'file_type': 'json',
              'observation_start': '2025-09-01', 'observation_end': '2026-10-31',
              'vintage_dates': date, 'output_type': '1'}
    if not key:
        return {'status': 'missing_api_key', 'vintage_date': date}
    url = 'https://api.stlouisfed.org/fred/series/observations?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'User-Agent': 'AtlasEUR-RC65/0.6.5'})
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError('Resposta acima de 2MB')
    obs = json.loads(raw).get('observations')
    if not isinstance(obs, list):
        raise ValueError('Observations ausente')
    values = {}
    for item in obs:
        month = str(item.get('date', ''))[:7]
        if month not in MONTHS:
            continue
        try:
            val = float(item.get('value', '.'))
            values[month] = val if math.isfinite(val) and val > 0 else None
        except (ValueError, TypeError):
            values[month] = None
    return {'status': 'ok', 'vintage_date': date,
            'index_levels': {m: values.get(m) for m in MONTHS},
            'observations_count': len(obs), 'daily_snapshot_not_intraday': True}


def compare_snapshots(snapshots):
    comparisons = []
    for older, newer in zip(DATES, DATES[1:]):
        a, b = snapshots.get(older, {}), snapshots.get(newer, {})
        valid = a.get('status') == 'ok' and b.get('status') == 'ok'
        for month in MONTHS:
            left = (a.get('index_levels') or {}).get(month) if valid else None
            right = (b.get('index_levels') or {}).get(month) if valid else None
            if not valid:
                status = 'comparison_unavailable'
            elif left is None and right is None:
                status = 'missing_in_both'
            elif left is None:
                status = 'newly_present_not_necessarily_first_release'
            elif right is None:
                status = 'became_missing'
            elif abs(left-right) > 1e-9:
                status = 'value_changed_between_snapshots'
            else:
                status = 'unchanged_between_snapshots'
            comparisons.append({'from_vintage_date': older, 'to_vintage_date': newer,
                                'reference_period': month, 'earlier_index': left,
                                'later_index': right,
                                'delta_index_points': round(right-left, 8) if left is not None and right is not None else None,
                                'status': status,
                                'revision_event_timestamp_verified': False})
    return comparisons


def evaluate(fetcher=get_snapshot, api_key=None, now=None):
    now = now or datetime.now(timezone.utc)
    key = os.getenv('FRED_API_KEY') if api_key is None else api_key
    snapshots = {}
    for date in DATES:
        try:
            snapshots[date] = fetcher(date, key)
        except Exception as exc:
            snapshots[date] = {'status': 'error', 'vintage_date': date,
                               'error': f'{type(exc).__name__}: {str(exc)[:250]}'}
    comparisons = compare_snapshots(snapshots)
    eu = [{**row, 'historical_value_source_verified': False,
           'archived_original_release_retrieved': False,
           'revision_history_retrieved': False}
          for row in euro_schedule()]
    return {
        'model_version': VERSION, 'asof_utc': now.isoformat().replace('+00:00','Z'),
        'asset': 'EUR/USD', 'us_series': 'CPIAUCNS',
        'alfred_snapshots': snapshots, 'us_revision_comparisons': comparisons,
        'us_comparison_summary': {
            'compared_pairs': len(DATES)-1,
            'changed_values': sum(r['status']=='value_changed_between_snapshots' for r in comparisons),
            'newly_present': sum(r['status']=='newly_present_not_necessarily_first_release' for r in comparisons),
            'missing_in_both': sum(r['status']=='missing_in_both' for r in comparisons),
            'unavailable_comparisons': sum(r['status']=='comparison_unavailable' for r in comparisons)},
        'eu_hicp_archive_audit': {
            'dataset': 'prc_hicp_minr', 'geo': 'EA21', 'coicop18': 'TOTAL', 'unit': 'RCH_A',
            'scheduled_releases': eu,
            'official_calendar': 'https://ec.europa.eu/eurostat/news/euro-indicators/release-calendar',
            'eurostat_data_revision_policy_reference': 'https://ec.europa.eu/eurostat/web/main/data/database',
            'original_publication_values_retrieved': False,
            'historical_dataset_vintages_retrieved': False,
            'status': 'archive_evidence_pending',
            'note': 'Links sao pontos de partida, nao comprovantes de valores originais.'},
        'us_daily_snapshots_are_intraday_evidence': False,
        'us_first_release_values_verified': False,
        'eu_original_values_verified': False,
        'historical_vintage_per_observation_verified': False,
        'point_in_time_backtest_authorized': False,
        'eligibility': {'inflation': False, 'unemployment': False, 'rates': False, 'activity': False},
        'eligible_count': 0, 'coverage': 0.0, 'relative_score': None,
        'horizons': {'1d': {'score': None}, '5d': {'score': None}},
        'signals_generated': False, 'database_writes': False,
        'production_change_authorized': False, 'source_code_modified': False,
        'limitations': [
            'Comparacao de snapshots identifica diferencas, mas nao data exata de revisao.',
            'Valor novo entre snapshots nao comprova primeira publicacao.',
            'Datas ALFRED nao demonstram disponibilidade intradiaria.',
            'Arquivos originais HICP nao foram obtidos nem verificados nesta versao.',
            'Outubro de 2025 ausente nao pode ser interpolado.',
            'Nenhum score, sinal, backtest ou escrita em banco.']}


if __name__ == '__main__':
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2))
