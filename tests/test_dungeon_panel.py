import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock
import numpy as np
from tools.legacy_gate_annotations import load_config,relative_box
from beatrice.dungeon import DungeonOCR


def box(coords,confidence=.95):
    return Mock(xyxy=np.array([coords]),conf=[confidence],cls=[0])


class DungeonPanelTests(unittest.TestCase):
    def test_crop_retry_requires_two_agreeing_complete_arrays(self):
        from tools.legacy_gate_annotations import predict_panel_gates
        frame=np.zeros((400,600,3),dtype=np.uint8)
        def boxes(offset=0,state=0):
            return [Mock(xyxy=np.array([[40+offset,20,80+offset,60]]),conf=[.9],cls=[0]),
                    Mock(xyxy=np.array([[190+offset,20,230+offset,60]]),conf=[.9],cls=[state])]
        for agree in (True,False):
            model=Mock();model.names={0:'완료',1:'진행중'}
            model.predict.side_effect=[[Mock(boxes=boxes()[:1])],
                [Mock(boxes=boxes(2))],[Mock(boxes=boxes(-2,0 if agree else 1))]]
            result=predict_panel_gates(model,frame,[32,112,352,224],expected_count=2)
            self.assertEqual(len(result),2 if agree else 1)
            self.assertEqual(model.predict.call_count,3)
            self.assertAlmostEqual(result[0]['xyxy'][0],72)

    def test_gate_crop_preserves_icon_aspect_without_shrinking_detected_region(self):
        from tools.legacy_gate_annotations import gate_crop_box
        original=[32,112,352,224]
        self.assertEqual(gate_crop_box(original,(1440,3440,3)),original)
        for box in ([14,115,327,201],[40,120,200,220]):
            l,t,r,b=gate_crop_box(box,(1440,3440,3))
            self.assertLessEqual(l,box[0]);self.assertLessEqual(t,box[1])
            self.assertGreaterEqual(r,box[2]);self.assertGreaterEqual(b,box[3])
            self.assertAlmostEqual((r-l)/(b-t),320/112,delta=.05)




    def test_ocr_reads_original_pixels_in_detected_panel(self):
        frame=np.zeros((1080,1920,3),dtype=np.uint8)
        location=dict(status='detected',xyxy=[500,200,860,404],regions={name:relative_box([500,200,860,404],value,frame.shape) for name,value in load_config()['regions'].items()})
        l,t,r,b=location['regions']['dungeonName'];frame[t:b,l:r]=200
        l,t,r,b=location['regions']['difficulty'];frame[t:b,l:r]=200
        reader=Mock();reader.recognize.side_effect=[[(None,'새로운 던전',.99)]]*3+[[(None,'하드',.99)]]*3
        result=DungeonOCR(reader=reader).analyze_detected(frame,location,
            [dict(state='진행중',confidence=.99,xyxy=[60,130,100,180])])
        self.assertEqual(result['dungeonName']['text'],'새로운 던전')
        self.assertTrue(result['dungeonVisible'])
        self.assertGreaterEqual(reader.recognize.call_args_list[0].args[0].shape[1],
                                location['regions']['dungeonName'][2]-location['regions']['dungeonName'][0])


    def test_training_preparation_preserves_images_and_negative_labels(self):
        from PIL import Image
        from tools.train_dungeon_panel import prepare
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);items=[]
            for i,(split,positive) in enumerate([('train',True),('train',False),('val',True),('val',False)]):
                Image.new('RGB',(200+i*10,100),(i*30,0,0)).save(root/f'{i}.png')
                items.append(dict(path=f'{i}.png',sessionId=split,split=split,boxes=[[20,10,100,80]] if positive else []))
            manifest=root/'labels.json';manifest.write_text(json.dumps(dict(classes=['dungeon_panel'],images=items)),encoding='utf-8')
            result=prepare(manifest,root/'dataset')
            self.assertTrue(result.is_file())
            self.assertEqual((root/'dataset/labels/train/00001.txt').read_text(),'')
            with Image.open(root/'dataset/images/val/00002.png') as im:self.assertEqual(im.size,(220,100))
            with self.assertRaises(ValueError):prepare(manifest,root/'dataset')

    def test_training_preparation_rejects_session_leakage_before_writing(self):
        from PIL import Image
        from tools.train_dungeon_panel import prepare
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);items=[]
            for i,split in enumerate(['train','val']):
                Image.new('RGB',(100,100),(i*100,0,0)).save(root/f'{i}.png')
                items.append(dict(path=f'{i}.png',sessionId='same-session',split=split,boxes=[[0,0,50,50]]))
            manifest=root/'labels.json';manifest.write_text(json.dumps(dict(classes=['dungeon_panel'],images=items)),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'세션'):prepare(manifest,root/'dataset')
            self.assertFalse((root/'dataset').exists())

    def test_reconstruction_mode_is_explicit_and_marked(self):
        from PIL import Image
        from tools.train_dungeon_panel import prepare
        import yaml
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            Image.new('RGB',(100,100),'white').save(root/'positive.png')
            Image.new('RGB',(100,100),'black').save(root/'negative.png')
            document=dict(classes=['dungeon_panel'],images=[
                dict(path='positive.png',sessionId='one',split='train',boxes=[[0,0,50,50]]),
                dict(path='negative.png',sessionId='one',split='train',boxes=[])])
            manifest=root/'labels.json';manifest.write_text(json.dumps(document),encoding='utf-8')
            with self.assertRaises(ValueError):prepare(manifest,root/'strict')
            dataset=prepare(manifest,root/'reconstruction',reconstruction=True)
            config=yaml.safe_load(dataset.read_text())
            self.assertEqual(config['train'],config['val'])
            report=json.loads((dataset.parent/'manifest.json').read_text())
            self.assertEqual(report['evaluationPurpose'],'training_reconstruction_only_not_independent')


if __name__=='__main__':unittest.main()
