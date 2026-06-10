"""학습 페어 익명화 — 실 사적 메시지를 리포에 push하기 전 PII 제거.

설계 원칙:
  1) **페어 정합 보존**: message·gold·thread·sender 전반에서 같은 이름은 같은 가명으로
     일관 치환한다. 한쪽만 바꾸면 (message↔gold) 학습 페어가 깨진다.
  2) **시간 신호 불가침**: date/time/end_time/recurrence 등 스키마의 일정 필드와
     메시지 내 '3시·12일·내일' 같은 표면형은 절대 건드리지 않는다([[feedback_time_first_priority]]).
  3) **아는 이름만 치환**: 임의 한글을 사람이름으로 오인해 '회의/점심'을 뭉개지 않도록,
     이름 후보는 sender + gold(attendees/organizer) + thread sender 에서만 모은다.
  4) **패턴 마스킹**: 전화·주민번호·카드·계좌·이메일·URL 은 정규식으로 마스킹(텍스트 필드 한정).

사용:
    # 모듈
    from anonymize import anonymize_record
    rec = anonymize_record(rec)
    # CLI (임의 jsonl 스크럽)
    python scripts/anonymize.py --in data/processed/train.jsonl --out data/processed/train.anon.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re

# 가명 풀(결정론적 배정 — 첫 등장 순). 한글/영문 분리.
_PSEUDO_KO = ["민준", "서연", "도윤", "지우", "하준", "서윤", "예준", "지유", "주원", "채원",
              "지호", "수아", "건우", "유나", "현우", "지민", "준서", "은우", "민서", "지안",
              "선우", "다은", "시우", "예린", "연우", "수빈", "정우", "하린", "지환", "소율"]
_PSEUDO_EN = ["Alex", "Sam", "Jordan", "Taylor", "Casey", "Morgan", "Riley", "Jamie",
              "Quinn", "Avery", "Drew", "Reese", "Skyler", "Rowan", "Emery", "Parker"]

# 개인 이름이 아닌(=치환 제외) 발신자 키워드(기관·서비스)
_ORG_HINT = re.compile(
    r"센터|은행|카드|증권|보험|병원|의원|약국|회사|공단|지원|관리|학교|학원|"
    r"국세|세무|구청|시청|동사무소|주민센터|배송|택배|쿠팡|배민|토스|페이|뱅크|"
    r"알림|고객|상담|안내|예약|Web발신|발신|no.?reply|noreply|admin|team|notification|"
    r"기상청|재난|긴급|소방|경찰|행정안전|행안|안전안내|광역시|특별시|도청|군청|CMAS",
    re.IGNORECASE,
)

# 패턴 마스킹(텍스트 필드 한정). 날짜/시각 표면형은 매칭하지 않도록 좁게.
# ★ 단일 정규식 1회 치환: 순차 sub는 치환 결과(예: 전화 마스킹값)를 뒤 패턴이 재매칭해
#   덮어쓰는 문제가 있어, alternation 우선순위(앞 그룹 우선)로 한 번에 처리한다.
_MASK = {
    "url": "http://example.com",
    "email": "user@example.com",
    "rrn": "000000-0000000",          # 주민번호
    "card": "0000-0000-0000-0000",    # 카드
    "phone": "010-0000-0000",         # 전화
    "acct": "000-000-000000",         # 계좌(하이픈식)
}
_PII = re.compile(
    r"(?P<url>https?://\S+)"
    r"|(?P<email>[\w.+-]+@[\w-]+\.[\w.-]+)"
    r"|(?P<rrn>\b\d{6}\s*-\s*[1-4]\d{6}\b)"
    r"|(?P<card>\b\d{4}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4}\b)"
    r"|(?P<phone>\b0\d{1,2}[-\s]?\d{3,4}[-\s]?\d{4}\b)"
    r"|(?P<acct>\b\d{2,6}-\d{2,6}-\d{2,6}\b)"
)


def _is_personal(name: str | None) -> bool:
    if not name:
        return False
    n = name.replace("[Web발신]", "").strip()
    if len(n) < 2 or _ORG_HINT.search(n):
        return False
    # 한글 2~4자 또는 영문 이름(공백 포함 가능) — 너무 길면 문장일 수 있어 제외
    if re.fullmatch(r"[가-힣]{2,4}", n):
        return True
    if re.fullmatch(r"[A-Za-z]+(?:\s[A-Za-z]+){0,2}", n) and len(n) <= 20:
        return True
    return False


def _pseudo_for(name: str, mapping: dict) -> str:
    """이름→가명. **이름 해시 기반 분산** 배정(같은 이름=항상 같은 가명, 풀 전체에 고르게).
    ★ 과거 per-record counter 방식은 각 레코드 첫 이름을 항상 pool[0]="민준"으로 찍어
      학습셋 43%가 "민준"이 되는 오염을 냈다(r19~r21). 해시 분산으로 교정.
    레코드 내 서로 다른 이름의 가명 충돌은 선형 탐사로 회피(두 사람이 한 가명으로 합쳐지지 않게)."""
    if name in mapping:
        return mapping[name]
    if re.search(r"[가-힣]", name):
        pool, key = _PSEUDO_KO, "ko"
    else:
        pool, key = _PSEUDO_EN, "en"
    used = set(mapping.values())
    base = int(hashlib.md5(name.encode("utf-8")).hexdigest(), 16) % len(pool)
    for off in range(len(pool)):
        cand = pool[(base + off) % len(pool)]
        if cand not in used:
            mapping[name] = cand
            return cand
    pseudo = f"{'사람' if key == 'ko' else 'Person'}{len(used) + 1}"  # 풀 소진(이름 수>풀 크기)
    mapping[name] = pseudo
    return pseudo


def _scrub_text(s: str, name_map: dict) -> str:
    """텍스트에서 (1) 알려진 이름 → 가명, (2) 패턴 마스킹. 긴 이름부터 치환(부분일치 방지)."""
    if not isinstance(s, str) or not s:
        return s
    for raw in sorted(name_map, key=len, reverse=True):
        if raw and raw in s:
            s = s.replace(raw, name_map[raw])
    s = _PII.sub(lambda m: _MASK[m.lastgroup], s)
    return s


def anonymize_record(rec: dict) -> dict:
    """페어 1건 익명화. 원본을 변형하지 않고 새 dict 반환."""
    import copy
    rec = copy.deepcopy(rec)
    gold = rec.get("gold") or {}
    events = gold.get("events") or []
    thread = rec.get("thread_context") or []

    # 1) 이름 후보 수집 → 가명 매핑(결정론적: attendees/organizer/sender/thread sender)
    name_map: dict[str, str] = {}
    cand: list[str] = []
    for ev in events:
        if isinstance(ev, dict):
            cand += [a for a in (ev.get("attendees") or []) if a]
            if ev.get("organizer"):
                cand.append(ev["organizer"])
    for who in ([rec.get("sender")] + [t.get("sender") for t in thread if isinstance(t, dict)]):
        if _is_personal(who):
            cand.append(who.replace("[Web발신]", "").strip())
    # 길이 내림차순으로 안정 배정(부분일치 방지)
    for nm in sorted(dict.fromkeys(cand), key=len, reverse=True):
        _pseudo_for(nm, name_map)

    # 2) 텍스트 필드 스크럽
    rec["message"] = _scrub_text(rec.get("message", ""), name_map)
    # sender: 개인이면 가명, 기관이면 유지([Web발신] 접두는 보존)
    snd = rec.get("sender")
    if _is_personal(snd):
        core = snd.replace("[Web발신]", "").strip()
        rec["sender"] = snd.replace(core, name_map.get(core, core))
    for t in thread:
        if isinstance(t, dict):
            t["message"] = _scrub_text(t.get("message", ""), name_map)
            if _is_personal(t.get("sender")):
                c = t["sender"].replace("[Web발신]", "").strip()
                t["sender"] = name_map.get(c, c)

    # 3) gold 텍스트 필드(이름·자유텍스트만; 날짜/시각/반복은 불가침)
    for ev in events:
        if not isinstance(ev, dict):
            continue
        for f in ("title", "location", "description"):
            if isinstance(ev.get(f), str):
                ev[f] = _scrub_text(ev[f], name_map)
        if ev.get("organizer"):
            ev["organizer"] = name_map.get(ev["organizer"], ev["organizer"])
        if isinstance(ev.get("attendees"), list):
            ev["attendees"] = [name_map.get(a, a) for a in ev["attendees"]]

    rec["_anon"] = True
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    n = 0
    with open(args.inp, "rb") as fi, open(args.out, "w", encoding="utf-8") as fo:
        for line in fi:
            line = line.strip()
            if not line:
                continue
            fo.write(json.dumps(anonymize_record(json.loads(line)), ensure_ascii=False) + "\n")
            n += 1
    print(f"익명화 {n}건 → {args.out}")


if __name__ == "__main__":
    main()
