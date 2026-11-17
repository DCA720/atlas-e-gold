"""Atlas EUR RC5.6: auditoria de selecao de fontes e janelas temporais.
Somente leitura, sem pontuacao ou alteracoes em producao.
"""
import contextlib
import io
import json
from datetime import datetime, timezone
from atlas_eur_rc552 import fetch, SPECS
from eur_macro_sources import SERIES, collect_eurostat

VERSION = 'eur-rc5.6-source-window-audit-0.5.6'


def _period_age(period, now):
    if not period:
        return None
    try:
        if '-Q' in period:
            y, q = period.split('-Q')
            return (now.year - int(y)) * 4 + (now.month - 1) // 3 - (int(q) - 1)
        y, m = period.split('-')
        return (now.year - int(y)) * 12 + now.month - int(m)
    except (ValueError, TypeError):
        return None


def _summarize(entry, now, factor):
    if entry['status'] != 'ok':
        return {'status': entry['status'], 'reason': entry.get('reason') or entry.get('error'),
                'latest_period': None, 'observation_count': 0, 'age_periods': None,
                'freshness': 'indeterminada'}
    latest = entry['latest_period']
    age = _period_age(latest, now)
    # Limiares de TRIAGEM, nao equivalencia ou elegibilidade.
    threshold = 2 if factor == 'activity' else 3
    freshness = ('indeterminada' if age is None or age < 0 else
                 'dentro_do_limiar_exploratorio' if age <= threshold else 'defasado')
    return {'status': 'ok', 'latest_period': latest,
            'latest_value': entry['observations'][latest],
            'observation_count': entry['observation_count'],
            'age_periods': age, 'age_unit': 'trimestres' if factor == 'activity' else 'meses',
            'freshness': freshness, 'threshold_exploratory': threshold}


def evaluate(now=None, fetcher=fetch, original_collector=collect_eurostat):
    now = now or datetime.now(timezone.utc)
    diagnostics = {}
    for factor, (dataset, filters) in SPECS.items():
        geos = {}
        for geo in ('EA20', 'EA21'):
            try:
                entry = {'status': 'ok', **fetcher(dataset, filters, geo)}
            except Exception as exc:
                # A fonte pode nao retornar a geografia; registrar, sem inventar valor.
                kind = 'sem_dados' if type(exc).__name__ == 'NoData' else 'erro'
                entry = {'status': kind, 'reason': f'{type(exc).__name__}: {str(exc)[:250]}'}
            geos[geo] = _summarize(entry, now, factor)
        candidates = [geo for geo, item in geos.items() if item['status'] == 'ok']
        diagnostics[factor] = {
            'dataset': dataset, 'geographies': geos,
            'available_geographies': candidates,
            'preferred_for_diagnostic_only': ('EA21' if 'EA21' in candidates else
                                              'EA20' if 'EA20' in candidates else None),
            'production_change_authorized': False,
            'methodology_verified': False,
            'vintage_verified': False,
        }
    originals = {}
    for name, spec in SERIES.items():
        try:
            result = original_collector(name)
            originals[name] = {'status': 'ok', 'dataset': result['dataset'],
                               'configured_geo': spec['filters'].get('geo'),
                               'latest': result['latest'],
                               'recent_count': len(result.get('recent', [])),
                               'collection_window': 36}
        except Exception as exc:
            originals[name] = {'status': 'erro', 'configured_geo': spec['filters'].get('geo'),
                               'reason': f'{type(exc).__name__}: {str(exc)[:250]}'}
    inflation = originals.get('hicp_yoy', {})
    audit_inf = diagnostics['inflation']['geographies']['EA20']
    comparison = {
        'rc552_window': 12, 'original_window': 36,
        'rc552_latest_ea20': audit_inf['latest_period'],
        'original_latest_ea20': (inflation.get('latest') or {}).get('date'),
        'original_latest_value': (inflation.get('latest') or {}).get('value'),
        'same_latest_period': (audit_inf['latest_period'] == (inflation.get('latest') or {}).get('date')
                               if audit_inf['latest_period'] and inflation.get('latest') else None),
        'interpretation': 'Janelas de 12 e 36 periodos diferem; se os ultimos periodos nao coincidirem, investigar resposta da fonte e disponibilidade por geografia. Nao inferir erro apenas pela diferenca.'
    }
    return {
        'model_version': VERSION, 'asof_utc': now.isoformat(), 'asset': 'EUR/USD',
        'source_policy': 'diagnostico_apenas_sem_migracao_automatica',
        'diagnostics': diagnostics, 'original_pipeline': originals,
        'inflation_window_comparison': comparison,
        'full_pipeline_verified': False, 'source_code_modified': False,
        'eligible_factors': {k: False for k in ('inflation','unemployment','rates','activity')},
        'eligible_count': 0, 'coverage': 0.0, 'relative_score': None,
        'horizons': {'1d': {'score': None}, '5d': {'score': None}},
        'signals_generated': False, 'database_writes': False,
        'limitations': ['Limiar de atualidade e exploratorio, nao autoriza score',
                        'Diferentes geografias nao sao automaticamente comparaveis',
                        'Sem vintages e datas de divulgacao nao ha backtest ponto-no-tempo'],
    }


def main():
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
