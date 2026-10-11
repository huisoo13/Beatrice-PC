"""Canonical completed-record JSON and the legacy recognition adapter."""
import copy
import re
import uuid
from datetime import datetime,timezone
from .record_identity import existing_time,record_id,normalized_time

FIELDS=('recordId','characterName','contentName','difficulty','gateNumber','expectedGates','isTest','observedAt','createdAt','updatedAt')
META=('ocrOriginal','catalogMatch')
OPTIONAL=('goldReward',)

def utc(value):
    if value is None:return None
    normalized_time(value)  # Validate without losing the original precision.
    at=datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(timezone.utc)
    return at.isoformat(timespec='milliseconds' if at.microsecond%1000==0 else 'microseconds').replace('+00:00','Z')

def canonical(row):
    """Convert old completed rows; unavailable historical facts remain unknown."""
    if 'contentName' in row and 'dungeonName' not in row:
        value=copy.deepcopy(row)
        return {k:value[k] for k in (*FIELDS,*META,*OPTIONAL) if k in value}
    imported=row.get('evidenceType')=='drive_import' or row.get('timeBasis')=='drive_import'
    gate=0 if row.get('completionScope')=='raid' else row.get('gate',0)
    name=row.get('characterName');content=row.get('dungeonName')
    value=dict(recordId=row.get('recordID') or (record_id(name,content,gate) if name and content else None),
        characterName=name,contentName=content,difficulty=row.get('difficulty'),gateNumber=gate,
        expectedGates=0 if gate==0 else row.get('expectedGates') or 0,
        isTest=bool(row.get('isTest') or row.get('timeBasis')=='synthetic_test'),
        observedAt=None if imported else utc(row.get('observedAt')),
        createdAt=None if imported else utc(row.get('savedAt') or row.get('createdAt')),
        updatedAt=existing_time(row))
    for field in META:
        if field not in row:continue
        meta=copy.deepcopy(row[field])
        for before,after in (('dungeonName','contentName'),('gate','gateNumber')):
            if before in meta:meta[after]=meta.pop(before)
        if 'gateName' in meta:
            label=meta.pop('gateName');match=re.fullmatch(r'(\d+)관문',label)
            if match:meta['gateNumber']=int(match[1])
        if gate==0 and 'gateNumber' in meta:meta['gateNumber']=0
        value[field]=meta
    if 'goldReward' in row:value['goldReward']=row['goldReward']
    return value

def recognition_record(row):
    """Transient adapter for OCR/catalog modules; never persist this representation."""
    if 'contentName' not in row:return copy.deepcopy(row)
    value=copy.deepcopy(row)
    value.update(recordID=row.get('recordId'),dungeonName=row['contentName'],gate=row['gateNumber'] or 1,
        state='완료',completionScope='raid' if row['gateNumber']==0 else 'gate',
        characterKey='name:'+row['characterName'] if row.get('characterName') else None)
    for field in META:
        if field not in value:continue
        meta=value[field]
        if 'contentName' in meta:meta['dungeonName']=meta.pop('contentName')
        if 'gateNumber' in meta:
            number=meta.pop('gateNumber');meta['gate']=number or 1
            if field=='catalogMatch':meta['gateName']=f'{number or 1}관문'
    return value

def new_record(row,expected_gates,previous=None):
    value=canonical(dict(row,expectedGates=expected_gates))
    now=datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
    value['recordId']=previous['recordId'] if previous else 'br2_'+uuid.uuid4().hex
    value['createdAt']=previous['createdAt'] if previous else now
    value['updatedAt']=now
    return validate(value)

