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
