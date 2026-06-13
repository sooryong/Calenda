"""양자화 GGUF를 골든셋으로 평가 (llama-cpp-python). eval_model.py와 **동일 채점**.

추론만 llama.cpp(GGUF)로 바꾸고 점수·집계는 eval_model.run_eval을 그대로 재사용하므로
FP16(eval_model.py) 결과와 같은 척도로 비교 가능 → 양자화 손실을 정량화한다.

사용:
    pip install llama-cpp-python
    python scripts/eval_gguf.py \
        --gguf models/gguf/r30-qwen3-0.6b/r30-qwen3-0.6b.Q4_K_M.gguf \
        --eval data/eval/golden.jsonl \
        --out logs/eval_r30-qwen3-0.6b.Q4_K_M.json

Qwen3는 non-thinking을 빈 <think></think> 블록으로 표현하므로(학습 분포와 일치),
프롬프트의 assistant 턴에 빈 think를 미리 채워 순수 JSON만 생성하게 한다.
Qwen2.5 등 non-thinking 베이스면 --no_think_prefill.
"""
from __future__ import annotations

import argparse

from _common import build_user_block, read_jsonl
from eval_model import run_eval  # 동일 채점·집계 단일 경로 재사용


def build_prompt(system: str, user_block: str, think_prefill: bool) -> str:
    """ChatML 프롬프트. eval_model의 apply_chat_template(add_generation_prompt=True,
    enable_thinking=False) 렌더와 동일한 표면형."""
    p = (
        "<|im_start|>system\n" + system + "<|im_end|>\n"
        "<|im_start|>user\n" + user_block + "<|im_end|>\n"
        "<|im_start|>assistant\n"
    )
    if think_prefill:
        p += "<think>\n\n</think>\n\n"
    return p


def make_infer(llm, system: str, think_prefill: bool, max_tokens: int = 512):
    def infer_fn(sample: dict) -> str:
        user_block = build_user_block(sample)  # thread_context 있으면 <대화내역> 자동 삽입
        prompt = build_prompt(system, user_block, think_prefill)
        out = llm(prompt, max_tokens=max_tokens, temperature=0.0,
                  stop=["<|im_end|>"], echo=False)
        return out["choices"][0]["text"].strip()
    return infer_fn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gguf", required=True)
    ap.add_argument("--eval", required=True)
    ap.add_argument("--out", default="logs/eval_gguf.json")
    ap.add_argument("--failures_out", default="data/failures/round_gguf.jsonl")
    ap.add_argument("--system_prompt", default=None,
                    help="없으면 configs/model_qwen3_0_6b.yaml 사용")
    ap.add_argument("--n_ctx", type=int, default=2048)
    ap.add_argument("--n_gpu_layers", type=int, default=0,
                    help="GPU면 -1(전부 오프로드), CPU면 0(기본)")
    ap.add_argument("--no_think_prefill", action="store_true",
                    help="Qwen2.5 등 non-thinking 베이스면 지정(기본은 Qwen3용 빈 think 프리필)")
    args = ap.parse_args()

    if args.system_prompt is None:
        import yaml
        with open("configs/model_qwen3_0_6b.yaml", "r", encoding="utf-8") as f:
            args.system_prompt = yaml.safe_load(f)["system_prompt"]

    from llama_cpp import Llama
    llm = Llama(model_path=args.gguf, n_ctx=args.n_ctx,
                n_gpu_layers=args.n_gpu_layers, verbose=False)

    samples = list(read_jsonl(args.eval))
    infer_fn = make_infer(llm, args.system_prompt, think_prefill=not args.no_think_prefill)
    run_eval(samples, infer_fn, out=args.out, failures_out=args.failures_out)


if __name__ == "__main__":
    main()
