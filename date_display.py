"""Human-readable UI dates. Storage, source payloads and exports remain canonical."""
import math
import re
from datetime import datetime,timezone
MONTHS=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
DATE_FIELDS={'release','last_played','updated','date_added','mc_release','mc_checked'}
DATE_FIELDS |= {source+'_checked' for source in ('igdb','protondb','steamgriddb','opencritic')}
REPORT_FIELDS=DATE_FIELDS|{'time','retry_after','expires_at','timestamp','grantDate','acquisitionDate','purchaseDate','datePurchased','createdAt','claimedAt','grantedAt','date'}

def parse_date(value):
    if value is None or value=='' or isinstance(value,bool):return None
    try:
        if isinstance(value,str):
            text=value.strip()
            if re.fullmatch(r'\d{4}',text):return datetime(int(text),1,1),'year'
            if re.fullmatch(r'\d{4}-\d{2}',text):return datetime.strptime(text,'%Y-%m'),'month'
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}',text):return datetime.strptime(text,'%Y-%m-%d'),'day'
            if not re.fullmatch(r'\d+(?:\.\d+)?',text):
                try:return datetime.fromisoformat(text.replace('Z','+00:00')),'datetime'
                except ValueError:pass
                # Store release dates can already be human-readable, with partial precision.
                for fmt,precision in [('%d %b, %Y','day'),('%b %d, %Y','day'),('%d %B, %Y','day'),('%B %d, %Y','day'),('%d %b %Y','day'),('%b %Y','month'),('%B %Y','month')]:
                    try:return datetime.strptime(text,fmt),precision
                    except ValueError:pass
                return None
            value=float(text)
        if isinstance(value,(int,float)):
            if not math.isfinite(value) or value<=0:return None
            if value>100000000000:value/=1000
            return datetime.fromtimestamp(value,timezone.utc),'datetime'
    except (ValueError,TypeError,OverflowError,OSError):return None
    return None

def friendly_date(value,unknown='—'):
    parsed=parse_date(value)
    if not parsed:return unknown if value is None or value=='' or value==0 else str(value)
    date,precision=parsed
    if precision=='datetime':date=date.astimezone() # Honors system timezone and DST.
    if precision=='year':return str(date.year)
    month=MONTHS[date.month-1]
    if precision=='month':return f'{month} {date.year}'
    text=f'{date.day} {month} {date.year}'
    if precision=='datetime':text+=f', {date.hour:02}:{date.minute:02}:{date.second:02}'
    return text

def date_sort_key(value):
    parsed=parse_date(value)
    if not parsed:return None
    date,precision=parsed
    if precision!='datetime':date=date.replace(tzinfo=timezone.utc)
    return date.timestamp()

def friendly_report(value,key=None):
    if isinstance(value,dict):return {k:friendly_report(v,k) for k,v in value.items()}
    if isinstance(value,list):return [friendly_report(v,key) for v in value]
    if key in REPORT_FIELDS and parse_date(value):return friendly_date(value)
    return value
