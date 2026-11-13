"""Facet normalization shared by the table and cover grid."""
import html
import re
from advanced_filters import matches as matches_advanced

UNKNOWN='(Unknown)'
FACETS=['store','type','genres','platforms','languages','installation_status','personal_tags']
PLATFORMS={'windows':'Windows','win32':'Windows','win64':'Windows','linux':'Linux','mac':'Mac','macos':'Mac','osx':'Mac','os x':'Mac'}
TYPES={'game':'Game','base_game':'Game','base game':'Game','movie':'Movie','film':'Movie','dlc':'DLC','downloadable_content':'DLC'}
LANGUAGES={'en':'English','en-us':'English','en-gb':'English','fr':'French','français':'French','francais':'French','de':'German','deutsch':'German','es':'Spanish','español':'Spanish','it':'Italian','italiano':'Italian','ja':'Japanese','日本語':'Japanese','ru':'Russian','русский':'Russian','pt':'Portuguese','português':'Portuguese','pl':'Polish','polski':'Polish','ko':'Korean','한국어':'Korean'}

def facet_tokens(row,key):
    value=row.get(key)
    if value is None or value=='':return [UNKNOWN]
    text=str(value)
    if key=='languages':text=re.split(r'<br\s*/?>',text,flags=re.I)[0]
    text=html.unescape(re.sub('<[^>]+>','',text)).replace('*','').strip()
    values=[text] if key in ['store','type','installation_status'] else re.split(r'[,;|\n]+',text)
    mapping={'platforms':PLATFORMS,'type':TYPES,'languages':LANGUAGES}.get(key,{})
    result=[]
    for val in values:
        val=val.strip()
        if not val:continue
        val=mapping.get(val.casefold(),val)
        if val not in result:result.append(val)
    return result or [UNKNOWN]

def matches(row,filters):
    if filters.get("advanced") and not matches_advanced(row, filters["advanced"]):return False
    if filters.get("favorites") and not row.get("favorite"):return False
    if "visible_stores" in filters and row.get("store") not in filters["visible_stores"]:return False
    searchable=' '.join(str(row.get(k) or '') for k in ['title','id','genres','developers','publishers','description','personal_tags']).casefold()
    if not all(t in searchable for t in filters.get('search','').casefold().split()):return False
    for key in FACETS:
        selected=filters.get(key) or []
        if isinstance(selected,str):selected=[selected]
        if selected and not ({v.casefold() for v in selected}&{v.casefold() for v in facet_tokens(row,key)}):return False
    played=filters.get('played','All');time=row.get('playtime')
    if played=='Played' and not (time is not None and time>0):return False
    if played=='Unplayed (known)' and time!=0:return False
    if played=='Unknown playtime' and time is not None:return False
    if filters.get('current') and not row.get('active'):return False
    score=filters.get('score',0)
    if score and (row.get('score') is None or float(row['score'])<score):return False
    return True
