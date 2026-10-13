"""GPU：把微调后的 Qwen2.5-0.5B 导出为 ONNX 并 int8 量化（供 CPU/本地演示）。
用法：~/teacloud/envs/qa/bin/python export_onnx.py --src ~/teacloud/models/qa_d2t --out ~/teacloud/models/qa_d2t_onnx
"""
import argparse
import os

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.expanduser("~/teacloud/models/qa_d2t"))
    ap.add_argument("--out", default=os.path.expanduser("~/teacloud/models/qa_d2t_onnx"))
    a = ap.parse_args()
    from optimum.onnxruntime import ORTModelForCausalLM, ORTQuantizer
    from optimum.onnxruntime.configuration import AutoQuantizationConfig
    from transformers import AutoTokenizer

    import json as _json
    _cfg = os.path.join(a.src, "tokenizer_config.json")
    if os.path.exists(_cfg):
        _c = _json.load(open(_cfg, encoding="utf-8"))
        if isinstance(_c.get("extra_special_tokens"), list):
            _c["extra_special_tokens"] = {}
            _json.dump(_c, open(_cfg, "w", encoding="utf-8"), ensure_ascii=False)
    tok = AutoTokenizer.from_pretrained(a.src)
    model = ORTModelForCausalLM.from_pretrained(a.src, export=True, use_cache=True)
    model.save_pretrained(a.out)
    tok.save_pretrained(a.out)
    print("ONNX exported ->", a.out, flush=True)
    try:
        q = ORTQuantizer.from_pretrained(a.out, file_name="model.onnx")
        qc = AutoQuantizationConfig.avx512_vnni(is_static=False, per_channel=False)
        q.quantize(save_dir=a.out + "_int8", quantization_config=qc)
        print("int8 ->", a.out + "_int8", flush=True)
    except Exception as e:  # noqa: BLE001
        print("量化跳过:", e)


if __name__ == "__main__":
    main()
