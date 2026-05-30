"""공통 유틸 — 프롬프트 로딩, Anthropic 호출, JSONL I/O."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Iterable, Iterator

import orjson
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

ROOT = Path(__file__).resolve().parents[1]

load_dotenv(ROOT / ".env", override=True)


def load_prompt(name: str) -> str:
    """prompts/{name}.md 전체 텍스트 반환."""
    path = ROOT / "prompts" / f"{name}.md"
    return path.read_text(encoding="utf-8")


WEEKDAYS_KO = ["월", "화", "수", "목", "금", "토", "일"]


def with_weekday(received_at: str) -> str:
    """수신시각 ISO에 한국어 요일 부착. 예: '...+09:00' → '...+09:00 (금)'.
    학습·평가·앱 프롬프트가 반드시 동일 형식이어야 함 (Android ScheduleExtractor와 일치)."""
    from datetime import datetime

    s = received_at.isoformat() if hasattr(received_at, "isoformat") else str(received_at)
    try:
        return f"{s} ({WEEKDAYS_KO[datetime.fromisoformat(s).weekday()]})"
    except Exception:
        return s


def build_user_block(record: dict) -> str:
    """학습/추론 공용 user 메시지 빌더.

    단일 메시지: 기존 <채널>/<수신시각>/<발신자>/<메시지> 4블록.
    멀티턴: record['thread_context']가 있으면 <발신자>와 <메시지> 사이에
            <대화내역> 블록(이전 대화)을 삽입한다. 없으면 생략 → 하위호환.
    thread_context 원소 형식: {"time": "HH:MM", "sender": "...", "message": "..."}.
    ★ train_lora / eval_model / (추후 Android)가 전부 이 함수와 동일 포맷이어야 한다."""
    parts = [
        f"<채널: {record['channel']}>",
        f"<수신시각: {with_weekday(record['received_at'])}>",
        f"<발신자: {record.get('sender', '')}>",
    ]
    thread = record.get("thread_context") or []
    if thread:
        lines = "\n".join(
            f"[{t.get('time', '')}] {t.get('sender', '')}: {t.get('message', '')}" for t in thread
        )
        parts.append(f"<대화내역>\n{lines}\n</대화내역>")
    parts.append(f"<메시지>\n{record['message']}\n</메시지>")
    return "\n".join(parts)


import calendar as _calendar
import re as _re
from datetime import date as _date, datetime as _datetime, timedelta as _timedelta

_WD_KO = "월화수목금토일"


def _add_months(d: _date, n: int) -> _date:
    y = d.year + (d.month - 1 + n) // 12
    mo = (d.month - 1 + n) % 12 + 1
    return _date(y, mo, min(d.day, _calendar.monthrange(y, mo)[1]))


_DATE_ALIAS = {
    "today": "오늘", "tomorrow": "내일", "day after tomorrow": "모레", "overmorrow": "모레",
    "next week": "다음주", "this weekend": "이번주말", "next weekend": "다음주말",
}


def resolve_date(received_date: _date, token: str | None) -> _date | None:
    """date 토큰 → 절대 date (received 기준). 인식 못 하면 None. schema.md 어휘표와 1:1.
    방어: 모델이 가끔 내는 영어(today/next week 등)는 한국어 토큰으로 정규화, 공백은 허용."""
    if not token:
        return None
    token = str(token).strip()
    token = _DATE_ALIAS.get(token.lower(), token).replace(" ", "")
    fixed = {"오늘": 0, "내일": 1, "모레": 2, "글피": 3}
    if token in fixed:
        return received_date + _timedelta(days=fixed[token])
    m = _re.match(r"^(\d+)일후$", token)
    if m:
        return received_date + _timedelta(days=int(m.group(1)))
    m = _re.match(r"^(\d+)주후$", token)
    if m:
        return received_date + _timedelta(days=7 * int(m.group(1)))
    m = _re.match(r"^(\d+)개월후$", token)
    if m:
        return _add_months(received_date, int(m.group(1)))
    m = _re.match(r"^(\d+)년후$", token)
    if m:
        return _add_months(received_date, 12 * int(m.group(1)))
    m = _re.match(r"^(다음주|다다음주)$", token)            # 요일 없는 다음주/다다음주 → 주 단위
    if m:
        return received_date + _timedelta(days=7 * {"다음주": 1, "다다음주": 2}[token])
    m = _re.match(r"^(이번주|다음주|다다음주)([월화수목금토일])$", token)
    if m:
        monday = received_date - _timedelta(days=received_date.weekday())
        monday += _timedelta(days=7 * {"이번주": 0, "다음주": 1, "다다음주": 2}[m.group(1)])
        return monday + _timedelta(days=_WD_KO.index(m.group(2)))
    if token in ("이번주말", "다음주말"):
        sat = received_date + _timedelta(days=(5 - received_date.weekday()) % 7)
        return sat + (_timedelta(days=7) if token == "다음주말" else _timedelta())
    if _re.match(r"^\d{4}-\d{2}-\d{2}$", token):
        try:
            return _date.fromisoformat(token)
        except Exception:
            return None
    return None


def resolve_time(time_obj: dict | None, received_dt: _datetime) -> str | None:
    """time {hour,minute,marker} → 'HH:MM'(24h). None이면 None. schema.md 변환표와 1:1.
    표시어 없는 1~12시는 받은 시각 이후 가장 가까운 쪽(AM/PM), 둘 다 과거면 오후."""
    if not time_obj:
        return None
    h = int(time_obj.get("hour", 0))
    m = int(time_obj.get("minute") or 0)
    k = time_obj.get("marker")
    if k in ("오후", "저녁", "밤", "낮"):
        if h < 12:
            h += 12
    elif k in ("오전", "아침", "새벽"):
        if h == 12:
            h = 0
    elif k == "정오":
        h, m = 12, 0
    elif k == "자정":
        h, m = 0, 0
    elif k is None and 1 <= h <= 12:
        am, pm = h % 12, h % 12 + 12
        rh = received_dt.hour + received_dt.minute / 60
        h = next((c for c in sorted((am, pm)) if c >= rh), pm)
    return f"{h:02d}:{m:02d}"


def resolve_when(received_at, date_token, time_obj, end_time_obj=None, all_day=False, tz="+09:00") -> dict:
    """모델의 date/time → 절대 start/end ISO. eval·앱 공용 단일 진실원.
    반환 {'start': ISO|None, 'end': ISO|None, 'all_day': bool}."""
    try:
        recv = received_at if hasattr(received_at, "date") else _datetime.fromisoformat(str(received_at))
    except Exception:
        return {"start": None, "end": None, "all_day": bool(all_day)}
    d = resolve_date(recv.date(), date_token)
    # 규칙7: 날짜가 '진짜 없을' 때만(빈/None) 시간만 → 오늘.
    # date가 있었지만 인식 못 한 토큰이면 오늘로 단정하지 않음(잘못된 today 방지).
    if d is None and time_obj and not (date_token and str(date_token).strip()):
        d = recv.date()
    if d is None:
        return {"start": None, "end": None, "all_day": bool(all_day)}
    if all_day or not time_obj:
        return {"start": d.isoformat(), "end": None, "all_day": bool(all_day)}
    start = f"{d.isoformat()}T{resolve_time(time_obj, recv)}:00{tz}"
    end = f"{d.isoformat()}T{resolve_time(end_time_obj, recv)}:00{tz}" if end_time_obj else None
    return {"start": start, "end": end, "all_day": False}


def _gwa(word: str) -> str:
    """받침 유무에 따라 '와/과'."""
    ch = word[-1] if word else ""
    if "가" <= ch <= "힣":
        return "과" if (ord(ch) - 0xAC00) % 28 else "와"
    return "와"


def compose_title(base_title, attendees=None, organizer=None, sender=None, channel=None) -> str:
    """캘린더 표시 제목 조합. 모델은 활동(base_title)만 뽑고, 누구와·출처(소속)는 앱이 붙인다.
      누구와: '{참석자}와/과 {활동}'
      출처:   ' · {발신자}'  (소속 있으면 ' · {발신자} ({소속})', 기관 발신이면 ' · {기관}')
    예: 저녁식사+[민지] → '민지와 저녁식사';  주간 회의+발신 박과장 → '주간 회의 · 박과장';
        Kickoff+발신 Sarah Lee/소속 Company → 'Kickoff · Sarah Lee (Company)';  진료+기관 서울내과 → '진료 · 서울내과'."""
    title = (base_title or "일정").strip()
    who = [a for a in (attendees or []) if a and a not in title]
    if who:
        joined = ", ".join(who)
        title = f"{joined}{_gwa(joined)} {title}"

    src = None
    if sender and sender not in ("나", "Me", "me"):
        s = sender.replace("[Web발신]", "").strip()         # SMS 웹발신 접두 정리
        if organizer and organizer not in s:
            src = f"{s} ({organizer})"                      # 외부 개인 + 소속
        elif organizer:
            src = organizer                                # 기관 발신(발신자=소속)
        else:
            src = s
    elif organizer:
        src = organizer
    if src and src not in title:
        title = f"{title} · {src}"
    return title


def resolve_event(received_at, sender, event: dict, channel=None) -> dict:
    """모델 이벤트(date/time 토큰) → 캘린더용 완성 이벤트.
    시각은 resolve_when으로 절대화, location/attendees/organizer/description/recurrence는 그대로 통과,
    제목은 compose_title로 조합. ★ location 등 어떤 필드도 누락 없이 캐리."""
    when = resolve_when(
        received_at, event.get("date"), event.get("time"),
        event.get("end_time"), event.get("all_day", False),
    )
    return {
        "title": compose_title(event.get("title"), event.get("attendees"),
                               event.get("organizer"), sender, channel),
        "start": when["start"],
        "end": when["end"],
        "all_day": when["all_day"],
        "location": event.get("location"),                 # ← 장소 보존 (필수 표시)
        "attendees": event.get("attendees", []),
        "organizer": event.get("organizer"),
        "description": event.get("description"),
        "recurrence": event.get("recurrence"),
        "confidence": event.get("confidence"),
    }


def read_jsonl(path: str | Path) -> Iterator[dict[str, Any]]:
    with open(path, "rb") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield orjson.loads(line)


def write_jsonl(path: str | Path, rows: Iterable[dict[str, Any]]) -> int:
    n = 0
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        for row in rows:
            f.write(orjson.dumps(row))
            f.write(b"\n")
            n += 1
    return n


def get_anthropic_client():
    """anthropic.Anthropic 클라이언트 반환. import는 lazy."""
    from anthropic import Anthropic

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY가 .env에 없습니다.")
    return Anthropic(api_key=key)


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=30))
def call_claude(
    system: str,
    user: str,
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 4096,
    temperature: float = 0.7,
) -> str:
    """Anthropic Messages API 단일 호출. 텍스트 반환."""
    client = get_anthropic_client()
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    # 첫 번째 텍스트 블록만 사용
    parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    return "".join(parts).strip()


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json_block(text: str) -> str:
    """모델 출력에서 JSON만 추출. 코드펜스 제거.

    여러 개의 ``` 코드펜스 블록이 섞여 있으면 마지막 블록을 사용한다
    (모델이 reasoning 후 재진술하는 케이스 — 최종 답안은 마지막 블록).
    """
    t = text.strip()
    blocks = _FENCE_RE.findall(t)
    if blocks:
        return blocks[-1].strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t


def safe_json_loads(text: str) -> Any | None:
    try:
        return orjson.loads(extract_json_block(text))
    except Exception:
        try:
            return json.loads(extract_json_block(text))
        except Exception:
            return None
