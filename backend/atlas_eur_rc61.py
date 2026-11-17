"""Atlas EUR RC6.1: evidencias oficiais, lacunas e barreiras temporais. Somente diagnostico."""
import json
from datetime import datetime, timezone
from atlas_eur_rc60 import evaluate as rc60_evaluate

VERSION = 'eur-rc6.1-inflation-methodology-timing-audit-0.6.1'
OFFICIAL_REFERENCES = {
    'eurostat_hicp': {
        'url': 'https://ec.europa.eu/eurostat/web/euro-indicators/information-data/consumer-housing-prices',
        'claim': 'HICP e publicado sem ajuste sazonal; indicador de precos ao consumidor europeu.',
        'seasonally_adjusted': False,
        'metadata_confirmed': True,
    },
    'fred_cpiaucns': {
        'url': 'https://fred.stlouisfed.org/series/CPIAUCNS',
        'claim': 'CPI-U all items, indice mensal nao ajustado sazonalmente; fonte BLS via FRED.',
        'seasonally_adjusted': False,
        'metadata_confirmed': True,
    },
    'bls_missing_october_2025': {
        'url': 'https://www.bls.gov/charts/consumer-price-index/',
        'claim': 'BLS informa ausencia de indices de outubro de 2025 para a maioria das series devido a interrupcao de financiamento.',
        'missing_month': '2025-10',
        'applies_to_all_cpi_series': False,
    },
    'bls_2026_release': {
        'url': 'https://www.bls.gov/news.release/pdf/cpi.pdf',
        'claim': 'BLS nao disponibiliza variacoes anuais de outubro de 2026 para itens afetados pela falta de base de outubro de 2025.',
    },
}


def evaluate(rc60_fetcher=rc60_evaluate):
    previous = rc60_fetcher()
    us = previous.get('us_series', {})
    nsa = us.get('CPIAUCNS', {})
    sa = us.get('CPIAUCSL', {})
    europe = previous.get('europe', {})
    aligned = previous.get('eu_us_alignment', {}).get('CPIAUCNS', {})
    missing_2025_nsa = '2025-10' in nsa.get('missing_or_invalid_periods', [])
    missing_2025_sa = '2025-10' in sa.get('missing_or_invalid_periods', [])
    missing_base_2026_nsa = any(x.get('period') == '2026-10' and x.get('missing_base') == '2025-10'
                                for x in nsa.get('missing_base_periods', []))
    missing_base_2026_sa = any(x.get('period') == '2026-10' and x.get('missing_base') == '2025-10'
                               for x in sa.get('missing_base_periods', []))
    nsa_ok = nsa.get('status') == 'ok' and bool(nsa.get('observations'))
    eu_ok = europe.get('status') == 'ok' and europe.get('geo') == 'EA21'
    same_month_count = aligned.get('common_period_count', 0)
    return {
        'model_version': VERSION, 'asof_utc': datetime.now(timezone.utc).isoformat(),
        'asset': 'EUR/USD',
        'official_references': OFFICIAL_REFERENCES,
        'source_audit': {
            'europe_hicp': {'status': europe.get('status'), 'dataset': europe.get('dataset'),
                            'geo': europe.get('geo'), 'seasonally_adjusted': False,
                            'last_period': europe.get('last_period')},
            'us_cpi_nsa': {'status': nsa.get('status'), 'dataset': 'CPIAUCNS',
                           'seasonally_adjusted': False, 'last_yoy_period': nsa.get('last_yoy_period')},
            'us_cpi_sa_control': {'status': sa.get('status'), 'dataset': 'CPIAUCSL',
                                  'seasonally_adjusted': True},
            'seasonal_adjustment_alignment_confirmed': eu_ok and nsa_ok,
            'basket_and_methodology_equivalence_confirmed': False,
            'preferred_us_series_for_diagnostic': 'CPIAUCNS',
            'preferred_series_approved_for_scoring': False,
            'aligned_period_count': same_month_count,
            'latest_aligned_period': aligned.get('latest_common_period'),
            'latest_descriptive_spread_pp': aligned.get('latest_common_spread_pp'),
        },
        'missing_data_audit': {
            'october_2025_nsa_missing': missing_2025_nsa,
            'october_2025_sa_missing': missing_2025_sa,
            'october_2026_nsa_yoy_blocked_by_missing_base': missing_base_2026_nsa,
            'october_2026_sa_yoy_blocked_by_missing_base': missing_base_2026_sa,
            'bls_general_explanation_documented': True,
            'bls_explanation_individually_verified_for_each_series': False,
            'imputation_performed': False,
            'nsa_missing_or_invalid_periods': nsa.get('missing_or_invalid_periods', []),
            'sa_missing_or_invalid_periods': sa.get('missing_or_invalid_periods', []),
        },
        'temporal_integrity': {
            'reference_periods_aligned': same_month_count > 0,
            'release_timestamp_per_observation_verified': False,
            'eu_release_timestamp_per_observation_verified': False,
            'us_release_timestamp_per_observation_verified': False,
            'historical_vintage_per_observation_verified': False,
            'point_in_time_backtest_authorized': False,
            'reason': 'Mes de referencia nao e data de publicacao; dados atuais podem conter revisoes.',
        },
        'technical_diagnostic_ready': eu_ok and nsa_ok and same_month_count > 0,
        'eligible_factors': {k: False for k in ('inflation', 'unemployment', 'rates', 'activity')},
        'eligible_count': 0, 'coverage': 0.0, 'relative_score': None,
        'horizons': {'1d': {'score': None}, '5d': {'score': None}},
        'signals_generated': False, 'database_writes': False,
        'production_change_authorized': False, 'source_code_modified': False,
        'limitations': [
            'Fontes oficiais fundamentam ajuste sazonal, nao equivalencia de cestas CPI e HICP.',
            'Justificativa geral BLS para outubro de 2025 nao substitui auditoria individual de cada serie.',
            'Nao ha historico verificado de horarios de divulgacao e vintages por observacao.',
            'Diferencial descritivo nao e sinal de EUR/USD; nenhum score ou escrita em producao.',
        ],
    }


if __name__ == '__main__':
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2))
