import unittest
from beatrice.gates import GateTracker


def boxes(*states):
    return [dict(state=s,confidence=.9,xyxy=[60+i*100,130,100+i*100,180]) for i,s in enumerate(states)]


class GateTests(unittest.TestCase):
    def setUp(self):
        self.t=GateTracker('test',2)
        self.now=-.2

    def feed(self,b,n=1):
        events=[]
        for _ in range(n):
            self.now+=.2
            events+=self.t.update(self.now,b)['events']
        return events

    def test_completion_once_after_return(self):
        self.assertEqual(self.feed(boxes('완료','진행중'),3),[])
        e=self.feed(boxes('완료','완료'),3)
        self.assertEqual([v['gate'] for v in e],[2])
        self.feed([],20)
        self.assertEqual(self.feed(boxes('완료','완료'),8),[])

    def test_start_already_complete(self):
        self.assertEqual(self.feed(boxes('완료','완료'),10),[])

    def test_one_frame_error(self):
        self.feed(boxes('완료','진행중'),3)
        self.feed(boxes('완료','완료'))
        self.assertEqual(self.feed(boxes('완료','진행중'),3),[])
        self.assertEqual(self.t.stable,('완료','진행중'))

    def test_missing_slot_does_not_shift(self):
        self.feed(boxes('진행중','진행 전'),3)
        self.assertEqual(self.feed(boxes('완료'),5),[])
        self.assertEqual(self.t.stable,('진행중','진행 전'))

    def test_low_confidence_breaks_streak(self):
        self.feed(boxes('완료','진행중'),3)
        self.feed(boxes('완료','완료'),2)
        b=boxes('완료','완료');b[1]['confidence']=.1
        self.feed(b)
        self.assertEqual(self.feed(boxes('완료','완료'),2),[])
        self.assertEqual(len(self.feed(boxes('완료','완료'))),1)

    def test_duplicate_and_displaced_boxes(self):
        self.feed(boxes('완료','진행중'),3)
        b=boxes('완료','완료');b[1]['xyxy']=b[0]['xyxy'][:]
        self.assertEqual(self.feed(b,3),[])
        b=boxes('완료','완료');b[1]['xyxy']=[v+100 for v in b[1]['xyxy']]
        self.assertEqual(self.feed(b,3),[])

    def test_long_gap_resets_candidate(self):
        self.feed(boxes('완료','진행중'),3)
        self.feed(boxes('완료','완료'),2);self.now+=10
        self.assertEqual(self.feed(boxes('완료','완료'),2),[])
        self.assertEqual(len(self.feed(boxes('완료','완료'))),1)

    def test_pending_to_done_and_monotonic_clock(self):
        self.feed(boxes('완료','진행 전'),3)
        self.assertEqual(len(self.feed(boxes('완료','완료'),3)),1)
        with self.assertRaises(ValueError):self.t.update(self.now,[])
        self.assertEqual(self.feed(boxes('완료','진행중'),3),[])

if __name__=='__main__':unittest.main()
