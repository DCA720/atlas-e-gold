#!/usr/bin/env python3
"""Atlas EUR RC7.8: conservative event/document linkage and headline disambiguation.
Read-only. Consumes RC7.7; does not fetch documents or authenticate release times.
"""
import argparse
import datetime as dt
import json
import re
from pathlib import Path

VERSION='eur-rc7.8-event-document-linkage-0.7.8'
FACTORS=('inflation','rates','unemployment','activity')
BLS_URL='https://www.bls.gov/news.release/archives/empsit_12162025.htm'
EU_EVENTS={
 'https://ec.europa.eu/eurostat/web/products-euro-indicators/w/2-02102026-ap':('2026-09','flash','2026-10-02'),
 'https://ec.europa.eu/eurostat/en/web/products-euro-indicators/w/2-16102026-ap':('2026-09','full','2026-10-16'),
 'https://ec.europa.eu/eurostat/en/web/products-euro-indicators/w/2-04112026-ap':('2026-10','flash','2026-11-04'),
}

def classify_candidate(factor,label,c):
    value=str(c.get('matched_text','')).strip()
    ctx=' '.join(str(c.get('context','')).split())
    s=ctx.lower(); v=value.lower()
    kind=c.get('kind')
    previous=c.get('classification','')
    category=previous or 'unlinked_candidate'
    reason='Previous classification retained; no event-specific evidence established.'
    headline_period=None
    if factor=='unemployment' and kind=='percent_candidate':
        if re.search(r'\b(confidence level|confidence interval|statistically significant|overlap|response rate|participation rate|employment.population|teenagers|adult men|adult women|whites|blacks|asians|hispanics|long.term)\b',s):
            category='secondary_or_methodology_statistic';reason='Subgroup, survey or methodological percentage, not total unemployment.'
        elif re.search(r'\b(?:last november|prior november|year earlier)\b',s):
            category='historical_comparison_not_headline';reason='Comparison with another period.'
        elif re.search(r'\bin november\b[^.]{0,100}\bunemployment rate,?\s+at\s+'+re.escape(v),s) or re.search(r'\bin november[^.]{0,100}\bunemployment rate[^.]{0,30}'+re.escape(v),s):
            category='total_unemployment_headline_candidate';reason='Explicit November total unemployment rate in archived BLS release.';headline_period='2025-11'
        else:
            category='unlinked_percentage';reason='Cannot prove total rate, reference period and headline association.'
    elif factor=='unemployment' and kind=='time_candidate':
        if 'embargoed until' in s:category='embargo_time_not_actual_publication';reason='Embargo is not proof of actual dissemination.'
        elif 'scheduled to be released' in s:category='future_schedule_not_current_release';reason='Next release schedule, not current event.'
    elif factor=='unemployment' and kind=='date_candidate':
        if 'last modified' in s:category='page_modified_not_release';reason='Website modification date.'
        elif 'embargoed until' in s:category='embargo_date_candidate';reason='Release header date candidate, not independently authenticated publication.'
    elif factor=='rates' and previous=='fomc_minutes_release':
        category='minutes_not_policy_decision';reason='FOMC minutes date must not be used as policy decision announcement.'
    elif factor=='inflation' and previous=='geographic_methodology_context':
        category='geographic_context_not_release';reason='Euro-area membership date, not publication.'
    elif factor=='activity' and previous=='scheduled_g17_release_time':
        category='scheduled_time_not_actual_publication';reason='General schedule, not event-specific dissemination.'
    return {'kind':kind,'matched_text':value,'context':ctx,'previous_classification':previous,
            'classification':category,'rationale':reason,'headline_reference_period_candidate':headline_period,
            'actual_publication_timestamp_verified':False,'first_release_value_verified':False,
            'point_in_time_usable':False}

