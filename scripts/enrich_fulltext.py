#!/usr/bin/env python3
"""Evidence-first, legal-open-access DOI backfill and field *candidates*.

Uses Europe PMC OA JATS XML, then OpenAlex best_oa_location PDF if an
optional PDF parser is available. Never circumvents passwords or paywalls.
Evidence snippets are unverified and must not overwrite reviewed facts.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'data' / 'papers.json'
USER_AGENT = 'BioCatalystIntelligence-OpenAccess-Research/1.0 (academic text mining; contact in repo README)'
MAX_BYTES = 14 * 1024 * 1024

# These rules merely locate likely evidence; they do NOT reliably map a numerical
# value to the target product and therefore are displayed as unverified snippets.
FIELD_RULES = {
    'cat_name': r'\bcatalyst\b|\bNi@|\bCoMo\b|\bNiMo\b|\bPd/C\b|\bbifunctional\b',
    'cat_active': r'\b(?:loading|wt\.?\s*%|weight percent|metal content|ICP[-– ](?:MS|OES)|active metal)\b',
    'cat_support': r'\b(?:support|supported|zeolite|Al2O3|alumina|silica|HZSM|H-beta)\b',
    'cat_synthesis': r'\b(?:synthesi[sz]ed|impregnat|preparat|calcined|calcination|reduction|hydrothermal|co.precipitation)\b',
    'cat_size': r'\b(?:particle size|nanoparticle size|TEM|HRTEM|dispersion)\b',
    'cat_bet': r'\b(?:BET|Brunauer|specific surface area|m[²2]\s*[/]?\s*g|m2\s*g.?1)\b',
    'cat_pore': r'\b(?:pore volume|pore size|pore diameter|mesoporous|nm)\b',
    'cat_site': r'\b(?:active site|acid site|Brønsted|Lewis acid|spillover|oxygen vacanc)\b',
    'cat_cycles': r'\b(?:recyclab|reusab|cycles?|regenerat|stabilit|deactivat|spent catalyst|lifetime)\b',
    'rx_reactor': r'\b(?:reactor|autoclave|fixed.bed|trickle.bed|stirred tank|batch reactor|quartz tube)\b',
    'rx_feed': r'\b(?:feedstock|biocrude|bio.oil|lignin|microalgae|pyrolysis oil|fatty acid|biomass)\b',
    'rx_catalyst': r'\b(?:catalyst loading|catalyst mass|g catalyst|catalyst dosage|catalyst.amount)\b',
    'rx_flow': r'\b(?:flow rate|space velocity|WHSV|LHSV|mL/min|sccm|cm3/min|cm³/min)\b',
    'rx_temp': r'(?:\b(?:reaction temperature|temperature|heated)\b|°C|\b\d+\s*K\b)',
    'rx_pressure': r'\b(?:pressure|MPa|bar|psi)\b',
    'rx_power': r'(?:\b(?:input power|discharge power|specific input energy|plasma power)\b|\b\d+\s*W\b|kJ/mol)',
    'rx_mode': r'\b(?:continuous|batch|fluidi[sz]ed|counter.current|dielectric.barrier|stirred)\b',
    'rx_time': r'\b(?:reaction time|residence time|\d\s?h\b|minutes|\d\s?min\b)\b',
    'out_oil': r'\b(?:oil yield|liquid yield|biocrude yield|monomer yield|carbon yield)\b',
    'out_jet': r'\b(?:jet.fuel.range|aviation.range|\bC\d+[–-]C\d+\b|selectivity|cycloalkane yield)\b',
    'out_hdo': r'\b(?:hydrodeoxygenation|oxygen removal|deoxygenation|residual oxygen|oxygen content)\b',
    'out_hdn': r'\b(?:hydrodenitrogenation|denitrogenation|nitrogen removal|nitrogen content)\b',
    'out_phys': r'\b(?:higher heating value|density|viscosity|total acid number|freezing point|flash point)\b',
    'out_hydrogen': r'\b(?:hydrogen consumption|H2 consumption|gas yield|hydrogen uptake)\b',
    'out_novel': r'\b(?:novel|synergy|interface|mechanism|DFT|in situ|in.situ|design strateg)\b',
}
SECTION_OK = re.compile(r'(?i)methods?|materials?|experiment|catalyst|characteri[sz]|results?|discuss|performance|activity|optimization|prepar|analys')
SECTION_BAD = re.compile(r'(?i)references|acknowledg|competing interest|funding|author contribution|supplementary material|bibliograph')


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def get(url, accept='application/json', max_bytes=MAX_BYTES):
    p=urllib.parse.urlsplit(url)
    if p.scheme!='https' or not p.hostname:
        raise ValueError('Only HTTPS scholarly URLs allowed')
    req=urllib.request.Request(url,headers={'User-Agent':USER_AGENT,'Accept':accept})
    with urllib.request.urlopen(req,timeout=22) as rsp:
        dat=rsp.read(max_bytes+1)
        if len(dat)>max_bytes:raise ValueError('Open-access document exceeds 14 MB limit')
        return dat


def get_json(url):
    return json.loads(get(url).decode('utf-8'))


def tidy(t):
    return re.sub(r'\s+', ' ', str(t or '')).strip()


def parse_jats(xmltext):
    """Read ONLY body sections, preserve section ancestry, not abstract/reference lists."""
    root=ET.fromstring(xmltext)
    body=root.find('.//body')
    if body is None: return []
    paras=[]
    def travel(el, headers):
        tag=el.tag.split('}')[-1]
        if tag=='sec':
            name=tidy(''.join(el.find('title').itertext())) if el.find('title') is not None else ''
            headers=headers+([name] if name else [])
        if tag in ('p','table-wrap'):
            raw=tidy(''.join(el.itertext()))
            section=' > '.join(headers) or 'Article body'
            if 45<=len(raw)<=9000 and not SECTION_BAD.search(section):
                paras.append({'section':section,'text':raw,'locator':section})
            return
        if tag not in ('ref-list','references'):
            for child in el:
                if child.tag.split('}')[-1]=='title':continue
                travel(child,headers)
    travel(body,[])
    return paras


def extract_suggestions(paragraphs, src, max_fields=18):
    """Short, traceable excerpts. No guessing conditions from bibliographies."""
    out={}
    for field,pattern in FIELD_RULES.items():
        reg=re.compile(pattern,re.I)
        choices=[]
        for entry in paragraphs:
            txt=entry['text'];m=reg.search(txt)
            if not m:continue
            section=entry.get('section') or entry.get('page') or 'Full text'
            if SECTION_BAD.search(section):continue
            # prioritize methods or results paragraphs, and numeric content
            start=max(0,m.start()-78);stop=min(len(txt),m.end()+175)
            snippet=tidy(('…' if start else '')+txt[start:stop]+('…' if stop<len(txt) else ''))
            score=3*bool(SECTION_OK.search(str(section)))+2*bool(re.search(r'\d',snippet))+1*('Methods' in str(section) or 'method' in str(section).lower())
            choices.append((score,snippet,section))
        if choices:
            choices.sort(key=lambda x:x[0],reverse=True)
            snip=choices[0]
            out[field]={'value':snip[1][:275], 'source':src, 'locator':str(snip[2])[:160],
                        'evidence_type':'auto_extracted_open_fulltext', 'reviewed':False,
                        'disclaimer':'Candidate text, not verified experimental value'}
        if len(out)>=max_fields:break
    return out


def epmc_lookup(doi):
    q=urllib.parse.urlencode({'query':'DOI:'+doi,'format':'json','resultType':'core','pageSize':3})
    data=get_json('https://www.ebi.ac.uk/europepmc/webservices/rest/search?'+q)
    for hit in (data.get('resultList') or {}).get('result') or []:
        if hit.get('doi','').lower()!=doi.lower():continue
        return hit
    return {}


def openalex_lookup(doi, key=''):
    url='https://api.openalex.org/works/'+urllib.parse.quote('https://doi.org/'+doi,safe='')
    query={'select':'id,abstract_inverted_index,best_oa_location,open_access'}
    if key:query['api_key']=key
    return get_json(url+'?'+urllib.parse.urlencode(query))


def reconstruct_abstract(index):
    if not isinstance(index,dict):return ''
    words={n:w for w,poses in index.items() for n in poses if isinstance(n,int) and n<2000}
    return tidy(' '.join(words[k] for k in sorted(words)))[:6500]


def pdf_paragraphs(pdf, source):
    try:import fitz
    except ImportError:return []
    doc=fitz.open(stream=pdf,filetype='pdf')
    output=[]
    for i in range(min(len(doc),40)):
        raw=doc[i].get_text('text')
        if i>=4 and re.search(r'(?i)^references\s*$',raw,flags=re.M):continue
        chunks=re.split(r'\n\s*\n',raw)
        for c in chunks:
            t=tidy(c)
            if 50<=len(t)<=6000 and not SECTION_BAD.match(t):
                output.append({'section':'PDF page '+str(i+1), 'text':t,'page':i+1})
    return output


def maybe_open_pdf(location):
    if not isinstance(location,dict) or location.get('is_oa') is not True:return None
    link=location.get('pdf_url') or ''
    u=urllib.parse.urlsplit(link)
    host=(u.hostname or '').lower()
    # Curated scholarly hosts only; no arbitrary SSRF or paywall crawling.
    domains=('nature.com','springer.com','springerlink.com','pmc.ncbi.nlm.nih.gov','arxiv.org',
             'rsc.org','acs.org','acs.figshare.com','wiley.com','mdpi.com','frontiersin.org',
             'science.org','plos.org','biomedcentral.com','sciencedirect.com','elsevier.com')
    if u.scheme!='https' or not any(host==d or host.endswith('.'+d) for d in domains):return None
    try:
        raw=get(link,accept='application/pdf',max_bytes=MAX_BYTES)
        if not raw.startswith(b'%PDF'):return None
        return raw,link
    except (urllib.error.URLError,OSError,ValueError,TimeoutError):return None


def enrich_one(p, allow_pdf=True):
    doi=p.get('doi','')
    if not doi:return {'status':'skipped_no_doi'}
    attempted=[]
    ep={}
    try:
        ep=epmc_lookup(doi);attempted.append('Europe PMC DOI lookup')
    except (urllib.error.URLError,OSError,ValueError,TimeoutError) as exc:
        attempted.append('Europe PMC lookup error: '+str(exc)[:90])
    if not p.get('abstract') and ep.get('abstractText'):
        # Plain text from a scholarly index, not the full article.
        p['abstract']=tidy(re.sub('<[^>]*>',' ',ep['abstractText']))[:6500]
        p['abstract_source']='Europe PMC'
    pmcid=ep.get('pmcid','')
    if pmcid and ep.get('isOpenAccess')=='Y' and ep.get('inEPMC')=='Y':
        try:
            raw=get('https://www.ebi.ac.uk/europepmc/webservices/rest/'+urllib.parse.quote(pmcid)+'/fullTextXML',accept='application/xml')
            paras=parse_jats(raw)
            if len(paras)>=5:
                url='https://europepmc.org/articles/'+pmcid
                suggestions=extract_suggestions(paras,url)
                p['fulltext_suggestions']=suggestions
                p['oa_fulltext']={'status':'automatic_candidates_waiting_review','type':'europepmc_jats_xml',
                   'url':url,'downloaded_at':utc_now(),'sections_parsed':len(paras),
                   'fields_suggested':len(suggestions),'data_scope':'open-access body only; SI not included'}
                return {'status':'xml_ok','fields':len(suggestions)}
        except (ET.ParseError,urllib.error.URLError,OSError,ValueError,TimeoutError) as exc:
            attempted.append('Europe PMC XML failure: '+str(exc)[:100])
    oa={}
    try:
        oa=openalex_lookup(doi,os.environ.get('OPENALEX_API_KEY',''))
        attempted.append('OpenAlex DOI lookup')
    except (urllib.error.URLError,OSError,ValueError,TimeoutError) as exc:
        attempted.append('OpenAlex lookup error: '+str(exc)[:90])
    if not p.get('abstract') and oa.get('abstract_inverted_index'):
        p['abstract']=reconstruct_abstract(oa['abstract_inverted_index'])
        p['abstract_source']='OpenAlex inverted abstract'
    best=oa.get('best_oa_location') or {}
    p['oa_url']=p.get('oa_url') or best.get('landing_page_url') or best.get('pdf_url') or ''
    if allow_pdf:
        found=maybe_open_pdf(best)
        if found:
            pdf,url=found
            try:
                paras=pdf_paragraphs(pdf,url)
                if paras:
                    suggestions=extract_suggestions(paras,url)
                    p['fulltext_suggestions']=suggestions
                    p['oa_fulltext']={'status':'automatic_candidates_waiting_review','type':'open_access_pdf',
                       'url':url,'downloaded_at':utc_now(),'sections_parsed':len(paras),
                       'fields_suggested':len(suggestions),'data_scope':'pdf text layer first 40 pages; scanned parts and SI excluded'}
                    return {'status':'pdf_ok','fields':len(suggestions)}
            except (OSError,RuntimeError,ValueError) as exc:attempted.append('PDF parsing failure: '+str(exc)[:80])
    p['oa_fulltext']={'status':'metadata_only_not_accessed','checked_at':utc_now(),
       'url':p.get('oa_url',''),'note':'No machine-readable open full text retrieved; paywalled sources never bypassed',
       'attempted':attempted[:5]}
    return {'status':'metadata_only','fields':0}


def run(force=False,limit=10):
    if not DB.exists():return 2
    db=json.loads(DB.read_text(encoding='utf-8'))
    papers=db.get('papers',[])
    candidates=sorted(papers,key=lambda p:(p.get('curated_added_at') or '',p.get('priority_score') or 0),reverse=True)
    cnt={'xml_ok':0,'pdf_ok':0,'metadata_only':0,'skipped_no_doi':0,'skipped_recent':0,'errors':0}
    today=dt.datetime.now(dt.timezone.utc)
    calls=0
    for p in candidates:
        if calls>=limit:break
        state=p.get('oa_fulltext') or {}
        if not force and state.get('status')=='automatic_candidates_waiting_review':
            cnt['skipped_recent']+=1;continue
        last=state.get('checked_at','')
        if not force and last:
            try:
                if (today-dt.datetime.fromisoformat(last.replace('Z','+00:00'))).days<14:
                    cnt['skipped_recent']+=1;continue
            except ValueError:pass
        calls+=1
        try:out=enrich_one(p)
        except Exception as exc:
            cnt['errors']+=1
            p['oa_fulltext']={'status':'retrieval_error','checked_at':utc_now(),'note':str(exc)[:180]}
            continue
        cnt[out['status']]=cnt.get(out['status'],0)+1
    db['fulltext_last_attempt']=utc_now()
    db['fulltext_batch_stats']=cnt
    # Atomic replace so a network exception never destroys the user's data.
    tmp=DB.with_suffix('.fulltext.tmp')
    tmp.write_text(json.dumps(db,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    tmp.replace(DB)
    print('Full-text research pass:',json.dumps(cnt,ensure_ascii=False))
    return 0


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--force',action='store_true')
    ap.add_argument('--limit',type=int,default=10)
    args=ap.parse_args()
    sys.exit(run(args.force,max(1,min(args.limit,15))))