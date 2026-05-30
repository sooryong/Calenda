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


def date_hints(received_at: str) -> str:
    """수신시각 날짜 기준 오늘/내일/모레/글피의 절대일자를 미리 계산해 한 줄로.
    0.5B가 요일→날짜 산술(특히 주말 횡단)을 못 맞히는 문제를, '계산은 호스트가 하고
    모델은 복사만' 하게 만들어 구조적으로 해결. 계산 불가 시 빈 문자열(힌트 생략)."""
    from datetime import datetime, timedelta

    s = received_at.isoformat() if hasattr(received_at, "isoformat") else str(received_at)
    try:
        base = datetime.fromisoformat(s).date()
    except Exception:
        return ""
    parts = []
    for name, off in (("오늘", 0), ("내일", 1), ("모레", 2), ("글피", 3)):
        d = base + timedelta(days=off)
        parts.append(f"{name}={d.isoformat()}({WEEKDAYS_KO[d.weekday()]})")
    return "<날짜힌트: " + ", ".join(parts) + ">"


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
    ]
    hint = date_hints(record["received_at"])
    if hint:
        parts.append(hint)
    parts.append(f"<발신자: {record.get('sender', '')}>")
    thread = record.get("thread_context") or []
    if thread:
        lines = "\n".join(
            f"[{t.get('time', '')}] {t.get('sender', '')}: {t.get('message', '')}" for t in thread
        )
        parts.append(f"<대화내역>\n{lines}\n</대화내역>")
    parts.append(f"<메시지>\n{record['message']}\n</메시지>")
    return "\n".join(parts)


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
