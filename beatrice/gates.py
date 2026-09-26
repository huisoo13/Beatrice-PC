"""단일 진행 세션의 관문 상태 관리. 시각 단위는 영상의 초입니다."""
import math
import uuid

STATES = {'진행중', '완료', '진행 전'}


class GateTracker:
    def __init__(self, session_id, expected_gates, confirmations=3, min_confidence=.5,
                 max_center_distance=25, max_sample_gap=.6, snapshot_mode=False):
        if not session_id or expected_gates < 1 or confirmations < 2:
            raise ValueError('세션, 예상 관문 수, 확인 횟수를 확인해주세요.')
        self.session_id = session_id
        self.expected = expected_gates
        self.required = confirmations
        self.threshold = min_confidence
        self.distance = max_center_distance
        self.max_gap = max_sample_gap
        self.slots = None
        self.stable = None
        self.candidate = None
        self.count = 0
        self.candidate_since = None
        self.emitted = set()
        self.last_time = None
        self.last_valid = None
        self.snapshot_mode=snapshot_mode

    def clear_candidate(self):
        self.candidate = None
        self.count = 0
        self.candidate_since = None

    def update(self, timestamp, boxes):
        if not math.isfinite(timestamp) or (self.last_time is not None and timestamp <= self.last_time):
            raise ValueError('관측 시각은 유한하고 증가해야 합니다.')
        if self.last_time is not None and timestamp-self.last_time > self.max_gap:
            self.clear_candidate()
        self.last_time = timestamp
        result = {'videoSeconds': timestamp, 'events': []}
        valid = len(boxes) == self.expected
        centers = []
        for b in boxes:
            coords = b.get('xyxy', [])
            if (b.get('state') not in STATES or len(coords) != 4
                or not all(isinstance(v, (float, int)) and math.isfinite(v) for v in coords)
                or not isinstance(b.get('confidence'), (float, int))
                or not math.isfinite(b['confidence']) or not self.threshold <= b['confidence'] <= 1):
                valid = False
                break
            x1,y1,x2,y2 = coords
            if not (0 <= x1 < x2 and 0 <= y1 < y2):
                valid = False
                break
            centers.append(((x1+x2)/2, (y1+y2)/2))
        if valid:
            order = sorted(range(len(boxes)), key=lambda i: centers[i][0])
            ordered = [boxes[i] for i in order]
            points = [centers[i] for i in order]
            # 가까이 겹친 박스가 누락 슬롯 대신 들어오는 경우를 거부합니다.
            valid = all(ordered[i]['xyxy'][2] <= ordered[i+1]['xyxy'][0] for i in range(len(ordered)-1))
            reference = self.slots or getattr(self, 'candidate_slots', None)
            if reference is not None and not self.snapshot_mode:
                valid = valid and all(math.dist(a,b) <= self.distance for a,b in zip(points, reference))
            if valid and self.stable is not None and not self.snapshot_mode:
                valid = all(not (old == '완료' and b['state'] != '완료') for old,b in zip(self.stable,ordered))
        if not valid:
            self.clear_candidate()
            if self.slots is None:
                self.candidate_slots = None
            result.update(status='waiting' if self.stable is None else 'uncertain',
                          reason='배열 누락·저신뢰·위치 불일치·완료 역행 중 하나',
                          stableStates=self.stable, lastValidSeconds=self.last_valid)
            return result
        states = tuple(b['state'] for b in ordered)
        result['observedStates']=states
        if self.snapshot_mode:
            completed=[i for i,s in enumerate(states) if s=='완료']
            completed += [i for i,s in enumerate(self.stable or ()) if s=='완료']
            highest=max(completed,default=-1)
            states=tuple('완료' if i<=highest else s for i,s in enumerate(states))
        self.last_valid = timestamp
        if states != self.candidate:
            self.candidate = states
            self.count = 1
            self.candidate_since = timestamp
            if self.slots is None:
                self.candidate_slots = points
        else:
            self.count += 1
        if self.count >= self.required:
            if self.slots is None:self.slots=self.candidate_slots
            if self.stable is None:
                self.slots = self.candidate_slots
                self.stable = states
                # 시작 시 이미 완료인 관문은 이번 세션의 새 완료 이벤트가 아닙니다.
                self.emitted.update(i+1 for i,s in enumerate(states) if s == '완료')
            else:
                for index,(before,after) in enumerate(zip(self.stable,states),1):
                    if before != '완료' and after == '완료' and index not in self.emitted:
                        self.emitted.add(index)
                        result['events'].append(dict(schemaVersion=1,
                            eventID=str(uuid.uuid5(uuid.NAMESPACE_URL, f'beatrice:{self.session_id}:gate:{index}')),
                            sessionID=self.session_id, eventType='gate_completed', gate=index,
                            previousState=before, state=after,
                            firstObservedSeconds=self.candidate_since, confirmedSeconds=timestamp))
                self.stable = states
        result.update(status='stable' if self.stable == states and self.count >= self.required else 'candidate',
                      stableStates=self.stable, candidateStates=states,
                      consecutiveObservations=self.count, lastValidSeconds=self.last_valid)
        return result
