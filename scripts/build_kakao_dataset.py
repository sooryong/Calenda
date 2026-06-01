"""실제 카톡 캡처(docs/카톡N.png) → 학습/평가 데이터셋 빌더.

멀티턴 합의는 thread_context(직전 수신 메시지)에 담고, 최종 수신 메시지가 message.
앱은 '수신' 메시지만 보므로 내가 보낸 확정("좋습니다")은 thread에 없음 — 그래서
최종 ack("네")만으로 thread의 합의 시각을 추론하는 진짜 멀티턴 케이스.
출력: data/processed/kakao_real.jsonl(학습) + data/eval/kakao_real.jsonl(골든).
"""
import json


def pos(title, date, time=None, end_time=None, all_day=False, location=None,
        attendees=None, organizer=None, description=None, conf=0.85):
    return {"has_schedule": True, "events": [{
        "title": title, "date": date, "time": time, "end_time": end_time,
        "all_day": all_day, "location": location, "attendees": attendees or [],
        "organizer": organizer, "description": description, "recurrence": None,
        "confidence": conf}]}


NEG = {"has_schedule": False, "events": []}

# 각 레코드: dict(received_at, sender, message, gold, split[, thread])
ROWS = [
    # 카톡1 — 행사 안내(단일, 날짜+시각+장소)
    {"received_at": "2026-06-01T10:06:00+09:00", "sender": "모두의 창업 대구보건대학", "split": "train",
     "message": "추가로 안내드립니다. 대구창경에서 6월 2일(화) 오후 2시에 우리대학 3층 대회의실에서 행사를 진행 예정입니다. 참석하실 멘토 분들께서는 제게 개인톡을 주시면 참여 명단에 올려두겠습니다.",
     "gold": pos("멘토 회의", "2026-06-02", {"hour": 2, "minute": 0, "marker": "오후"}, location="대구보건대 3층 대회의실", organizer="대구보건대", conf=0.88)},
    # 카톡2 — 멀티턴 합의(정원구=참석자, 화상=온라인)
    {"received_at": "2026-05-22T21:57:00+09:00", "sender": "정원구 페테리안 초창26탈 경북대", "split": "golden",
     "thread": [{"time": "21:19", "sender": "정원구", "message": "멘토님 안녕하세요? 오늘 오전 갑작스레 응급동물환자가 와서 죄송했습니다. 다음주 월 혹은 목요일 오후 2시 중에 화상미팅 어떠신지 확인부탁드리겠습니다. 혹시 다른 시간대 혹은 저녁이라도 괜찮으신 때 알려주시면 맞추도록 하겠습니다."}],
     "message": "네 감사합니다. 월요일 오후 2시에 뵙겠습니다",
     "gold": pos("화상미팅", "다음주월", {"hour": 2, "minute": 0, "marker": "오후"}, location="온라인", attendees=["정원구"], conf=0.85)},
    # 카톡3(--false) — 남(김현철)의 강의, 그룹 논의
    {"received_at": "2026-06-01T18:15:00+09:00", "sender": "부트캠프자료정리방", "split": "golden",
     "message": "@김현철 아마존 중급 6/26(금) 13:00-18:00까지 5시간을 온라인이나 오프라인으로 강의하셔야 하는 상황입니다.",
     "gold": NEG},
    # 카톡4(--false) — 잡담
    {"received_at": "2026-05-29T18:46:00+09:00", "sender": "손일권전자86, 공성호 교수", "split": "train",
     "message": "난 상황 보구요", "gold": NEG},
    # 카톡5 — 멀티턴 합의(28일 10시 줌)
    {"received_at": "2026-05-27T10:04:00+09:00", "sender": "강건욱 다플기획 초창26탈 경북대", "split": "train",
     "thread": [
         {"time": "10:00", "sender": "강건욱", "message": "음..혹시 28일이랑 29일 오전중에는 괜찮으신지요? 두 날 오전 중 더 편하신 날 하루로 잡아주시면 적당할 것 같습니다."},
         {"time": "10:01", "sender": "강건욱", "message": "오전은 가능하시다는 전제이고, 불가능하시면 저는 다음주 월요일정도도 괜찮을 것 같습니다!"},
         {"time": "10:04", "sender": "강건욱", "message": "네 그럼 28일 10시가 더 괜찮습니다. 시간 비워두겠습니다"}],
     "message": "네, 감사합니다.",
     "gold": pos("줌 미팅", "2026-05-28", {"hour": 10, "minute": 0, "marker": "오전"}, location="온라인", attendees=["강건욱"], conf=0.85)},
    # 카톡6 — 마감(날짜+시각)
    {"received_at": "2026-05-24T12:00:00+09:00", "sender": "차정욱 모두의창업1 대구창경", "split": "train",
     "message": "마감이 5/27(수) 오후 6시라 일정이 촉박하니 빠른 확인 부탁드립니다. 징구서류 안내를 메일로 보내드렸습니다.",
     "gold": pos("징구서류 제출 마감", "2026-05-27", {"hour": 6, "minute": 0, "marker": "오후"}, conf=0.78)},
    # 카톡7 — 멀티턴 합의(6월4일 오전 9시, 최종 "네")
    {"received_at": "2026-06-01T10:39:00+09:00", "sender": "김용안 빈체레 초창26탈 경북대", "split": "golden",
     "thread": [
         {"time": "10:14", "sender": "김용안", "message": "6월4일 오전 9시 어떤지요?"},
         {"time": "10:35", "sender": "김용안", "message": "네 알겠습니다."}],
     "message": "네",
     "gold": pos("미팅", "2026-06-04", {"hour": 9, "minute": 0, "marker": "오전"}, attendees=["김용안"], conf=0.8)},
    # 카톡8a — FYI 공유(현지시간 실리콘밸리 포럼) → 음성
    {"received_at": "2026-06-01T09:25:00+09:00", "sender": "K-Scaleup Forum", "split": "train",
     "message": "6.27(현지시간) 실리콘밸리에서 저녁에 NEXUS 포럼이 진행됩니다. 대경권연합행사이고 바이오 기업이 많이 보여 공유해봅니다.",
     "gold": NEG},
    # 카톡8b — 미확정 → 음성
    {"received_at": "2026-06-01T12:37:00+09:00", "sender": "K-Scaleup Forum", "split": "golden",
     "message": "아마 7월 우리포럼은 미국에서 K-PAI와 함께 진행될수도 있을 것 같아요^^ (아직은 미확정인데 7월 예정소식 곧 공유드릴게요)",
     "gold": NEG},
]


def main():
    train, golden = [], []
    for i, r in enumerate(ROWS):
        rec = {"scenario_id": f"kakao_real_{i:03d}", "received_at": r["received_at"],
               "channel": "kakao", "sender": r["sender"], "language": "ko"}
        if "thread" in r:
            rec["thread_context"] = r["thread"]
        rec["message"] = r["message"]
        rec["gold"] = r["gold"]
        (golden if r["split"] == "golden" else train).append(rec)
    for path, rows in [("data/processed/kakao_real.jsonl", train), ("data/eval/kakao_real.jsonl", golden)]:
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        p = sum(1 for r in rows if r["gold"]["has_schedule"])
        print(f"{path}: {len(rows)}건 (일정 {p} / 음성 {len(rows) - p})")


if __name__ == "__main__":
    main()
