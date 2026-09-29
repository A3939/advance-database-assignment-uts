"""Download public ABS boundaries only; never access ARSIA original data."""
import urllib.parse, json, hashlib, subprocess
from pathlib import Path
endpoint='https://geo.abs.gov.au/arcgis/rest/services/ASGS2024/LGA/MapServer/1/query'
root=Path(__file__).resolve().parents[1]/'public/geo'
receipts=[]
for code,state in [('1','nsw'),('2','vic'),('3','qld')]:
    params={'where':f"state_code_2021='{code}'",'outFields':'lga_code_2024,lga_name_2024,state_name_2021','outSR':'4326','f':'geojson','returnGeometry':'true','maxAllowableOffset':'0.008','geometryPrecision':'4'}
    url=endpoint+'?'+urllib.parse.urlencode(params)
    data=json.loads(subprocess.check_output(["curl","-fsSL","--max-time","60",url]))
    if data.get('type')!='FeatureCollection' or data.get('exceededTransferLimit'):raise ValueError(data)
    data['features']=[f for f in data['features'] if f.get('geometry')]
    for feature in data['features']:feature['id']=int(feature['properties']['lga_code_2024'])
    raw=json.dumps(data,separators=(',',':')).encode()
    (root/f'{state}-lga.geojson').write_bytes(raw)
    receipts.append({'state':state,'url':url,'features':len(data['features']),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
    print(state,len(data['features']),len(raw))
(root/'provenance.json').write_text(json.dumps({'publisher':'Australian Bureau of Statistics (ABS)','dataset':'ASGS 2024 LGA_GEN','license':'CC BY 4.0','license_url':'https://creativecommons.org/licenses/by/4.0/','retrieved':'2026-09-29','crs':'EPSG:4326 (requested from the ABS service)','modifications':'Service-generalised at 0.008 degrees; coordinates rounded to 4 decimals; null geometries omitted; feature IDs added. Statistical approximations, not legal boundaries.','files':receipts},indent=2))