def audit(src):
    if not isinstance(src,dict) or not str(src.get('model_version','')).startswith('eur-rc7.7-') or src.get('asset')!='EUR/USD' or src.get('input_valid') is not True:
        raise ValueError('Invalid RC7.7 input')
    if src.get('eligible_count')!=0 or src.get('coverage')!=0.0 or src.get('relative_score') is not None or src.get('verified_point_in_time_events')!=0:
        raise ValueError('Unsafe RC7.7 scoring state')
    if any(src.get(k) for k in ('point_in_time_backtest_authorized','signals_generated','database_writes','production_change_authorized')):
        raise ValueError('Unsafe RC7.7 actions')
    docs=src.get('documents');events=src.get('publication_events')
    if not isinstance(docs,list) or len(docs)!=10 or not isinstance(events,list) or len(events)!=6:
        raise ValueError('Incomplete RC7.7 audit')
    if any(d.get('factor') not in FACTORS or d.get('point_in_time_usable') or d.get('event_specific_document_verified') for d in docs):
        raise ValueError('Invalid source document flags')
    if any(e.get('point_in_time_usable') or e.get('available_asof_utc') is not None for e in events):
        raise ValueError('Unsafe publication event')
    registry=[];outdocs=[];counts={};false_positives=0
    for d in docs:
        url=d.get('source_url');factor=d['factor'];label=d.get('label','')
        evidence=[classify_candidate(factor,label,c) for c in d.get('evidence',[])]
        for c in evidence:
            k=c['classification'];counts[k]=counts.get(k,0)+1
            if c['previous_classification']=='unemployment_headline_candidate' and k!='total_unemployment_headline_candidate':false_positives+=1
        linkage='discovery_only';event_id=None;period=None;kind=None;release_date=None
        if factor=='inflation' and url in EU_EVENTS:
            period,kind,release_date=EU_EVENTS[url];event_id=f'EU_HICP_{period}_{kind.upper()}';linkage='event_specific_url_candidate'
        elif factor=='unemployment' and url==BLS_URL:
            period='2025-11';kind='employment_situation';release_date='2025-12-16';event_id='US_UNRATE_2025-11_BLS';linkage='event_specific_archived_release_candidate'
        outdocs.append({'factor':factor,'label':label,'source_url':url,'sha256_at_retrieval':d.get('retrieved_sha256'),
                        'retrieval_status':d.get('retrieval_status'),'linkage_classification':linkage,
                        'evidence':evidence,'point_in_time_usable':False})
        if event_id:
            headline=[c for c in evidence if c['classification']=='total_unemployment_headline_candidate' and c['headline_reference_period_candidate']==period]
            values=sorted(set(c['matched_text'] for c in headline))
            registry.append({'event_id':event_id,'factor':factor,'reference_period':period,'release_kind':kind,
                             'release_date_candidate':release_date,'source_url':url,'document_sha256_at_retrieval':d.get('retrieved_sha256'),
                             'linkage_classification':linkage,'headline_value_candidates':values,
                             'headline_contexts':[{'value':c['matched_text'],'excerpt':c['context']} for c in headline],
                             'document_event_link_verified':False,'release_timestamp_utc':None,
                             'release_timestamp_verified':False,'first_release_value':None,
                             'first_release_value_verified':False,'available_asof_utc':None,'point_in_time_usable':False,
                             'blockers':['Source identity and original vintage not independently authenticated',
                                         'Actual publication timestamp not verified',
                                         'No first-release dataset vintage verified']})
    if len(registry)!=4:raise ValueError('Expected 3 Eurostat and 1 BLS candidate event')
    return {'model_version':VERSION,'asof_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
            'asset':'EUR/USD','module':'event_document_linkage','input_model_version':src['model_version'],
            'input_valid':True,'documents_reviewed':len(docs),'candidates_reviewed':sum(len(d['evidence']) for d in outdocs),
            'classification_counts':dict(sorted(counts.items())),'previous_headline_false_positives_reclassified':false_positives,
            'event_registry_candidates':registry,'event_registry_candidate_count':len(registry),
            'documents':outdocs,'publication_events':[{**e,'release_timestamp_utc':None,'release_timestamp_verified':False,
                'first_release_value':None,'first_release_value_verified':False,'available_asof_utc':None,'point_in_time_usable':False} for e in events],
            'verified_point_in_time_events':0,'historical_first_release_vintages_verified':False,
            'historical_release_timestamps_verified':False,'point_in_time_integrity_verified':False,
            'eligibility':{f:False for f in FACTORS},'eligible_count':0,'coverage':0.0,'relative_score':None,
            'horizons':{'1d':{'score':None},'5d':{'score':None}},'point_in_time_backtest_authorized':False,
            'signals_generated':False,'database_writes':False,'production_change_authorized':False,'source_code_modified':False,
            'next_step':'Retrieve individual ECB/FOMC/Eurostat releases; independently verify first-release values and publication timestamps.',
            'limitations':['URL-to-event linkage is a candidate association, not independent authentication.',
                           'RC7.8 uses only RC7.7 excerpts and metadata; no new live document retrieval.',
                           'Headline text candidate is not a verified full dataset first-release vintage.',
                           'Embargo or scheduled time is not independently proven actual dissemination.',
                           'No scores, signals, backtests or production writes.']}

def self_test():
    def cl(t,ctx):return classify_candidate('unemployment','BLS',{'kind':'percent_candidate','matched_text':t,'context':ctx,'classification':'unemployment_headline_candidate'})['classification']
    assert cl('90 percent','statistically significant at a 90 percent confidence level')=='secondary_or_methodology_statistic'
    assert cl('16.3 percent','The unemployment rate for teenagers was 16.3 percent in November')=='secondary_or_methodology_statistic'
    assert cl('4.6 percent','In November, the unemployment rate, at 4.6 percent, was little changed')=='total_unemployment_headline_candidate'
    assert cl('4.2 percent','These measures are higher than last November, when the jobless rate was 4.2 percent')!='total_unemployment_headline_candidate'
    assert cl('4.1 percent','The jobless rates for adult men (4.1 percent)')!='total_unemployment_headline_candidate'
    print('RC78_SELF_TEST_OK')

def main():
    p=argparse.ArgumentParser();p.add_argument('--input',default='eur_rc77_result.json');p.add_argument('--output',default='eur_rc78_result.json');p.add_argument('--self-test',action='store_true');a=p.parse_args()
    if a.self_test:self_test();return
    r=audit(json.loads(Path(a.input).read_text(encoding='utf-8')))
    Path(a.output).write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('RC78_OK',r['documents_reviewed'],r['candidates_reviewed'],r['event_registry_candidate_count'],r['previous_headline_false_positives_reclassified'])
if __name__=='__main__':main()
