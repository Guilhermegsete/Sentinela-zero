import json, urllib.request, datetime, pathlib, xml.etree.ElementTree as ET
OUT=pathlib.Path(__file__).resolve().parents[1]/'docs'/'data.json'
feeds={'regions':'https://services.swpc.noaa.gov/json/solar_regions.json','kp':'https://services.swpc.noaa.gov/json/planetary_k_index_1m.json','flares':'https://services.swpc.noaa.gov/json/goes/primary/xray-flares-latest.json','alerts':'https://services.swpc.noaa.gov/products/alerts.json'}
news={'BBC World':'https://feeds.bbci.co.uk/news/world/rss.xml','Al Jazeera':'https://www.aljazeera.com/xml/rss/all.xml'}
now=datetime.datetime.now(datetime.timezone.utc).isoformat()
previous={}
if OUT.exists():
 try: previous=json.loads(OUT.read_text())
 except (ValueError,OSError): pass
result={'generated_at':now,'solar':{},'news':{},'status':{}}
def fetch(url):
 req=urllib.request.Request(url,headers={'User-Agent':'SentinelaZeroPilot/0.1 (public data research)'})
 with urllib.request.urlopen(req,timeout=20) as r: return r.read()
for name,url in feeds.items():
 try:
  data=json.loads(fetch(url))
  if not isinstance(data,list): raise ValueError('Expected JSON list')
  if name=='regions':
   rows=[v for v in data if isinstance(v,dict) and v.get('observed_date')]
   if not rows: raise ValueError('Missing observed_date')
   latest=max(v['observed_date'] for v in rows)
   data=[v for v in rows if v['observed_date']==latest]
   observed=latest+'T00:00:00+00:00'
   limit_hours=48
  elif name=='alerts':
   data=data[:15]
   observed=None
   limit_hours=None
  else:
   data=data[-15:]
   observed=next((v.get('time_tag') or v.get('begin_time') or v.get('peak_time') for v in reversed(data) if isinstance(v,dict) and (v.get('time_tag') or v.get('begin_time') or v.get('peak_time'))),None)
   limit_hours=3 if name=='kp' else 72
  stale=False
  if observed and limit_hours:
   dt=datetime.datetime.fromisoformat(observed.replace('Z','+00:00'))
   if dt.tzinfo is None: dt=dt.replace(tzinfo=datetime.timezone.utc)
   stale=(datetime.datetime.now(datetime.timezone.utc)-dt).total_seconds()>limit_hours*3600
  result['solar'][name]={'data':data,'fetched_at':now,'observed_at':observed,'stale':stale,'source':url}
  result['status'][name]='stale' if stale else 'ok'
 except Exception as e:
  old=previous.get('solar',{}).get(name)
  if old: result['solar'][name]={**old,'stale':True}
  result['status'][name]='failed: '+type(e).__name__
for name,url in news.items():
 try:
  root=ET.fromstring(fetch(url));items=[]
  for item in root.findall('.//item')[:15]:
   items.append({k:(item.findtext(k) or '').strip() for k in ('title','link','pubDate')})
  result['news'][name]={'items':items,'fetched_at':now,'stale':False,'source':url};result['status'][name]='ok'
 except Exception as e:
  old=previous.get('news',{}).get(name)
  if old:result['news'][name]={**old,'stale':True}
  result['status'][name]='failed: '+type(e).__name__
OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result['status'],indent=2))
if all(result['status'].get(k)!='ok' for k in feeds):
 raise SystemExit('No fresh NOAA solar feeds; marking workflow failed')
