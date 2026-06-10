"""r22 하드케이스 — r21 잔존 confident FP 강화 음성 + 재난경보 음성.

r21 평가(real_golden 50): specificity 0.682(불변). 격식메일 음성 72로 공고형(g15)은
고쳤으나 **자료공유(g17)·회람(g18)·일정확인(g19)** 은 ~10/형으론 안 죽음(0.5B confident).
+ 신규 과발화 sms_027 산불 **재난경보**(날짜·시각·장소 다 있는 공공안전 알림).

r22 = 잔존 3형을 ~25/형으로 끌어올리고(볼륨 돌파 시도) + 재난경보 음성 신설.
※ ①(anonymizer "민준" 오염 수정)·②(보일러플레이트 desc null)와 같은 라운드.

그룹:
  A 지난행사 자료공유/결과공유 (gmail) — 종료된 행사 자료, 일정 아님.
  B 회람/서식 송부 (gmail) — 확인·검토·회신 요청, 일정 아님.
  C 일정확인/가능시간 요청 (gmail) — 확정 일자 없이 가능시간 취합, 일정 아님.
  D 재난경보/공공안전 (sms) — #CMAS#·기상청·행정안전부, 날짜·시각·장소 있어도 개인일정 아님.

전부 has_schedule:false. 출력: data/processed/r22_hardcases.jsonl
사용: python scripts/build_r22_hardcases.py [--apply]
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

RECV_BASE = "2026-06-08"

# (sender, message) — channel은 그룹별 지정.
A_PAST = [  # 지난행사 자료/결과 공유
    ("onestop@kised.or.kr", "어제 마무리된 전문가 자문단 회의 결과를 정리해 공유드립니다."),
    ("admin@ccei.kr", "지난 데모데이 발표 자료와 심사평을 첨부하여 보내드립니다."),
    ("office@knu.ac.kr", "종료된 산학협력 세미나 녹화본 링크를 안내드립니다."),
    ("pm@tips.or.kr", "금주 진행된 착수보고회 회의록을 공유드립니다. 참고 바랍니다."),
    ("secretary@academy.or.kr", "멘토 간담회가 잘 마무리되었습니다. 논의 내용을 정리해 전달드립니다."),
    ("freedaegu@naver.com", "출범식에 함께해 주셔서 감사합니다. 행사 사진첩 링크를 보내드립니다."),
    ("edu@daegu.go.kr", "창업주간 행사가 종료되었습니다. 주요 성과 자료를 공유드립니다."),
    ("host@founders.kr", "지난 포럼 발제문을 정리하여 회원분들께 공유드립니다."),
    ("contact@kban.or.kr", "투자 IR 행사 종료 후 기업별 피드백을 전달드립니다."),
    ("info@startupbiz.kr", "지난주 네트워킹데이 참가자 명단과 후기를 공유드립니다."),
    ("support@kised.or.kr", "설명회가 종료되어 발표 영상과 Q&A를 정리해 안내드립니다."),
    ("manager@incubator.kr", "입주사 간담회 결과를 요약하여 회신드립니다."),
    ("biz@dgmf.or.kr", "지난달 실증 워크숍 결과 보고서를 공유드립니다."),
    ("jyjeon@koef.or.kr", "분과 회의가 종료되었습니다. 회의 자료를 첨부합니다."),
    ("khmoon@koef.or.kr", "강의가 잘 끝났습니다. 수강생 피드백을 정리해 보내드립니다."),
]

B_CIRC = [  # 회람/서식 송부
    ("support@kised.or.kr", "사업 변경 신청서 양식을 송부드리니 작성 후 회신 바랍니다."),
    ("office@knu.ac.kr", "연구실 안전교육 자료를 회람하오니 숙지 부탁드립니다."),
    ("admin@ccei.kr", "멘토 운영 규정 개정안을 회람드립니다. 의견 있으시면 회신 바랍니다."),
    ("pm@tips.or.kr", "협약 변경 관련 서식을 송부드립니다. 검토 부탁드립니다."),
    ("secretary@academy.or.kr", "멘토 교육 커리큘럼 초안을 공유드리니 검토 바랍니다."),
    ("jyjeon@koef.or.kr", "분과 운영 세칙을 회람합니다. 확인 후 회신 부탁드립니다."),
    ("fund@kised.or.kr", "정산 가이드 개정본을 송부드리니 참고 바랍니다."),
    ("host@founders.kr", "행사 운영 매뉴얼을 회람드립니다. 담당자 공유 부탁드립니다."),
    ("biz@dgmf.or.kr", "시설 이용 수칙을 송부하오니 입주사 전달 바랍니다."),
    ("contact@kban.or.kr", "투자계약 표준 서식을 회람드립니다. 검토 의견 회신 바랍니다."),
    ("edu@daegu.go.kr", "사업 홍보물 시안을 공유드리니 의견 부탁드립니다."),
    ("manager@incubator.kr", "입주 신청 서류 목록을 송부드립니다. 누락 없이 준비 바랍니다."),
    ("office@knu.ac.kr", "학술대회 발표 양식을 회람하오니 기한 내 작성 바랍니다."),
    ("info@startupbiz.kr", "IR 피칭덱 템플릿을 송부드립니다. 해당 양식 사용 바랍니다."),
    ("support@kised.or.kr", "멘토 위촉 관련 안내문을 회람드립니다. 확인 부탁드립니다."),
]

C_AVAIL = [  # 일정확인/가능시간 요청(확정 일자 없음)
    ("jyjeon@koef.or.kr", "다음 분과 회의 가능 일자를 회신해 주시면 취합하겠습니다."),
    ("admin@ccei.kr", "멘토링 일정 조율을 위해 가능 시간대를 알려주시기 바랍니다."),
    ("office@knu.ac.kr", "협약식 참석 가능 여부와 희망 일자를 회신 부탁드립니다."),
    ("pm@tips.or.kr", "착수 미팅 일정을 잡으려 합니다. 가능하신 요일을 알려주세요."),
    ("secretary@academy.or.kr", "워크숍 희망 일정을 설문으로 받습니다. 응답 부탁드립니다."),
    ("khmoon@koef.or.kr", "강의 가능 시간표를 회신 주시면 배정하겠습니다."),
    ("host@founders.kr", "포럼 패널 가능 일정을 조사 중입니다. 회신 부탁드립니다."),
    ("manager@incubator.kr", "입주사 정기 면담 가능 시간을 알려주시기 바랍니다."),
    ("support@kised.or.kr", "멘토 오리엔테이션 일정 조율 중입니다. 가능 주를 알려주세요."),
    ("contact@kban.or.kr", "투자자 미팅 가능 시간대를 취합하고 있습니다. 회신 바랍니다."),
    ("edu@daegu.go.kr", "간담회 일정을 협의하고자 합니다. 가능하신 날짜를 알려주세요."),
    ("biz@dgmf.or.kr", "실증 점검 방문 가능 일자를 회신 부탁드립니다."),
    ("jyjeon@koef.or.kr", "분과별 발표 순서를 정하려 합니다. 가능 시간 회신 바랍니다."),
    ("office@knu.ac.kr", "멘토-멘티 매칭 면담 가능 시간을 알려주시기 바랍니다."),
    ("admin@ccei.kr", "데모데이 리허설 가능 일정을 조사 중입니다. 회신 부탁드립니다."),
]

D_ALERT = [  # 재난경보/공공안전 (sms) — 날짜·시각·장소 있어도 개인일정 아님
    ("#CMAS#Severe", "[기상청] 오늘 15시 대구·경북 호우경보. 하천변 접근 자제, 외출 자제 바랍니다."),
    ("행정안전부", "[안전안내] 6/12 02시 경북 북부 지진 발생(규모 3.5). 여진에 주의 바랍니다."),
    ("#CMAS#Emergency", "오늘 09:20 달성군 가창면 산불 확산 중. 인근 주민 대피 준비 바랍니다."),
    ("대구광역시", "[폭염경보] 오늘 14시 기준 대구 체감 35도. 야외활동 자제, 수분 섭취 바랍니다."),
    ("기상청", "내일 06시까지 대구 강풍주의보. 시설물 관리에 유의하세요."),
    ("#CMAS#Amber", "[실종경보] 오늘 11시 수성구 인근 80대 어르신 실종. 발견 시 112 신고 바랍니다."),
    ("행정안전부", "[한파주의보] 6/14 새벽 기온 급강하. 수도계량기 동파에 주의 바랍니다."),
    ("대구광역시", "오늘 17시 신천대로 침수로 통제. 우회 바랍니다."),
    ("#CMAS#Severe", "[대설주의보] 내일 오전 대구 산간 적설 예상. 차량 운행에 주의 바랍니다."),
    ("기상청", "오늘 20시 황사 유입. 창문을 닫고 외출 시 마스크 착용 바랍니다."),
    ("행정안전부", "[화재] 오늘 22:10 북구 산격동 공장 화재. 인근 주민 연기에 주의 바랍니다."),
    ("대구광역시", "오늘 미세먼지 매우 나쁨. 호흡기 질환자 외출 자제 바랍니다."),
]


def rows(records, channel, prefix):
    out = []
    for i, (sender, msg) in enumerate(records):
        out.append({"scenario_id": f"{prefix}_{i:03d}",
                    "received_at": f"{RECV_BASE}T{8 + (i % 12):02d}:{(i * 11) % 60:02d}:00+09:00",
                    "channel": channel, "sender": sender, "language": "ko",
                    "message": msg, "gold": {"has_schedule": False, "events": []}})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    groups = {
        "A 지난행사 자료공유(gmail)": rows(A_PAST, "gmail", "g22_past"),
        "B 회람/서식 송부(gmail)": rows(B_CIRC, "gmail", "g22_circ"),
        "C 일정확인/가능시간(gmail)": rows(C_AVAIL, "gmail", "g22_avail"),
        "D 재난경보/공공안전(sms)": rows(D_ALERT, "sms", "g22_alert"),
    }
    allrows = [r for g in groups.values() for r in g]
    for name, g in groups.items():
        print(f"  {name:28} {len(g):3}건")
    print(f"  {'합계':28} {len(allrows):3}건  (전부 has_schedule:false)")
    if args.apply:
        p = "data/processed/r22_hardcases.jsonl"
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            for r in allrows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"→ {p}")
    else:
        print("(미리보기 — --apply 로 기록)")


if __name__ == "__main__":
    main()
