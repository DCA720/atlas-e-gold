"""Atlas EUR RC6.7: consolidacao documental HICP x CPI (diagnostico somente leitura)."""
import json
from datetime import datetime, timezone
from atlas_eur_rc65 import evaluate as evaluate_us
from atlas_eur_rc66 import evaluate as evaluate_eu

VERSION = 'eur-rc6.7-inflation-evidence-consolidation-0.6.7'
EU_METHOD_URL = 'https://ec.europa.eu/eurostat/web/products-euro-indicators/w/2-16102026-ap'
EU_FLASH_URL = 'https://ec.europa.eu/eurostat/web/products-euro-indicators/w/2-02102026-ap'


def _get_release(records, period, kind):
    return next((r for r in records if r.get('period') == period and r.get('kind') == kind), None)


def evaluate(eu_fetcher=None, us_fetcher=None, api_key=None, now=None):
    now = now or datetime.now(timezone.utc)
    kwargs_eu = {'now': now}
    kwargs_us = {'now': now, 'api_key': api_key}
    if eu_fetcher is not None:
        kwargs_eu['fetcher'] = eu_fetcher
    if us_fetcher is not None:
        kwargs_us['fetcher'] = us_fetcher
    eu = evaluate_eu(**kwargs_eu)
    us = evaluate_us(**kwargs_us)
    releases = eu['official_release_archive']
    september_flash = _get_release(releases, '2026-09', 'flash')
    september_full = _get_release(releases, '2026-09', 'full')
    october_flash = _get_release(releases, '2026-10', 'flash')
    eu_events = []
    for r in releases:
        eu_events.append({
            'period': r['period'], 'kind': r['kind'], 'publication_date': r['publication_date'],
            'headline_yoy_pct': r['reported_yoy_pct'] if r.get('headline_rate_verified_in_page') else None,
            'headline_confirmed': bool(r.get('headline_rate_verified_in_page')),
            'source_url': r['url'], 'intraday_time_verified': False,
            'full_dataset_vintage_verified': False,
            'status': r['status'],
        })
    comparisons = us.get('us_revision_comparisons', [])
    snapshots = us.get('alfred_snapshots', {})
    sep_snap = snapshots.get('2026-10-14', {})
    sep_values = sep_snap.get('index_levels', {}) if sep_snap.get('status') == 'ok' else {}
    sep_current = sep_values.get('2026-09')
    sep_base = sep_values.get('2025-09')
    us_yoy = round((sep_current / sep_base - 1) * 100, 8) if isinstance(sep_current, (int, float)) and isinstance(sep_base, (int, float)) and sep_base > 0 else None
    eu_sep = september_full['reported_yoy_pct'] if september_full and september_full.get('headline_rate_verified_in_page') else None
    descriptive_spread = round(eu_sep - us_yoy, 8) if eu_sep is not None and us_yoy is not None else None
    return {
        'model_version': VERSION, 'asof_utc': now.isoformat().replace('+00:00', 'Z'), 'asset': 'EUR/USD',
        'euro_area_composition': {
            'up_to_2025_12': 'EA20', 'from_2026_01': 'EA21',
            'published_aggregate': 'evolving_composition_chain_linked',
            'evidence_url': EU_METHOD_URL,
            'press_release_and_fixed_geo_series_identical_verified': False,
            'note': 'Nao assumir que a serie fixa EA21 reproduz exatamente os agregados historicos de composicao variavel.'
        },
        'calendar_reconciliation': {
            'reference_period': '2026-09', 'old_rc65_scheduled_date': '2026-10-15',
            'official_flash_next_full_release_date': '2026-10-16',
            'official_full_release_date': september_full['publication_date'] if september_full else None,
            'flash_page_url': EU_FLASH_URL,
            'full_page_url': EU_METHOD_URL,
            'classification': 'prior_calendar_record_conflicts_with_official_release_evidence',
            'old_record_retained_for_audit': True,
            'actual_intraday_release_timestamp_verified': False,
        },
        'eu_release_events': eu_events,
        'eu_flash_full_comparison': {
            'period': '2026-09',
            'flash_headline_confirmed': bool(september_flash and september_flash.get('headline_rate_verified_in_page')),
            'full_headline_confirmed': bool(september_full and september_full.get('headline_rate_verified_in_page')),
            'flash_yoy_pct': september_flash['reported_yoy_pct'] if september_flash and september_flash.get('headline_rate_verified_in_page') else None,
            'full_yoy_pct': eu_sep,
            'same_headline': bool(september_flash and september_full and september_flash.get('headline_rate_verified_in_page') and september_full.get('headline_rate_verified_in_page') and september_flash['reported_yoy_pct'] == september_full['reported_yoy_pct']),
            'component_values_identical_verified': False,
        },
        'october_eu_status': {
            'flash_confirmed': bool(october_flash and october_flash.get('headline_rate_verified_in_page')),
            'flash_yoy_pct': october_flash['reported_yoy_pct'] if october_flash and october_flash.get('headline_rate_verified_in_page') else None,
            'full_release_verified': False,
            'note': 'Nao inferir publicacao completa a partir de data programada.'
        },
        'us_vintage_audit': {
            'series': 'CPIAUCNS', 'snapshot_dates': list(snapshots.keys()),
            'snapshot_status': {k: v.get('status') for k, v in snapshots.items()},
            'revision_summary': us.get('us_comparison_summary'),
            'september_2026_yoy_daily_vintage_pct': us_yoy,
            'october_2025_base_missing': all((v.get('index_levels') or {}).get('2025-10') is None for v in snapshots.values() if v.get('status') == 'ok'),
            'first_release_intraday_value_verified': False,
        },
        'descriptive_september_comparison': {
            'period': '2026-09', 'eu_full_hicp_yoy_pct': eu_sep,
            'us_cpi_nsa_yoy_pct': us_yoy, 'eu_minus_us_pp': descriptive_spread,
            'methodological_equivalence_verified': False,
            'trading_signal': False,
        },
        'quality_gates': {
            'european_press_headlines_confirmed': eu['eu_original_press_release_headlines_verified'],
            'european_full_series_vintages_verified': False,
            'us_daily_vintages_available': any(v.get('status') == 'ok' for v in snapshots.values()),
            'us_intraday_first_release_verified': False,
            'cross_region_methodology_equivalent': False,
            'point_in_time_backtest_authorized': False,
        },
        'next_module': 'ECB_FED_interest_rates',
        'outstanding': [
            'Comprovar historico completo de vintages HICP e valores por instante de publicacao.',
            'Verificar diferenca entre serie fixa EA21 e agregado encadeado publicado.',
            'Validar equivalencia metodologica HICP vs CPI-U NSA antes de qualquer score.',
            'Auditar horarios efetivos e valores intradiarios originais.',
            'Iniciar modulo de juros BCE x Fed independentemente destas pendencias.'
        ],
        'eligibility': {'inflation': False, 'unemployment': False, 'rates': False, 'activity': False},
        'eligible_count': 0, 'coverage': 0.0, 'relative_score': None,
        'horizons': {'1d': {'score': None}, '5d': {'score': None}},
        'signals_generated': False, 'database_writes': False,
        'production_change_authorized': False, 'source_code_modified': False,
        'limitations': ['RC6.7 consolida evidencias, nao aprova fator de inflacao.',
                        'Snapshots ALFRED diarios nao equivalem a dados intradiarios.',
                        'Comunicados oficiais nao sao vintages integrais do dataset.',
                        'Nenhum score, sinal, backtest ou alteracao de producao.']
    }


if __name__ == '__main__':
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2))
