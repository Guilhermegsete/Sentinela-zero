import json, urllib.request, datetime, pathlib, xml.etree.ElementTree as ET
OUT=pathlib.Path(__file__).resolve().parents[1]/'docs'/'data.json'
feeds={'regions':'https://services.swpc.noaa.gov/json/solar_regions.json','kp':'https://services.swpc.noaa.gov/json/planetary_k_index_1m.json','flares':'https://services.swpc.noaa.gov/json/goes/primary/xray-flares-latest.json','alerts':'https://services.swpc.noaa.gov/json/alerts.json'}
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
  data=json.loads(fetch(url));result['solar'][name]={'data':data[-15:] if isinstance(data,list) else data,'fetched_at':now,'stale':False,'source':url};result['status'][name]='ok'
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
