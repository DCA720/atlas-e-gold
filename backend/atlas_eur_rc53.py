"""Atlas EUR RC5.3: auditoria de geografia, evidencias e bloqueios (somente leitura).

Reutiliza RC5.2. Nao calcula scores, nao gera sinais, nao grava dados.
A verificacao de metadados NAO certifica comparabilidade metodologica.
"""
import contextlib
import io
import json
from datetime import datetime, timezone

VERSION = 'eur-rc5.3-geography-evidence-audit-0.5.3'
FACTORS = ('inflation', 'unemployment', 'rates', 'activity')

# Regras de evidencia explicitamente exigidas para liberar um fator em versoes futuras.
REQUIRED_EVIDENCE = {
    'inflation': ['mesmo_periodo', 'indices_harmonizados', 'observacoes_validas', 'vintage_disponivel'],
    'unemployment': ['mesmo_periodo', 'definicao_populacional_comparavel', 'ajuste_sazonal_documentado', 'vintage_disponivel'],
    'rates': ['instrumentos_comparaveis', 'mesma_data_referencia', 'convencao_de_taxa_documentada', 'vintage_disponivel'],
    'activity': ['mesmo_trimestre', 'taxa_qoq_nao_anualizada', 'ajuste_sazonal_documentado', 'geografia_consistente', 'vintage_disponivel'],
}


def inspect(rc52):
    audit = rc52.get('methodology_audit', {})
    geo_by_factor = {}
    evidence = {}
    for factor in FACTORS:
        entry = audit.get(factor, {})
        dims = entry.get('metadata', {}).get('dimensions', {})
        geo = dims.get('geo', {})
        codes = geo.get('codes', []) if geo.get('size') == 1 else []
        geo_by_factor[factor] = codes[0] if len(codes) == 1 else None
        observed = {
            'period_aligned': entry.get('period_aligned') is True,
            'eurostat_filters_verified': entry.get('source_filters_verified') is True,
            'methodology_fully_verified': entry.get('methodology_fully_verified') is True,
            'eurostat_observation_cells': entry.get('metadata', {}).get('observation_cells'),
        }
        missing = list(REQUIRED_EVIDENCE[factor])
        # Nao inferir validacao metodologica a partir de datas ou metadados.
        evidence[factor] = {
            'observed': observed,
            'required_for_future_eligibility': REQUIRED_EVIDENCE[factor],
            'unverified': missing,
            'score_eligible': False,
            'reason': 'Evidencia de equivalencia e vintages insuficiente; falha fechada',
        }
    known = {v for v in geo_by_factor.values() if v}
    geo_consistent = len(known) == 1 and all(geo_by_factor[f] is not None for f in ('unemployment', 'activity'))
    # Inflacao e juros nao possuem geografia Eurostat auditada nesta etapa.
    audited_geos = {f: geo_by_factor[f] for f in ('unemployment', 'activity')}
    geo_consistent = bool(audited_geos['unemployment'] and audited_geos['activity'] and
                          audited_geos['unemployment'] == audited_geos['activity'])
    return {
        'model_version': VERSION,
        'asof_utc': datetime.now(timezone.utc).isoformat(),
        'asset': 'EUR/USD',
        'source_model_version': rc52.get('model_version'),
        'geography': {
            'audited_factors': audited_geos,
            'consistent_among_audited': geo_consistent,
            'audited_geo': audited_geos['unemployment'] if geo_consistent else None,
            'full_eur_pipeline_geo_verified': False,
            'reason': ('EA21 confirmado apenas nas consultas RC5.2 de desemprego e PIB; '
                       'nao foi demonstrada a mesma geografia nas fontes RC3 de inflacao, juros e atividade.'),
        },
        'evidence_registry': evidence,
        'source_quality': {
            'unemployment': {'filters_verified': audit.get('unemployment', {}).get('source_filters_verified') is True,
                             'observation_cells': audit.get('unemployment', {}).get('metadata', {}).get('observation_cells')},
            'activity': {'filters_verified': audit.get('activity', {}).get('source_filters_verified') is True,
                         'observation_cells': audit.get('activity', {}).get('metadata', {}).get('observation_cells')},
        },
        'eligible_factors': {factor: False for factor in FACTORS},
        'eligible_count': 0,
        'coverage': 0.0,
        'relative_score': None,
        'horizons': {'1d': {'score': None}, '5d': {'score': None}},
        'signals_generated': False,
        'database_writes': False,
        'status': 'Auditoria geografia/evidencias; sem score nem sinais',
        'next_actions': [
            'Confirmar geografia e valor observado em todas as fontes Eurostat usadas pelo RC3',
            'Documentar definicoes comparaveis EUA/Europa e periodos de referencia',
            'Obter dados com data de publicacao e vintages antes de estudar surpresas e backtest',
        ],
    }


def main():
    from atlas_eur_rc52 import main as rc52_main
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc52_main()
    result = inspect(json.loads(buf.getvalue()))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
