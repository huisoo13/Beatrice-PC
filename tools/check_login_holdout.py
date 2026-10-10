"""Offline review annotations for the preserved October 1 login, not runtime ROIs."""
import argparse,json
from pathlib import Path

if __package__:
    from .evaluation_geometry import iou
else:
    from evaluation_geometry import iou

def main():
    p=argparse.ArgumentParser();p.add_argument('report',type=Path);a=p.parse_args()
    report=json.loads(a.report.read_text(encoding='utf-8'));checks=[]
    for row in report['rows']:
        n=int(row['frame'][6:9]);expected={}
        if 2<=n<=5:expected['server_table']=[745,385,1305,777]
        if 8<=n<=17:
            expected.update(selected_character_card=[642,709,823,758],game_start_button=[857,784,1023,828])
        if 18<=n<=37:
            # Offline annotation helper: find the bright marker inside the
            # manually reviewed bar, never imported by runtime recognition.
            import numpy as np
            from PIL import Image
            im=Image.open(a.report.parent/row['frame'].replace('.json','.jpg')).resize((2048,857))
            pixels=np.asarray(im.crop((300,802,1740,842))).astype(float)
            energy=np.maximum(0,np.minimum(pixels[:,:,1],pixels[:,:,2])-pixels[:,:,0]).sum(axis=0)
            center=300+int(np.argmax(np.convolve(energy,np.ones(7),mode='same')))
            expected['loading_progress']=[center-52,802,center+29,842]
        matches={}
        for kind,box in expected.items():
            detected=row['regions'].get(kind,{})
            overlap=iou(detected['xyxy'],[v*3440/2048 for v in box]) if detected.get('status')=='detected' else 0
            matches[kind]=round(overlap,3)
        extras=[k for k in ('server_table','selected_character_card','game_start_button','loading_progress')
                if k not in expected and row['regions'].get(k,{}).get('status')!='missing']
        checks.append(dict(frame=n,iou=matches,unexpected=extras))
    result=dict(checks=checks,final=report.get('final'))
    output=a.report.with_name(a.report.stem+'-geometry.json');output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    for k in ('server_table','selected_character_card','game_start_button','loading_progress'):
        vals=[r['iou'][k] for r in checks if k in r['iou']]
        print(k, sum(v>=.5 for v in vals),'/',len(vals))
    print('Unexpected frame/classes',[(r['frame'],r['unexpected']) for r in checks if r['unexpected']])

if __name__=='__main__':main()
