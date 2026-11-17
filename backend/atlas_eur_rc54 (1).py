"""Atlas EUR RC5.4: consolidacao conservadora de evidencias e geografia.

Somente leitura; preserva o bloqueio de scores e sinais. Inspeciona configuracao
real de eur_macro_sources.SERIES e resultados auditados de RC5.3.
"""
import contextlib
import io
import json
from datetime import datetime, timezone

VERSION = 'eur-rc5.4-evidence-consolidation-0.5.4'
FACTORS = ('inflation', 'unemployment', 'rates', 'activity')


def _state(value):
    return 'confirmado' if value is True else 'nao_comprovado'


def evaluate(rc53, source_specs):
    registry = rc53.get('evidence_registry') or {}
    audited = (rc53.get('geography') or {}).get('audited_factors') or {}
    source_geo = {}
    for factor, name in [('inflation', 'hicp_yoy'), ('unemployment', 'unemployment')]:
        spec = source_specs.get(name) or {}
        source_geo[factor] = (spec.get('filters') or {}).get('geo')
    source_geo['activity'] = None  # RC3 usa fonte de atividade separada
    source_geo['rates'] = None  # instrumentos BCE/Fed nao sao geografia Eurostat

    all_known = [x for x in [source_geo['inflation'], source_geo['unemployment'],
                             audited.get('unemployment'), audited.get('activity')] if x]
    mismatch = len(set(all_known)) > 1
    evidence = {}
    for factor in FACTORS:
        old = registry.get(factor) or {}
        obs = old.get('observed') or {}
        checks = {}
        if factor in ('unemployment', 'activity'):
            checks['periodo_alinhado'] = {'estado': _state(obs.get('period_aligned')), 'origem': 'RC5.2/RC5.3'}
            checks['filtros_eurostat'] = {'estado': _state(obs.get('eurostat_filters_verified')), 'origem': 'RC5.2/RC5.3'}
        if factor == 'inflation':
            checks['geografia_coleta_original'] = {'estado': 'confirmado' if source_geo['inflation'] else 'nao_comprovado',
                                                   'valor': source_geo['inflation'], 'origem': 'eur_macro_sources.SERIES'}
        if factor == 'unemployment':
            checks['geografia_coleta_original'] = {'estado': 'confirmado' if source_geo['unemployment'] else 'nao_comprovado',
                                                   'valor': source_geo['unemployment'], 'origem': 'eur_macro_sources.SERIES'}
        if factor in ('unemployment', 'activity'):
            checks['geografia_auditada'] = {'estado': 'confirmado' if audited.get(factor) else 'nao_comprovado',
                                            'valor': audited.get(factor), 'origem': 'RC5.3'}
        checks['metodologia_equivalente'] = {'estado': _state(obs.get('methodology_fully_verified')), 'origem': 'RC5.3'}
        checks['vintage_publicacao'] = {'estado': 'nao_comprovado', 'origem': 'nao auditado'}
        if factor == 'inflation' and mismatch:
            checks['geografia_consistente_pipeline'] = {'estado': 'divergente', 'origem': 'configuracao RC3 vs auditorias RC5.2'}
        elif factor in ('unemployment', 'activity'):
            checks['geografia_consistente_pipeline'] = {'estado': 'parcial', 'origem': 'somente fontes identificadas'}
        evidence[factor] = {
            'verificacoes': checks,
            'requisitos_pendentes_rc53': old.get('required_for_future_eligibility', []),
            'score_eligible': False,
            'reason': 'Verificacoes de fonte nao comprovam metodologia, vintages nem capacidade preditiva'
        }

    return {
        'model_version': VERSION, 'asof_utc': datetime.now(timezone.utc).isoformat(),
        'asset': 'EUR/USD', 'source_model_version': rc53.get('model_version'),
        'geography': {
            'original_collection': source_geo,
            'audited_rc52': audited,
            'known_geographies': sorted(set(all_known)),
            'mismatch_detected': mismatch,
            'full_pipeline_verified': False,
            'note': 'Configuracao de coleta nao demonstra a geografia efetiva de cada observacao; requer verificacao na resposta da fonte.'
        },
        'evidence_registry': evidence,
        'eligible_factors': {f: False for f in FACTORS}, 'eligible_count': 0,
        'coverage': 0.0, 'relative_score': None,
        'horizons': {'1d': {'score': None}, '5d': {'score': None}},
        'signals_generated': False, 'database_writes': False,
        'status': 'Evidencias consolidadas sem autorizacao de score',
        'next_actions': [
            'Definir geografia alvo e atualizar consultas de modo consistente apos testar disponibilidade',
            'Validar dados observados, metodologias e ajustes em fontes primarias',
            'Obter historico de publicacao e vintages antes de sinais ou backtest'
        ]
    }


def main():
    from atlas_eur_rc53 import main as rc53_main
    from eur_macro_sources import SERIES
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc53_main()
    print(json.dumps(evaluate(json.loads(buf.getvalue()), SERIES), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
