"""Atlas EUR experimental: diagnóstico macro conservador, sem persistência.

Não interpreta inflação/desemprego mensais como sinais diários e não inventa
atividade econômica. O diferencial de níveis não é uma previsão de EUR/USD.
"""
import json
from datetime import date, datetime, timezone
from eur_macro_sources import collect_eur_macro
from eur_rates import collect_rate_differential


def _months_between(a, b):
    return (a.year - b.year) * 12 + a.month - b.month


def evaluate(macro, rates, today=None):
    today = today or datetime.now(timezone.utc).date()
    factors = {}
    errors = dict(macro.get('errors') or {})
    errors.update(rates.get('errors') or {})
    ecb, fed = rates.get('ecb'), rates.get('fed')
    if ecb and fed:
        ecb_day = date.fromisoformat(ecb['latest']['date'])
        fed_day = date.fromisoformat(fed['latest']['date'])
        # Séries de taxa-alvo só mudam quando há decisão; data antiga não
        # significa necessariamente taxa vencida. Exigimos coleta recente.
        def fresh_collection(item):
            stamp = item.get('collected_at_utc')
            if not stamp:
                return False
            parsed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
            return parsed.tzinfo is not None and 0 <= (datetime.now(timezone.utc)-parsed).total_seconds() <= 172800
        if fresh_collection(ecb) and fresh_collection(fed) and ecb_day <= today and fed_day <= today:
            factors['interest_rate_spread'] = {
                'status': 'descritivo', 'value_pp': round(float(ecb['latest']['value']) - float(fed['latest']['value']), 4),
                'ecb_observation': ecb_day.isoformat(), 'fed_observation': fed_day.isoformat(),
                'note': 'Taxa de depósito BCE menos teto Fed; instrumentos distintos; não é score direcional.'}
        else:
            factors['interest_rate_spread'] = {'status': 'indisponível', 'reason': 'coleta ausente, vencida ou data inválida'}
    else:
        factors['interest_rate_spread'] = {'status': 'indisponível', 'reason': 'faltam BCE ou Fed'}

    for key in ('hicp_yoy', 'unemployment'):
        series = (macro.get('indicators') or {}).get(key)
        if not series:
            factors[key] = {'status': 'indisponível', 'reason': errors.get(key, 'sem dados')}
            continue
        latest, previous = series['latest'], series['previous']
        try:
            a = date.fromisoformat(latest['date'] + '-01')
            b = date.fromisoformat(previous['date'] + '-01')
            age = _months_between(today, a)
            if not 0 <= age <= 4 or _months_between(a, b) != 1:
                raise ValueError('observações mensais vencidas ou não consecutivas')
            factors[key] = {'status': 'descritivo', 'value_pct': float(latest['value']),
                            'change_pp': round(float(latest['value']) - float(previous['value']), 3),
                            'period': latest['date'], 'note': 'Mudança mensal, não sinal diário.'}
        except (ValueError, KeyError, TypeError) as exc:
            factors[key] = {'status': 'indisponível', 'reason': str(exc)}

    factors['activity'] = {'status': 'não implementado', 'reason': 'fonte de atividade ainda não integrada'}
    available = sum(f['status'] == 'descritivo' for f in factors.values())
    return {'asset': 'EUR', 'model_version': 'eur-diagnostic-0.1', 'asof_utc': datetime.now(timezone.utc).isoformat(),
            'factors': factors, 'available_factors': available, 'total_factors': 4,
            'structural_score': None, 'horizons': {'1d': {'score': None}, '5d': {'score': None}},
            'status': 'diagnóstico experimental; pontuação suspensa até dados e metodologia suficientes',
            'errors': errors,
            'limitations': ['Não gera sinais nem grava no PostgreSQL.',
                            'Juros em nível e dados mensais não permitem inferir variação macro diária.',
                            'A atividade econômica e a validação prospectiva ainda não foram implementadas.']}


def main():
    result = evaluate(collect_eur_macro(), collect_rate_differential())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result['available_factors'] < 3:
        raise SystemExit('Falha: menos de três fatores descritivos disponíveis')


if __name__ == '__main__':
    main()
