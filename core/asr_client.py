"""vokie 本地转写服务客户端 (跨平台: 纯 HTTP)。

vokie 桌面应用的 Skills 服务暴露:
  GET  /v1/asr/health        健康检查
  POST /v1/asr/offline2pass  {inputPath, locale} -> {text}
端口发现: ~/.vokie/service.json 的 port 字段。
"""
import json
import os
import urllib.request



def _resolve_port() -> int | None:
    path = os.path.join(os.path.expanduser("~"), ".vokie", "service.json")
    try:
        with open(path, encoding="utf-8") as f:
            port = json.load(f).get("port")
        return int(port) if port else None
    except Exception:
        return None


def health(port=None) -> dict:
    port = port or _resolve_port()
    if not port:
        raise RuntimeError("vokie 服务未运行 (~/.vokie/service.json 不存在)")
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/asr/health", timeout=5) as r:
        return json.loads(r.read())


def transcribe(wav_path: str, locale: str = "zh", timeout: int = 120) -> str:
    """转写本地音频文件, 返回合并文本。空串 = 无有效语音。"""
    port = _resolve_port()
    if not port:
        raise RuntimeError("vokie 服务未运行 (需在 vokie 设置中开启 Skills)")
    body = json.dumps({
        "inputPath": os.path.abspath(wav_path),
        "locale": locale,
        "includeSegments": False,
    }).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/asr/offline2pass",
        method="POST", headers={"Content-Type": "application/json"}, data=body)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        res = json.loads(r.read())
    if not res.get("ok", True):
        raise RuntimeError(f"vokie 转写失败: {res.get('error', res)}")
    return res.get("text") or ""
