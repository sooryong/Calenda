"""r21 하드케이스 빌더 — 격식 기관메일 음성 보강(r20 confident FP 교정).

r20 과발화 7건 중 4건이 **격식 기관메일**에서 신뢰도 0.86~0.97로 발화:
  g15 2차모집 공고 / g17 설명회 자료공유(지난행사) / g18 강의안 회람 / g19 분과 일정확인 부탁.
원인 = G2(격식 기관메일 '선택참석 양성' 12)를 부으며 모델이 "격식 기관메일=일정"으로
과일반화. 비율(50%)만으론 confident FP가 안 죽으므로(결정경계 문제) 같은 표면형의
**음성**을 직격 보강해 G2를 상쇄한다.

핵심 규칙(양성 누수 방지):
  - **확정 미래 일자+행사가 없는 격식메일**만 음성. "~MM/DD까지" 같은 명시 마감은
    종일 양성(real_golden g10)이므로 절대 넣지 않는다.
  - 표면형: 공고/모집·자료송부/회람·지난행사 후기·일정확인/가능시간 요청·추후안내/미확정·
    정산/서류 행정·결과발표/뉴스레터. 전부 has_schedule:false.

출력: data/processed/r21_hardcases.jsonl
사용: python scripts/build_r21_hardcases.py [--apply]
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

RECV_BASE = "2026-06-09"

# (sender, message) — 채널은 전부 gmail(격식메일). has_schedule:false.
GOV_NEG = [
    # ── N1 공고/모집 (행사·확정일자 없음) ─────────────────────────────
    ("support@kised.or.kr", "2025년도 예비창업패키지 모집 공고를 안내드립니다. 자세한 사항은 첨부 공고문을 참고하여 주시기 바랍니다."),
    ("office@knu.ac.kr", "산학협력 우수사례 공모전 개최 안내입니다. 참가 희망 시 첨부 양식을 작성해 제출 부탁드립니다."),
    ("admin@ccei.kr", "2025 액셀러레이팅 프로그램 참여기업 모집 공고입니다. 지원 자격은 공고문을 확인 부탁드립니다."),
    ("pm@tips.or.kr", "TIPS 프로그램 신규 운영사 모집을 공고합니다. 신청 절차는 누리집을 참고해 주십시오."),
    ("edu@daegu.go.kr", "청년창업 지원사업 수행기관 모집 공고를 게시하였습니다. 관심 기관의 많은 참여 바랍니다."),
    ("rlinc22@knu.ac.kr", "대학-지역기업 기술협업 프로젝트 참여기업 2차 모집 공고입니다. 많은 참여 부탁드립니다."),
    ("fund@kised.or.kr", "글로벌 진출 지원 프로그램 참가팀을 모집합니다. 모집 분야는 첨부를 확인 바랍니다."),
    ("host@founders.kr", "창업 멘토 풀 등록 안내입니다. 등록을 희망하시면 양식을 제출 부탁드립니다."),
    ("contact@kban.or.kr", "전문개인투자자 양성 교육과정 수강생을 모집합니다. 모집 인원 한정이오니 참고 바랍니다."),
    ("biz@dgmf.or.kr", "제조창업 실증지원 사업 참여기업을 공모합니다. 세부 내용은 공고문을 확인해 주세요."),
    ("manager@incubator.kr", "창업보육센터 입주기업 모집 공고를 안내드립니다. 입주 자격을 확인 부탁드립니다."),
    ("info@startupbiz.kr", "스타트업 IR 피칭 참가팀 모집 안내입니다. 참가 신청은 누리집에서 가능합니다."),
    ("pr@ccei.kr", "메이커 스페이스 이용자 모집 공고입니다. 이용 안내는 첨부를 참고 바랍니다."),
    ("support@kised.or.kr", "사회적기업 육성사업 참여기관 공모를 안내드립니다. 많은 관심 바랍니다."),
    # ── N2 자료송부/회람 (확인·회신 요청) ─────────────────────────────
    ("khmoon@koef.or.kr", "프리토타입 강의안 및 실습양식을 회람드리니 확인 부탁드립니다."),
    ("support@kised.or.kr", "멘토링 운영 가이드라인을 송부드립니다. 첨부파일 참고 부탁드립니다."),
    ("office@knu.ac.kr", "협약서 양식과 제출 서류 목록을 첨부합니다. 검토 후 회신 부탁드립니다."),
    ("admin@ccei.kr", "사업 운영 매뉴얼 개정본을 공유드립니다. 변경 사항을 확인해 주시기 바랍니다."),
    ("secretary@academy.or.kr", "멘토 활동비 정산 양식을 첨부하오니 작성하여 회신 부탁드립니다."),
    ("edu@daegu.go.kr", "사업 공고문과 신청 양식을 안내드립니다. 자세한 일정은 추후 안내드리겠습니다."),
    ("pm@tips.or.kr", "협약 관련 제출 서류를 안내드립니다. 누락 없이 준비 부탁드립니다."),
    ("jyjeon@koef.or.kr", "분과별 운영계획서 양식을 송부드립니다. 작성 후 회신 부탁드립니다."),
    ("fund@kised.or.kr", "사업비 집행 지침을 첨부하오니 숙지 부탁드립니다."),
    ("host@founders.kr", "발표자료 템플릿을 공유드립니다. 해당 양식으로 준비 바랍니다."),
    ("biz@dgmf.or.kr", "안전관리 매뉴얼을 회람드립니다. 입주사 공유 부탁드립니다."),
    ("office@knu.ac.kr", "연구윤리 교육자료를 전달드리니 참고 부탁드립니다."),
    # ── N3 지난행사 후기/자료공유 (이미 종료) ─────────────────────────
    ("onestop@kised.or.kr", "금일 개최된 전문가 설명회에 참석해 주신 분들께 감사드리며, 설명회 자료를 공유드립니다."),
    ("admin@ccei.kr", "지난 출범식 사진과 행사 후기를 공유드립니다. 함께해 주셔서 감사합니다."),
    ("office@knu.ac.kr", "어제 진행된 간담회 회의록을 공유드리니 참고 부탁드립니다."),
    ("pm@tips.or.kr", "지난주 데모데이에 참여해 주셔서 감사합니다. 발표 자료를 첨부합니다."),
    ("secretary@academy.or.kr", "멘토 워크숍이 성황리에 마무리되었습니다. 현장 스케치를 전달드립니다."),
    ("freedaegu@naver.com", "1기 오리엔테이션에 참석해 주신 멘토님들께 감사드립니다. 사진을 공유드립니다."),
    ("edu@daegu.go.kr", "창업 박람회가 종료되었습니다. 참가 기업 명단과 결과를 공유드립니다."),
    ("host@founders.kr", "파운더스포럼 영상 다시보기 링크를 안내드립니다."),
    ("contact@kban.or.kr", "투자설명회 종료 후 Q&A 정리본을 전달드립니다."),
    ("info@startupbiz.kr", "데모데이 현장 피드백을 정리하여 공유드립니다. 감사합니다."),
    # ── N4 일정확인/가능시간 요청 (확정 안 됨) ────────────────────────
    ("jyjeon@koef.or.kr", "IT+출연(연) 분과 일정 확인 부탁드립니다. 첨부파일을 확인 부탁드립니다."),
    ("support@kised.or.kr", "하반기 멘토링 가능 일자를 회신해 주시면 조율하겠습니다."),
    ("admin@ccei.kr", "멘토님 가능 시간대를 알려주시면 일정을 확정하겠습니다."),
    ("office@knu.ac.kr", "협약식 일정은 참석자 일정 취합 후 별도 공지하겠습니다."),
    ("pm@tips.or.kr", "착수 미팅 가능하신 요일을 알려주시기 바랍니다."),
    ("secretary@academy.or.kr", "간담회 희망 일시를 설문으로 받고 있습니다. 응답 부탁드립니다."),
    ("khmoon@koef.or.kr", "강의 가능 시간대를 회신 주시면 시간표를 편성하겠습니다."),
    ("host@founders.kr", "멘토 일정 조사 중입니다. 가능하신 주간을 알려주세요."),
    ("manager@incubator.kr", "입주사 면담 가능 시간을 취합 중입니다. 회신 부탁드립니다."),
    # ── N5 추후안내/미확정 ────────────────────────────────────────────
    ("support@kised.or.kr", "멘토비 지급 기준은 추후 별도 안내 예정입니다. 확정 시 다시 전달드리겠습니다."),
    ("edu@daegu.go.kr", "세부 일정은 확정되는 대로 다시 안내드리겠습니다."),
    ("pm@tips.or.kr", "착수보고회 일정은 협약 완료 후 별도 조율 예정입니다."),
    ("admin@ccei.kr", "다음 라운드 일정은 추후 공지 예정이니 참고 부탁드립니다."),
    ("secretary@academy.or.kr", "간담회 일시는 장소 섭외 후 재안내드리겠습니다."),
    ("office@knu.ac.kr", "협약식 장소와 시간은 추후 개별 안내드릴 예정입니다."),
    ("fund@kised.or.kr", "정산 마감일은 변경될 수 있으며 확정 시 공지하겠습니다."),
    ("host@founders.kr", "포럼 후속 일정은 미정이며 결정되면 알려드리겠습니다."),
    ("contact@kban.or.kr", "교육 개강일은 모집 마감 후 안내 예정입니다."),
    # ── N6 정산/서류/행정 요청 ────────────────────────────────────────
    ("fund@kised.or.kr", "사업비 집행 정산 서류를 안내드립니다. 기한 내 제출 부탁드립니다."),
    ("office@knu.ac.kr", "연구비 카드 사용 내역서를 작성하여 회신 부탁드립니다."),
    ("secretary@academy.or.kr", "멘토 위촉 동의서를 첨부하오니 서명 후 회신 부탁드립니다."),
    ("admin@ccei.kr", "참여 기업 현황 조사표를 작성해 주시기 바랍니다."),
    ("edu@daegu.go.kr", "사업자등록증 사본을 제출해 주시기 바랍니다."),
    ("pm@tips.or.kr", "통장 사본과 신분증을 제출 부탁드립니다."),
    ("manager@incubator.kr", "입주 계약 갱신 서류를 준비해 주시기 바랍니다."),
    ("jyjeon@koef.or.kr", "강사료 지급을 위한 인적사항을 회신 부탁드립니다."),
    ("biz@dgmf.or.kr", "안전점검 체크리스트를 작성하여 제출 바랍니다."),
    # ── N7 결과발표/선정/뉴스레터 ─────────────────────────────────────
    ("support@kised.or.kr", "예비창업패키지 선정 결과를 안내드립니다. 자세한 내용은 첨부 참고 바랍니다."),
    ("admin@ccei.kr", "액셀러레이팅 프로그램 서류 평가 결과를 통보드립니다."),
    ("pm@tips.or.kr", "추천위원회 심의 결과를 공유드립니다."),
    ("office@knu.ac.kr", "공모전 수상자 명단을 게시하였습니다. 축하드립니다."),
    ("onestop@kised.or.kr", "창업진흥원 뉴스레터를 보내드립니다. 주요 소식을 확인해 보세요."),
    ("admin@ccei.kr", "멘토링 만족도 설문에 참여 부탁드립니다. 응답은 익명으로 처리됩니다."),
    ("edu@daegu.go.kr", "대구시 창업 소식지 가을호를 전달드립니다."),
    ("secretary@academy.or.kr", "멘토 역량강화 콘텐츠를 공유드립니다. 이번 호 주제는 피드백 기법입니다."),
    ("contact@kban.or.kr", "엔젤투자허브 월간 소식을 안내드립니다. 많은 관심 바랍니다."),
]


def neg_rows(records, prefix):
    out = []
    for i, (sender, msg) in enumerate(records):
        out.append({"scenario_id": f"{prefix}_{i:03d}",
                    "received_at": f"{RECV_BASE}T{8 + (i % 12):02d}:{(i * 11) % 60:02d}:00+09:00",
                    "channel": "gmail", "sender": sender, "language": "ko",
                    "message": msg, "gold": {"has_schedule": False, "events": []}})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    rows = neg_rows(GOV_NEG, "g21_govneg")
    print(f"  G(격식 기관메일 음성)  {len(rows):3}건  (전부 has_schedule:false)")
    if args.apply:
        p = "data/processed/r21_hardcases.jsonl"
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"→ {p}")
    else:
        print("(미리보기 — --apply 로 기록)")


if __name__ == "__main__":
    main()
