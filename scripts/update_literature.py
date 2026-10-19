#!/usr/bin/env python3
"""Daily OpenAlex/Crossref literature metadata harvester. Standard library only.

Not a full-text scraper, and never guesses experimental yields or catalysts.
"""
import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data'/'papers.json'
TOPICS=ROOT/'config'/'topics.json'
USER_AGENT='BioCatalystIntelligence/2.0 (academic literature monitoring)' + (' mailto:'+os.environ['CONTACT_EMAIL'] if os.environ.get('CONTACT_EMAIL') else '')


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')


def fetch_json(url, params, tries=3, timeout=24):
    url += '?' + urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={'User-Agent':USER_AGENT,'Accept':'application/json'})
    for i in range(tries):
        try:
            with urllib.request.urlopen(req,timeout=timeout) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            if i==tries-1: raise RuntimeError(str(exc)) from exc
            time.sleep(min(2**i,5))


def normalize_doi(v):
    v=(v or '').strip().lower()
    v=re.sub(r'^https?://(dx\.)?doi\.org/', '', v)
    v=re.sub(r'^doi:\s*','',v)
    return v.strip(' /.,;')


def clean_text(s):
    return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>', ' ',str(s or '')))).strip()


def text_abstract(inv):
    if not isinstance(inv,dict): return ''
    positions=[]
    for word, ids in inv.items():
        for idx in ids:
            if isinstance(idx,int) and idx < 3000:
                positions.append((idx,word))
    return ' '.join(word for _,word in sorted(positions))[:4200]

FEEDSTOCKS=[('微藻',r'microalga|microalgae|algal|algae|chlorella|spirulina|cyanobacteria'),('HTL 生物原油',r'biocrude|hydrothermal liquefaction|\bhtl\b'),('热解生物油',r'pyrolysis oil|pyrolytic oil|fast pyrolysis'),('木质素',r'lignin|guaiacol|syringol|phenolic'),('植物油/脂肪酸',r'fatty acid|vegetable oil|lipid|triglyceride|hydroprocessed ester'),('生物质衍生物',r'biomass-derived|biomass conversion|bio-oil|bio oil|biofuel')]
REACTIONS=[('HDN',r'hydrodenitrogenation|denitrogenation|nitrogen removal'),('HDO',r'hydrodeoxygenation|deoxygenation|\bhdo\b'),('加氢裂化',r'hydrocracking|hydrocrack'),('异构化',r'hydroisomeriz|isomeriz'),('脱羧/脱羰',r'decarboxylat|decarbonylat|kolbe'),('C-C 偶联',r'c.?c coupling|oligomeriz|alkylation|carbon.chain'),('催化裂化',r'catalytic cracking|zeolite'),('重整',r'reforming|syngas'),('加氢',r'hydrogenation|hydrotreatment|hydroprocess')]
MATERIALS=[('Ni',r'\bni\b|nickel'),('Co',r'\bco\b|cobalt'),('Mn',r'\bmn\b|manganese'),('Mo',r'\bmo\b|molybdenum'),('Pt',r'\bpt\b|platinum'),('Pd',r'\bpd\b|palladium'),('Ru',r'\bru\b|ruthenium'),('Rh',r'\brh\b|rhodium'),('Ir',r'\biridium|\bir/'),('Cu',r'\bcu\b|copper'),('分子筛',r'zeolite|zsm.?5|\bsapo\b|\bbeta\b'),('磷化物',r'phosphide'),('高熵',r'high.entropy')]

