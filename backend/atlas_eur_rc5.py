"""Atlas EUR RC5: motor de qualidade e comparabilidade, somente diagnóstico.

Executar em backend/; requer eur_score_rc4.py e suas dependências.
Não cria sinais, não calcula score relativo, não grava em banco.
"""
import contextlib
import io
import json
from datetime import datetime, timezone

from eur_score_rc4 import main as rc4_main

VERSION = 'eur-rc5-quality-gates-experimental-0.5.0'


def evaluate(rc4):
    comparisons = rc4.get('comparisons', {})
    checks = {}

    infl = comparisons.get('inflation', {})
    checks['inflation'] = {
        'available': infl.get('status') == 'descritivo',
        'same_period': bool(infl.get('eur_period') and infl.get('eur_period') == infl.get('us_period')),
        'not_stale': infl.get('us_stale') is False,
        'methodology_aligned': False,  # HICP vs CPIAUCSL: não presumir equivalência
        'reason': 'HICP e CPI têm metodologias diferentes; requer harmonização explícita',
    }
    unemp = comparisons.get('unemployment', {})
    checks['unemployment'] = {
        'available': unemp.get('status') == 'descritivo',
        'same_period': bool(unemp.get('eur_period') and unemp.get('eur_period') == unemp.get('us_period')),
        'methodology_aligned': False,  # definições não verificadas
        'reason': 'Calendários e definições de desemprego exigem validação',
    }
    rates = comparisons.get('rates', {})
    checks['rates'] = {
        'available': rates.get('status') == 'descritivo',
        'same_instrument': False,  # taxa de depósito BCE vs teto Fed
        'reason': 'Instrumentos BCE/Fed diferentes; não pontuar diferencial como equivalente',
    }
    activity = comparisons.get('activity', {})
    eu, us = activity.get('eur', {}), activity.get('us', {})
    checks['activity'] = {
        'available': activity.get('status') == 'descritivo' and isinstance(us.get('qoq_pct'), (int, float)),
        'same_quarter': bool(eu.get('period') and us.get('period') and eu['period'] ==
                             f"{us['period'][:4]}-Q{(int(us['period'][5:7])-1)//3+1}"),
        'growth_definition_verified': False,  # não supor que taxa Eurostat é q/q
        'reason': 'Confirmar taxa e sazonalidade do PIB europeu antes da comparação',
    }
    eligible = {
        'inflation': all(checks['inflation'][k] for k in ('available', 'same_period', 'not_stale', 'methodology_aligned')),
        'unemployment': all(checks['unemployment'][k] for k in ('available', 'same_period', 'methodology_aligned')),
        'rates': all(checks['rates'][k] for k in ('available', 'same_instrument')),
        'activity': all(checks['activity'][k] for k in ('available', 'same_quarter', 'growth_definition_verified')),
    }
    return {
        'model_version': VERSION,
        'asof_utc': datetime.now(timezone.utc).isoformat(),
        'asset': 'EUR/USD',
        'source_model_version': rc4.get('model_version'),
        'quality_checks': checks,
        'eligible_factors': eligible,
        'eligible_count': sum(eligible.values()),
        'total_factors': len(eligible),
        'coverage': round(sum(eligible.values()) / len(eligible), 3),
        'structural_score_rc3': rc4.get('structural_score'),
        'relative_score': None,
        'horizons': {'1d': {'score': None}, '5d': {'score': None}},
        'signals_generated': False,
        'database_writes': False,
        'status': 'Auditoria de qualidade; sem score relativo ou sinais operacionais',
        'limitations': [
            'A elegibilidade é conservadora: metodologia ainda não validada bloqueia pontuação.',
            'Não é backtest nem estimativa de confiabilidade.',
            'Sem calendário de divulgação e vintages históricas, não se infere surpresa macro.',
        ],
    }


def main():
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rc4_main()
    rc4 = json.loads(buffer.getvalue())
    print(json.dumps(evaluate(rc4), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
