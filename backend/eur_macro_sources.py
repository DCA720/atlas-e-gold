        value = values.get(str(flat_index)) if isinstance(values, dict) else (values[flat_index] if flat_index < len(values) else None)
        if value is None:
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            rows.append({'date': date, 'value': value})
    rows.sort(key=lambda x: x['date'], reverse=True)
    if len(rows) < 2:
        raise ValueError('Menos de duas observações válidas')
    return rows[:36]


def collect_eurostat(name, timeout=25):
    spec = SERIES[name]
    params = {**spec['filters'], 'lang': 'EN', 'lastTimePeriod': 36}
    url = BASE + spec['dataset'] + '?' + urllib.parse.urlencode(params)
    data = _get_json(url, timeout=timeout)
    rows = _extract_series(data)
    return {
        'indicator': name, 'asset': 'EUR', 'source': 'Eurostat',
        'dataset': spec['dataset'], 'filters': spec['filters'],
        'description': spec['description'], 'unit': spec['unit'],
        'collected_at_utc': datetime.now(timezone.utc).isoformat(),
        'latest': rows[0], 'previous': rows[1], 'recent': rows,
        'score': None, 'status': 'observações coletadas; sem pontuação direcional',
        'note': 'Data de referência estatística não é horário de divulgação; dados sujeitos a revisões.'
    }


def collect_eur_macro(timeout=25):
    result = {'asset': 'EUR', 'collected_at_utc': datetime.now(timezone.utc).isoformat(),
              'indicators': {}, 'errors': {}, 'score': None,
              'status': 'coleta experimental; sem viés macro calculado'}
    for name in SERIES:
        try:
            result['indicators'][name] = collect_eurostat(name, timeout)
        except (KeyError, ValueError, TypeError, OSError, TimeoutError, json.JSONDecodeError) as exc:
            result['errors'][name] = f'{type(exc).__name__}: {str(exc)[:200]}'
        except Exception as exc:
            # Falha isolada por indicador, sem impedir o diagnóstico do restante.
            result['errors'][name] = f'{type(exc).__name__}: {str(exc)[:200]}'
    return result


if __name__ == '__main__':
    print(json.dumps(collect_eur_macro(), ensure_ascii=False, indent=2))