def detect(title, abstract, assigned=''):
    content=(title+' '+abstract).lower()
    directions=[]
    for name,pattern in [('低温等离子体',r'plasma|dielectric barrier discharge|\bdbd\b'),('电催化',r'electrocataly|electrochemic|electrohydrogenat|kolbe electro'),('光催化',r'photocataly|photo.?driven|photothermal|photoelectrocataly'),('热催化',r'hydrodeoxygen|hydrodenitrogen|hydrocrack|hydrotreat|thermocataly|catalytic cracking|hydroprocess')]:
        if re.search(pattern,content): directions.append(name)
    if not directions and assigned: directions=[assigned]
    feedstocks=[name for name,p in FEEDSTOCKS if re.search(p,content)]
    reactions=[name for name,p in REACTIONS if re.search(p,content)]
    materials=[name for name,p in MATERIALS if re.search(p,title+' '+abstract,re.I)]
    # Curated relevance: both biomass/fuel substrate and upgrading chemistry present.
    has_substrate=bool(re.search(r'bio.?oil|biocrude|biomass|lignin|alga|bio.?jet|jet fuel|sustainable aviation|renewable fuel|hydrothermal liquefaction|guaiacol|fatty acids?',content))
    has_process=bool(re.search(r'cataly|hydro.?deoxy|hydro.?denitro|hydrotreat|hydrocrack|upgrad|jet fuel|biojet|photocataly|electrocataly|plasma|hydrogenation|isomeriz|pyrolysis oil',content))
    score=int(has_substrate)*3+int(has_process)*3+int('jet fuel' in content or 'aviation' in content)*2+int('biocrude' in content or 'bio-oil' in content)*2+int('catalyst' in content or 'catalytic' in content)
    return dict(directions=directions,feedstocks=feedstocks,reactions=reactions,materials=materials,relevance=score,accepted=has_substrate and has_process)


def common_record(title,abstract,doi,authors,journal,date,source,ref_url,assigned,kind='',cited_by=None,oa_url=''):
    title=clean_text(title)
    if not title:return None
    abstract=clean_text(abstract)
    doi=normalize_doi(doi)
    info=detect(title,abstract,assigned)
    if not info['accepted']:return None
    date=(date or '')[:10]
    if date and not re.fullmatch(r'\d{4}(-\d{2}(-\d{2})?)?',date):date=''
    return {'id':'doi:'+doi if doi else 'title:'+re.sub(r'[^a-z0-9]','',title.lower())[:100],
      'title':title,'abstract':abstract,'doi':doi,'url':('https://doi.org/'+doi) if doi else ref_url,
      'authors':authors[:10], 'journal':journal,'date':date,'year':int(date[:4]) if len(date)>=4 else None,
      'kind':kind, 'sources':[source], 'directions':info['directions'],'feedstocks':info['feedstocks'],
      'reactions':info['reactions'],'materials':info['materials'],'relevance':info['relevance'],
      'cited_by':cited_by,'oa_url':oa_url or '', 'evidence_status':'元数据/摘要，实验性能待全文核验',
      'first_seen_at':utc_now(),'last_seen_at':utc_now(),'topics':[], 'curated':False}


def openalex(query,from_date,n,key=''):
    p={'search':query,'filter':'from_publication_date:'+from_date+',type:article|review',
       'per_page':str(n),'sort':'publication_date:desc',
       'select':'id,doi,display_name,publication_date,authorships,primary_location,type,cited_by_count,abstract_inverted_index,open_access'}
    if key:p['api_key']=key
    data=fetch_json('https://api.openalex.org/works',p)
    for v in data.get('results',[]):
        location=v.get('primary_location') or {}
        journal=((location.get('source') or {}).get('display_name') or '')
        authors=[((a.get('author') or {}).get('display_name') or '') for a in (v.get('authorships') or [])]
        oa=v.get('open_access') or {}
        record=common_record(v.get('display_name'),text_abstract(v.get('abstract_inverted_index')),
          v.get('doi'),authors,journal,v.get('publication_date'),'OpenAlex',v.get('id',''),'',v.get('type',''),v.get('cited_by_count'),oa.get('oa_url') or '')
        if record:yield record


