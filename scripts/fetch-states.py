"""Cache public ABS state boundaries for the local country overview."""
import urllib.parse, json, hashlib, subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]/'public/geo'
url='https://geo.abs.gov.au/arcgis/rest/services/ASGS2021/STE/MapServer/1/query?'+urllib.parse.urlencode({'where':'1=1','outFields':'state_code_2021,state_name_2021','outSR':'4326','f':'geojson','returnGeometry':'true','maxAllowableOffset':'0.015','geometryPrecision':'4'})
data=json.loads(subprocess.check_output(['curl','-fsSL','--max-time','60',url]))
assert data['type']=='FeatureCollection' and not data.get('exceededTransferLimit')
data['features']=[f for f in data['features'] if f.get('geometry')]
assert len(data['features'])==9
for f in data['features']: f['id']=f['properties']['state_code_2021']
raw=json.dumps(data,separators=(',',':')).encode()
(root/'australia-states.geojson').write_bytes(raw)
p=root/'provenance.json';receipt=json.loads(p.read_text());receipt['state_boundaries']={'dataset':'ABS ASGS 2021 STE_GEN','url':url,'license':'CC BY 4.0','retrieved':'2026-09-29','features':9,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'modifications':'Generalised at 0.015 degrees; coordinates rounded to 4 decimals; feature IDs added. Default camera frames mainland Australia and Tasmania; all nine ABS features including other territories remain in the file.'};p.write_text(json.dumps(receipt,indent=2)+'\n');print(len(raw),'bytes; 9 state/territory features')
