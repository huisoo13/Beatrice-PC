"""Check the reviewed replay, not an independent accuracy benchmark."""
import argparse,json
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('report',type=Path);a=p.parse_args()
    d=json.loads(a.report.read_text(encoding='utf-8'))
    dim=[];wrong=[];early=[]
    for row in d['rows']:
        n=int(row['frame'][6:9]);obs=row['observation'];state=row['state']
        if 12<=n<=21:
            value=(obs.get('selectedName') or {}).get('text')
            dim.append((n,value))
            if value and value!='테베체':wrong.append((n,value))
        if n<39 and state['recordingAllowed']:early.append(n)
    result=dict(dimReadings=dim,wrongDimNames=wrong,earlyRecording=early,final=d['final'])
    print(json.dumps(result,ensure_ascii=False))
    if wrong or early or sum(name=='테베체' for _,name in dim)<3 or d['final']['currentName']!='테베체' or not d['final']['recordingAllowed']:
        raise SystemExit(1)

if __name__=='__main__':main()