def crossref(query,from_date,n):
    p={'query.title':query,'filter':'from-pub-date:'+from_date+',type:journal-article',
       'rows':str(n),'sort':'published','order':'desc',
       'select':'DOI,title,author,container-title,published,published-online,abstract,type,URL'}
    if os.environ.get('CONTACT_EMAIL'):p['mailto']=os.environ['CONTACT_EMAIL']
    data=fetch_json('https://api.crossref.org/works',p)
    for v in (data.get('message') or {}).get('items',[]):
        date_parts=((v.get('published-online') or v.get('published') or {}).get('date-parts') or [[]])[0]
        date='-'.join(str(x).zfill(2) if i else str(x) for i,x in enumerate(date_parts))
        authors=[' '.join(x for x in (a.get('given',''),a.get('family','')) if x) for a in v.get('author',[])]
        title=(v.get('title') or [''])[0]
        journal=(v.get('container-title') or [''])[0]
        record=common_record(title,v.get('abstract',''),v.get('DOI'),authors,journal,date,'Crossref',v.get('URL',''),'',v.get('type',''))
        if record: yield record


def merge(prev,new):
    old=dict(prev)
    for field in ('sources','topics','directions','feedstocks','reactions','materials'):
        old[field]=list(dict.fromkeys((prev.get(field) or [])+(new.get(field) or [])))
    for field in ('abstract','journal','authors','oa_url','doi','url','date','year','kind'):
        if not old.get(field) and new.get(field):old[field]=new[field]
    if len(new.get('abstract',''))>len(old.get('abstract','')):old['abstract']=new['abstract']
    if new.get('cited_by') is not None:old['cited_by']=max(old.get('cited_by') or 0,new['cited_by'])
    old['relevance']=max(prev.get('relevance',0),new.get('relevance',0))
    old['last_seen_at']=new['last_seen_at']
    return old


def run(max_topics=None):
    cfg=json.loads(TOPICS.read_text(encoding='utf-8'))
    raw=json.loads(DB.read_text(encoding='utf-8')) if DB.exists() else {'papers':[]}
    prev={p['id']:p for p in raw.get('papers',[])}
    now=dt.datetime.now(dt.timezone.utc)
    last=raw.get('last_success','')
    days=cfg['daily_lookback_days'] if last else cfg['first_run_lookback_days']
    from_date=(now-dt.timedelta(days=days)).date().isoformat()
    topics=cfg['topics'][:max_topics] if max_topics else cfg['topics']
    n=cfg.get('max_per_topic_per_source',30)
    key=os.environ.get('OPENALEX_API_KEY','')
    successes=[];errors=[];new_cnt=0;hits=0
    for topic in topics:
        for name,fn in [('OpenAlex',lambda:openalex(topic['query'],from_date,n,key)),('Crossref',lambda:crossref(topic['query'],from_date,n))]:
            try:
                batch=list(fn())
                successes.append(name)
                for p in batch:
                    hits+=1
                    p['topics']=[topic['id']]
                    if not p['directions']:p['directions']=[topic['direction']]
                    if p['id'] not in prev:
                        new_cnt+=1
                        prev[p['id']]=p
                    else:prev[p['id']]=merge(prev[p['id']],p)
            except Exception as exc:
                errors.append('{} / {}: {}'.format(name,topic['id'],str(exc)[:160]))
            time.sleep(0.12)
    if not successes:
        print('All API sources failed; preserving last successful snapshot.',file=sys.stderr)
        for err in errors:print(err,file=sys.stderr)
        return 2
    papers=sorted(prev.values(),key=lambda p:((p.get('date') or '0000'),(p.get('first_seen_at') or '')),reverse=True)
    papers=papers[:cfg['max_stored_papers']]
    raw.update({'schema_version':2,'last_attempt':utc_now(),'last_success':utc_now(),
                'source_status':'success' if not errors else 'partial',
                'success_sources':sorted(set(successes)), 'errors':errors[:30],
                'query_window_start':from_date,'new_added_count':new_cnt,'hits_processed':hits,'papers':papers})
    DB.parent.mkdir(exist_ok=True,parents=True)
    tmp=DB.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(raw,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    tmp.replace(DB)
    print('OK: stored={}, new={}, hits={}, queries_success={}, errors={}'.format(len(papers),new_cnt,hits,len(successes),len(errors)))
    return 0

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--max-topics',type=int,default=None,help='For a quick connectivity test')
    args=ap.parse_args()
    sys.exit(run(args.max_topics))