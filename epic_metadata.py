"""Epic public metadata enrichment, with optional read-only Heroic cache reuse.

Identity is based on Epic namespaces and supplied/mapped slugs, never title searches.
Heroic's source is a protocol reference; no Heroic launcher code is bundled.
"""
import json
import os
import re
from pathlib import Path
from urllib.parse import quote
from connectors import request, FetchError, MetadataUnavailable, Cancelled
from core import words

GRAPHQL='https://launcher.store.epicgames.com/graphql'
EPIC_HEADERS={'User-Agent':'Mozilla/5.0 EpicGamesLauncher'}
ENRICHMENT_VERSION=1


def namespace_of(row):
    raw=row.get('raw') or {}
    return (raw.get('metadata') or {}).get('namespace') or raw.get('namespace')


def cache_roots(options):
    explicit=options.get('epic_heroic_root','').strip()
    if explicit:
        return [Path(explicit).expanduser()]
    config=Path(os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config')))
    return [config/'heroic',Path.home()/'.var/app/com.heroicgameslauncher.hgl/config/heroic']


def load_heroic_cache(options):
    result={}; warnings=[]
    for root in cache_roots(options):
        path=root/'store_cache/legendary_gameinfo.json'
        if not path.is_file(): continue
        try:
            # This one metadata cache is the only Heroic file read here.
            if path.stat().st_size>50*1024*1024:
                warnings.append('Heroic metadata cache exceeds 50 MiB; skipped'); continue
            data=json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(data,dict): raise ValueError()
            # Current Heroic CacheStore uses namespace -> ExtraInfo, plus __timestamp.
            for namespace,value in data.items():
                if namespace.startswith('__') or not isinstance(value,dict): continue
                if value.get('about') or value.get('reqs') or value.get('releaseDate'):
                    result.setdefault(namespace,{'data':value,'cache_file':str(path)})
        except (OSError,ValueError):
            warnings.append('Heroic metadata cache could not be read; direct Epic queries will still run')
    return result,warnings


def slug_value(value):
    if not isinstance(value,str): return None
    value=value.strip().strip('/')
    # Product content slugs may contain an optional /home suffix. No arbitrary URLs.
    if value.endswith('/home'): value=value[:-5]
    return value if re.fullmatch(r'[A-Za-z0-9_-]+',value or '') else None


def graphql(query,variables):
    data=request(GRAPHQL,headers=EPIC_HEADERS,body={'query':query,'variables':variables})
    if data.get('errors'):
        raise FetchError('Epic GraphQL query rejected (schema or access error)',category='http')
    if not isinstance(data.get('data'),dict):
        raise FetchError('Epic GraphQL returned no data',category='temporary')
    return data['data']


def mapped_slug(namespace):
    response=graphql('''query MagikMapping($ns:String!) {
        Catalog { catalogNs(namespace:$ns) { mappings(pageType:"productHome") { pageSlug pageType } } }
    }''',{'ns':namespace})
    node=(response.get('Catalog') or {}).get('catalogNs') or {}
    for mapping in node.get('mappings') or []:
        if mapping.get('pageType')=='productHome':
            slug=slug_value(mapping.get('pageSlug'))
            if slug: return slug
    return None


def product_page(data,namespace):
    if not isinstance(data,dict): return None
    # Product response must declare the expected namespace. Never merge a title guess.
    for page in data.get('pages') or []:
        if page.get('type')!='productHome': continue
        actual=page.get('namespace') or data.get('namespace')
        if actual==namespace and isinstance(page.get('data'),dict): return page['data']
    return None


def apply_cache(row,entry):
    if not entry: return row
    row={**row,'raw':dict(row['raw'])}
    data=entry['data']; about=data.get('about') or {}
    row['raw']['heroic_extra']=data
    row['raw']['heroic_metadata_cache_file']=entry['cache_file']
    for key,value in [('description',about.get('description') or about.get('shortDescription')),
                      ('release',data.get('releaseDate')),('url',data.get('storeUrl'))]:
        if value and (not row.get(key) or (key=='description' and len(value)>len(row.get(key) or ''))): row[key]=value
    return row


def apply_page(row,page,raw,slug):
    row={**row,'raw':dict(row['raw'])}
    about=page.get('about') or {}; meta=page.get('meta') or {}; requirements=page.get('requirements') or {}
    row['raw']['epic_product_content']=raw
    # DLC use their own namespace product if available, but parent-page inheritance is avoided.
    values={
        'developers':meta.get('developer') or about.get('developerAttribution'),
        'publishers':meta.get('publisher') or about.get('publisherAttribution'),
        'genres':meta.get('tags') or meta.get('genres'),
        'release':meta.get('releaseDate'),
        'platforms':meta.get('platform') or [s.get('systemType') for s in requirements.get('systems') or [] if s.get('systemType')],
        'languages':requirements.get('languages'),
        'description':about.get('description') or about.get('shortDescription'),
        'cover':(about.get('image') or {}).get('src'),
        'url':'https://store.epicgames.com/en-US/p/'+slug,
    }
    for key,value in values.items():
        if value: row[key]=words(value) if key in ['developers','publishers','genres','platforms','languages'] else value
    return row


def fallback_details(row,namespace,slug):
    response=graphql('''query MagikDetails($ns:String!) {
      Product { sandbox(sandboxId:$ns) { configuration { ... on StoreConfiguration {
        configs { shortDescription technicalRequirements {
          windows { title minimum recommended } macos { title minimum recommended }
        } }
      } } } }
    }''',{'ns':namespace})
    sandbox=(response.get('Product') or {}).get('sandbox') or {}
    for configuration in sandbox.get('configuration') or []:
        cfg=configuration.get('configs') or {}
        if cfg.get('shortDescription') or cfg.get('technicalRequirements'):
            row={**row,'raw':dict(row['raw'])};row['raw']['epic_graphql']=response
            if cfg.get('shortDescription'):row['description']=cfg['shortDescription']
            reqs=cfg.get('technicalRequirements') or {}
            platforms=[{'windows':'Windows','macos':'Mac'}.get(k,k) for k,v in reqs.items() if v]
            if platforms:row['platforms']=words(platforms)
            if slug:row['url']='https://store.epicgames.com/en-US/p/'+slug
            return row
    return None


def epic_details(row,heroic_cache=None,cancel=None):
    namespace=namespace_of(row)
    if not namespace: raise MetadataUnavailable('Epic namespace missing from library record; refresh the Epic library first')
    # Different DLC share a parent namespace. A base-game page cannot safely describe the DLC.
    if row.get('type')=='DLC' or (row['raw'].get('metadata') or {}).get('mainGameItem'):
        raise MetadataUnavailable('Epic DLC enrichment deferred: namespace pages may describe its parent game')
    row=apply_cache(row,(heroic_cache or {}).get(namespace)); problems=[]; slug=None
    def check_cancel():
        if cancel and cancel.is_set():raise Cancelled()
    def usable_failure(exc):
        # Return preserved cached fields if the public API fails; never discard usable cache data.
        if 'heroic_extra' in row['raw']:
            row['_metadata_warning']={'message':str(exc),'category':exc.category,'status':exc.status}
            row['source']='Legendary + Heroic metadata cache (partial)'
            return row
        raise exc
    metadata=row['raw'].get('metadata') or {}
    for key in ['productSlug','urlSlug']:
        slug=slug_value(metadata.get(key))
        if slug:break
    if not slug:
        check_cancel()
        try: slug=mapped_slug(namespace)
        except FetchError as exc:
            if exc.category in ['temporary','rate_limit'] or exc.status in [401,403]:return usable_failure(exc)
            problems.append(str(exc))
    if slug:
        check_cancel()
        try:
            raw=request('https://store-content.ak.epicgames.com/api/en-US/content/products/'+quote(slug,safe=''))
            page=product_page(raw,namespace)
            if page:
                row=apply_page(row,page,raw,slug)
                row['raw']['epic_enrichment']={'version':ENRICHMENT_VERSION,'method':'product-content','namespace':namespace}
                row['source']='Legendary + Epic product-content API'
                return row
            problems.append('Epic returned no matching productHome namespace')
        except FetchError as exc:
            if exc.category in ['temporary','rate_limit'] or exc.status in [401,403]:return usable_failure(exc)
            problems.append('Product content: '+str(exc))
    check_cancel()
    try:
        enriched=fallback_details(row,namespace,slug)
        if enriched:
            enriched['raw']['epic_enrichment']={'version':ENRICHMENT_VERSION,'method':'GraphQL fallback','namespace':namespace}
            enriched['source']='Legendary + Epic GraphQL fallback'
            return enriched
    except FetchError as exc:
        if exc.category in ['temporary','rate_limit'] or exc.status in [401,403]:return usable_failure(exc)
        problems.append('GraphQL: '+str(exc))
    return usable_failure(MetadataUnavailable('; '.join(problems) or 'Epic has no extra public product details for this namespace'))
