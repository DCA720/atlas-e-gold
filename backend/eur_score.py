"""Atlas EUR RC3: pontuação estrutural experimental, sem sinais ou persistência.

Mantém o contrato de diagnóstico anterior e não produz previsões de 1d/5d.
Pesos e limites são hipóteses de modelagem, ainda não validadas.
"""
import json
from datetime import date, datetime, timezone
from eur_macro_sources import collect_eur_macro
from eur_rates import collect_rate_differential

MODEL_VERSION = 'eur-rc3-structural-experimental-0.3'
WEIGHTS = {'interest_rate_spread': 0.30, 'hicp_yoy': 0.25,
           'unemployment': 0.20, 'activity': 0.25}
MIN_COVERAGE = 0.75


def _months_between(a, b):
    return (a.year - b.year) * 12 + a.month - b.month


def _clamp(value, low=-1.0, high=1.0):
    return max(low, min(high, value))


def _collection_is_fresh(item, now):
    stamp = item.get('collected_at_utc')
    if not stamp:
        return False
    try:
        collected = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        return collected.tzinfo is not None and 0 <= (now - collected).total_seconds() <= 172800
    except (ValueError, TypeError, OverflowError):
        return False


def evaluate(macro, rates, today=None, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('now deve conter fuso horário')
    today = today or now.date()
    factors = {}
    errors = dict(macro.get('errors') or {})
    errors.update(rates.get('errors') or {})
    ecb, fed = rates.get('ecb'), rates.get('fed')
    if ecb and fed:
        try:
            ecb_day = date.fromisoformat(ecb['latest']['date'])
            fed_day = date.fromisoformat(fed['latest']['date'])
            if not (_collection_is_fresh(ecb, now) and _collection_is_fresh(fed, now)
                    and ecb_day <= today and fed_day <= today):
                raise ValueError('coleta ausente, vencida ou data inválida')
            factors['interest_rate_spread'] = {
                'status': 'descritivo',
                'value_pp': round(float(ecb['latest']['value']) - float(fed['latest']['value']), 4),
                'ecb_observation': ecb_day.isoformat(), 'fed_observation': fed_day.isoformat(),
                'note': 'Depósito BCE menos teto Fed: instrumentos distintos; proxy estrutural não validada.'}
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            factors['interest_rate_spread'] = {'status': 'indisponível', 'reason': str(exc)}
    else:
        factors['interest_rate_spread'] = {'status': 'indisponível', 'reason': 'faltam BCE ou Fed'}

    for key in ('hicp_yoy', 'unemployment'):
        series = (macro.get('indicators') or {}).get(key)
        if not series:
            factors[key] = {'status': 'indisponível', 'reason': errors.get(key, 'sem dados')}
            continue
        try:
            latest, previous = series['latest'], series['previous']
            a, b = date.fromisoformat(latest['date'] + '-01'), date.fromisoformat(previous['date'] + '-01')
            age = _months_between(today, a)
            if not 0 <= age <= 4 or _months_between(a, b) != 1:
                raise ValueError('observações mensais vencidas ou não consecutivas')
            factors[key] = {'status': 'descritivo', 'value_pct': float(latest['value']),
                            'change_pp': round(float(latest['value']) - float(previous['value']), 3),
                            'period': latest['date'], 'note': 'Mudança mensal, não sinal diário.'}
        except (ValueError, KeyError, TypeError) as exc:
            factors[key] = {'status': 'indisponível', 'reason': str(exc)}

    activity = (macro.get('indicators') or {}).get('activity')
    if activity:
        try:
            latest, previous = activity['latest'], activity['previous']
            def quarter_index(value):
                year, quarter = value.split('-Q')
                q = int(quarter)
                if q not in (1, 2, 3, 4):
                    raise ValueError('trimestre inválido')
                return int(year) * 4 + q
            last_q = quarter_index(latest['date'])
            if last_q - quarter_index(previous['date']) != 1:
                raise ValueError('trimestres não consecutivos')
            if last_q > today.year * 4 + (today.month - 1) // 3 + 1:
                raise ValueError('trimestre futuro')
            # Aceita o trimestre mais recente e até dois trimestres anteriores.
            if today.year * 4 + (today.month - 1) // 3 + 1 - last_q > 2:
                raise ValueError('PIB trimestral desatualizado')
            factors['activity'] = {'status': 'descritivo', 'value_pct': float(latest['value']),
                                   'previous_pct': float(previous['value']), 'period': latest['date'],
                                   'note': 'PIB real trimestral, não sinal diário.'}
        except (ValueError, KeyError, TypeError) as exc:
            factors['activity'] = {'status': 'indisponível', 'reason': str(exc)}
    else:
        factors['activity'] = {'status': 'indisponível', 'reason': errors.get('activity', 'sem dados')}

    # Cada contribuição é limitada a [-1, 1]. Hipóteses heurísticas, não calibradas.
    contributions = {}
    if factors['interest_rate_spread']['status'] == 'descritivo':
        contributions['interest_rate_spread'] = _clamp(factors['interest_rate_spread']['value_pp'] / 3.0)
    if factors['hicp_yoy']['status'] == 'descritivo':
        # Mudança da inflação é contexto, não direção garantida: não pontua até
        # definir resposta relativa à inflação americana e à política monetária.
        factors['hicp_yoy']['scoring_note'] = 'Descritivo: sem contribuição direcional isolada.'
    if factors['unemployment']['status'] == 'descritivo':
        contributions['unemployment'] = _clamp(-factors['unemployment']['change_pp'] / 0.5)
    if factors['activity']['status'] == 'descritivo':
        contributions['activity'] = _clamp((factors['activity']['value_pct'] - factors['activity']['previous_pct']) / 1.0)

    available = sum(f['status'] == 'descritivo' for f in factors.values())
    # Não redistribui peso de fator ausente: evita inflar score por lacunas.
    weighted = {k: round(v * WEIGHTS[k] * 100, 3) for k, v in contributions.items()}
    coverage = sum(WEIGHTS[k] for k in contributions)
    # Mesmo com 4 fatores coletados, inflação ainda não tem proxy direcional.
    # O score fica suspenso até cobertura >=75% de pesos pontuáveis.
    score = round(sum(weighted.values())) if coverage >= MIN_COVERAGE else None
    return {
        'asset': 'EUR', 'model_version': MODEL_VERSION, 'asof_utc': now.isoformat(),
        'factors': factors, 'available_factors': available, 'total_factors': len(WEIGHTS),
        'structural_score': score,
        'scoring': {'status': 'experimental' if score is not None else 'suspenso',
                    'weights': WEIGHTS, 'minimum_coverage': MIN_COVERAGE,
                    'scoring_coverage': round(coverage, 4),
                    'normalized_contributions': {k: round(v, 4) for k, v in contributions.items()},
                    'weighted_points': weighted,
                    'missing_scoring_factors': [k for k in WEIGHTS if k not in contributions],
                    'methodology': 'heurística preliminar sem calibração nem backtest'},
        'horizons': {'1d': {'score': None}, '5d': {'score': None}},
        'status': 'RC3 experimental: score estrutural sujeito a cobertura; horizontes desativados',
        'errors': errors,
        'limitations': [
            'Não gera sinais nem grava no PostgreSQL.',
            'Score estrutural não é previsão de EUR/USD ou probabilidade de acerto.',
            'Spread BCE/Fed compara instrumentos diferentes.',
            'Inflação sem interpretação relativa ao USD não recebe contribuição direcional.',
            'Horizontes 1d e 5d exigem metodologia própria e validação prospectiva.'
        ]}


def main():
    result = evaluate(collect_eur_macro(), collect_rate_differential())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result['available_factors'] < 3:
        raise SystemExit('Falha: menos de três fatores descritivos disponíveis')


if __name__ == '__main__':
    main()