def validate(row):
    if not isinstance(row,dict) or not set(FIELDS)<=set(row) or set(row)-set(FIELDS+META+OPTIONAL):raise ValueError('완료 기록 필드를 확인해주세요.')
    value=copy.deepcopy(row)
    if value.get('goldReward') is not None and type(value['goldReward']) is not bool:raise ValueError('goldReward는 bool 또는 null이어야 합니다.')
    for field in ('characterName','contentName','difficulty'):
        text=value[field]
        if not isinstance(text,str) or not text.strip() or len(text)>200 or any(ord(c)<32 for c in text):raise ValueError('기록 이름·난이도가 올바르지 않습니다.')
    for field in ('gateNumber','expectedGates'):
        if type(value[field]) is not int or not 0<=value[field]<=8:raise ValueError('관문 번호와 전체 수는 0~8이어야 합니다.')
    gate,expected=value['gateNumber'],value['expectedGates']
    if (gate==0 and expected!=0) or (expected and gate>expected):raise ValueError('관문 번호와 전체 수가 일치하지 않습니다.')
    if type(value['isTest']) is not bool:raise ValueError('isTest는 bool이어야 합니다.')
    identifier=value['recordId']
    if not isinstance(identifier,str) or not re.fullmatch(r'br(?:1_[0-9a-f]{64}|2_[0-9a-f]{32})',identifier):raise ValueError('recordId 형식 오류')
    for field in ('observedAt','createdAt','updatedAt'):
        value[field]=utc(value[field])
    if value['updatedAt'] is None:raise ValueError('updatedAt이 필요합니다.')
    if 'ocrOriginal' in value:
        meta=value['ocrOriginal']
        if not isinstance(meta,dict) or set(meta)!={'contentName','difficulty','gateNumber'}:raise ValueError('OCR 원문 필드 오류')
        if not isinstance(meta['contentName'],str) or not isinstance(meta['difficulty'],str) or type(meta['gateNumber']) is not int or not 0<=meta['gateNumber']<=8:raise ValueError('OCR 원문 값 오류')
    if 'catalogMatch' in value:
        meta=value['catalogMatch']
        if not isinstance(meta,dict) or meta.get('status') not in ('matched','unmatched','ambiguous'):raise ValueError('매칭 상태 오류')
        if meta['status']=='matched':
            required={'status','contentName','difficulty','gateNumber','version','values'}
            if not required<=set(meta) or set(meta)-required-{'fieldName'}:raise ValueError('매칭 필드 오류')
            if type(meta['gateNumber']) is not int or meta['gateNumber']!=gate:raise ValueError('매칭 관문 번호 오류')
            if not all(isinstance(meta[k],str) and meta[k].strip() for k in ('contentName','difficulty')):raise ValueError('매칭 이름 오류')
            if not isinstance(meta['version'],dict):raise ValueError('공용 데이터 버전 오류')
            from .content_catalog import validate_reward,ContentError
            try:validate_reward(meta['values'])
            except ContentError as error:raise ValueError(str(error)) from error
            if set(meta['version'])-{'id','version','md5Checksum'} or any(not isinstance(v,str) or not v or len(v)>200 for v in meta['version'].values()):raise ValueError('공용 데이터 버전 값 오류')
            if 'fieldName' in meta and (not isinstance(meta['fieldName'],str) or not meta['fieldName'].strip()):raise ValueError('공용 데이터 화면 이름 오류')
        elif set(meta)!={'status'}:raise ValueError('미매칭 자료에는 status만 허용합니다.')
    return value


def period(row):
    """Unknown observedAt cannot identify a completion's reset period."""
    from .weekly import week_start
    at=row.get('observedAt')
    return week_start(datetime.fromisoformat(at.replace('Z','+00:00'))) if at else None


def deduplicate(rows, name=lambda row:row['contentName']):
    """Keep the first observation for each character/content/gate/reset-period."""
    from .dungeon import key
    seen=set();result=[]
    for row in sorted(rows,key=lambda row:(row.get('observedAt') or '',row.get('createdAt') or '',row['recordId'])):
        week=period(row)
        identity=(row['isTest'],row['characterName'],key(name(row)),row['gateNumber'],week)
        if week is not None and identity in seen:continue
        if week is not None:seen.add(identity)
        result.append(row)
    return result
