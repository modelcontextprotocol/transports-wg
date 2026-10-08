"""Qwen3-Omni リアルタイム文字起こしデモ (ステップ1: streaming 表示なし).

方式: 5秒ごとに「0秒目から現在までの全音声」+「確定テキストを assistant prefix」で再推論し、
      続きだけを生成させる。推論中に次の更新時刻が来たらスキップし、常に最新音声だけを処理する。

  ブラウザ(マイク) --WS--> 音声バッファ --5秒ごと--> vLLM --WS--> 画面

注意: このサーバは runpod の public proxy に出る。認証は無い。顧客音声は流さないこと。
"""
import asyncio, json, os, re, time
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from vllm import AsyncEngineArgs, SamplingParams
from vllm.v1.engine.async_llm import AsyncLLM

SR = 16000
MODEL = os.environ.get("MODEL", "/root/qwen_int8")
INTERVAL = float(os.environ.get("INTERVAL", "3.0"))
START_AFTER_SEC = float(os.environ.get("START_AFTER_SEC", "3.0"))
MAX_NEW_TOKENS = int(os.environ.get("MAX_NEW_TOKENS", "128"))
USE_PREFIX = os.environ.get("USE_PREFIX", "1") == "1"
WINDOW_SEC = float(os.environ.get("WINDOW_SEC", "30.0"))
# 直近 PREFIX_LAG_SEC 秒ぶんは「確定 (history) にせず pending として毎回まるごと
# 再推論」させる = 前回間違えても後続 round で復帰できる。PREFIX_LAG_SEC 秒経過する
# 度に pending を history へ確定 (graduate) して、次の pending 期間を始める。
PREFIX_LAG_SEC = float(os.environ.get("PREFIX_LAG_SEC", "6.0"))

SP = ("あなたは日本語の音声書き起こしアシスタントです。"
      "以下の音声を書き起こしてください。話者交代 [spk_0][spk_1][spk_2] タグ。前置きなし。<think> 禁止。")

_SPK_TAG_RE = re.compile(r'\[spk_\d\]')


def _last_spk_tag(text: str) -> str | None:
    """text 内で最後に現れる [spk_N] タグを返す。無ければ None."""
    m = _SPK_TAG_RE.findall(text)
    return m[-1] if m else None

app = FastAPI()
llm: AsyncLLM | None = None
HERE = os.path.dirname(os.path.abspath(__file__))


def build_prompt(prefix: str) -> str:
    """assistant ターンを閉じずに確定テキストを置く = continuation。
    chat template を通さない生プロンプトなので EOS は入らない。"""
    return (f"<|im_start|>system\n{SP}<|im_end|>\n"
            "<|im_start|>user\n<|audio_start|><|audio_pad|><|audio_end|>"
            "<|im_end|>\n<|im_start|>assistant\n" + prefix)


def remove_overlap(prefix: str, generated: str) -> tuple[str, int]:
    """prefix 末尾と generated 先頭の最長一致を削る。"""
    n = min(len(prefix), len(generated))
    for length in range(n, 0, -1):
        if prefix[-length:] == generated[:length]:
            return generated[length:], length
    return generated, 0


async def infer_streaming(audio: np.ndarray, prefix: str):
    """AsyncLLM を叩いて (delta_text, RequestOutput) を yield する async generator.
    delta_text は前回 yield からの差分。呼び出し側は毎回そのまま UI に流せる。"""
    n_tok = MAX_NEW_TOKENS if USE_PREFIX else 512
    samp = SamplingParams(temperature=0.0, max_tokens=n_tok)
    req_id = f"req-{time.time_ns()}"
    prompt = {"prompt": build_prompt(prefix),
              "multi_modal_data": {"audio": (audio, SR)}}
    prev_len = 0
    async for out in llm.generate(prompt=prompt, sampling_params=samp, request_id=req_id):
        text = out.outputs[0].text
        delta = text[prev_len:]
        prev_len = len(text)
        yield delta, out


@app.on_event("startup")
def _load():
    global llm
    print(f"[startup] loading {MODEL} ...", flush=True)
    args = AsyncEngineArgs(model=MODEL, max_model_len=65536, max_num_seqs=1,
                           limit_mm_per_prompt={"audio": 1}, seed=0,
                           gpu_memory_utilization=0.85)
    llm = AsyncLLM.from_engine_args(args)
    print("[startup] ready", flush=True)


@app.get("/")
def index():
    return HTMLResponse(open(os.path.join(HERE, "index.html"), encoding="utf-8").read())


@app.get("/health")
def health():
    return {"ready": llm is not None, "interval": INTERVAL, "model": MODEL,
            "start_after": START_AFTER_SEC, "use_prefix": USE_PREFIX}


# 届いたマイク音声をそのまま保存する。推測せず実物を聞く / 同じ音声で条件だけ変えて
# 再実験する (話者分離が音響を見ているのか言語だけなのか等) ために要る。
LAST_WAV = os.path.join(HERE, "mic_last.wav")


def save_wav(audio: np.ndarray):
    import soundfile as sf
    sf.write(LAST_WAV, audio, SR)


@app.get("/mic_last.wav")
def mic_last():
    """サーバが実際に受け取った音声をそのまま返す。
    モデルに何が届いているのかを、推測せず自分の耳で確かめるための口。"""
    from fastapi.responses import FileResponse, JSONResponse
    if not os.path.exists(LAST_WAV):
        return JSONResponse({"error": "まだ録音がありません"}, status_code=404)
    return FileResponse(LAST_WAV, media_type="audio/wav",
                        headers={"Cache-Control": "no-store"})


@app.get("/mic_info")
def mic_info():
    """届いた音声の素性 (長さ・音量・クリップ) を数値で見る。"""
    import soundfile as sf
    if not os.path.exists(LAST_WAV):
        return {"exists": False}
    a, sr = sf.read(LAST_WAV, dtype="float32")
    peak = float(np.abs(a).max()) if len(a) else 0.0
    return {"exists": True, "sec": round(len(a) / sr, 2), "sr": sr,
            "rms": round(float(np.sqrt((a ** 2).mean())) if len(a) else 0.0, 5),
            "peak": round(peak, 4),
            # 1.0 に張り付いていたら入力段で歪んでいる (音割れ)
            "clipped_pct": round(float((np.abs(a) > 0.99).mean() * 100), 3) if len(a) else 0.0}


@app.websocket("/ws")
async def ws(sock: WebSocket):
    await sock.accept()
    chunks: list[np.ndarray] = []      # 録音開始からの全音声 (メモリは growing)
    # history: (確定した時点の音声長 秒, 確定テキスト)。永久に確定 (graduate) 済み。
    # UI 表示用にも trim しない。model への prefix は毎回窓内だけ抽出する。
    history: list[tuple[float, str]] = []
    pending_text = ""                  # 直近 PREFIX_LAG_SEC 秒ぶんの未確定分。毎回まるごと再生成。
    last_graduate_sec = 0.0            # 最後に history へ確定させた時点の音声長(秒)
    busy = False                       # 推論中フラグ (同時に走らせない)
    n_samples = 0                      # 受信済みサンプル数 (= 音声の長さ, 単調増加)
    # 【壁時計で駆動しない】WebSocket 接続はページ読込時、録音開始はその後なので、
    # 接続時刻を基準にすると「録音開始した瞬間に 0.1 秒の音声で推論」してしまう。
    # 音声の長さで駆動すれば、このズレが原理的に消える。
    last_infer_sec = 0.0               # 前回推論した時点の音声長(秒)
    n_skipped = 0

    async def run_inference():
        nonlocal busy, n_skipped, pending_text, last_graduate_sec
        busy = True
        try:
            audio_full = np.concatenate(chunks) if chunks else np.zeros(0, np.float32)
            secs = len(audio_full) / SR

            # 音声は直近 WINDOW_SEC。prefix text は history (確定済み) から
            # 「30秒より古い分」を除いたもの。直近 PREFIX_LAG_SEC 秒 (pending) は
            # prefix に含めず、毎回まるごと再推論させる。
            if secs > WINDOW_SEC:
                audio = audio_full[-int(WINDOW_SEC * SR):]
            else:
                audio = audio_full
            cutoff_old = max(0.0, secs - WINDOW_SEC)
            sent_sec = len(audio) / SR
            prefix_kept = "".join(nt for t, nt in history if t > cutoff_old) if USE_PREFIX else ""
            # 窓で頭が切れて spk タグが失われると model が話者を見失う。
            # 落とされた履歴 (30秒より前) から「窓の直前で active だった」spk タグを補う。
            # 補うのは model への入力だけで、history には保存しない
            # (model が実際に emit したものではないので)。
            prepended = ""
            if USE_PREFIX and prefix_kept and not _SPK_TAG_RE.match(prefix_kept):
                dropped_old = "".join(nt for t, nt in history if t <= cutoff_old)
                tag = _last_spk_tag(dropped_old)
                if tag:
                    prepended = tag
            prefix = prepended + prefix_kept

            await asyncio.to_thread(save_wav, audio)   # 実物を後から検証できるように
            await sock.send_json({"type": "status", "state": "infer",
                                  "audio_sec": round(secs, 1),
                                  "sent_sec": round(sent_sec, 1)})

            # streaming: token 1個ずつだとブラウザのメインスレッドが飽和して
            # マイクの audio callback が飢餓 → 音声欠損する。50ms 単位で batch 送信。
            t0 = time.time()
            raw = ""
            last_out = None
            buf = ""
            last_send = t0
            FLUSH_SEC = 0.05
            async for delta, out in infer_streaming(audio, prefix):
                last_out = out
                raw = out.outputs[0].text
                buf += delta
                now = time.time()
                if buf and now - last_send >= FLUSH_SEC:
                    await sock.send_json({"type": "delta", "delta": buf,
                                          "audio_sec": round(secs, 1),
                                          "n_gen": len(out.outputs[0].token_ids)})
                    buf = ""
                    last_send = now
            if buf and last_out is not None:            # 最後の残りを flush
                await sock.send_json({"type": "delta", "delta": buf,
                                      "audio_sec": round(secs, 1),
                                      "n_gen": len(last_out.outputs[0].token_ids)})
            dt = time.time() - t0
            n_prompt = len(last_out.prompt_token_ids) if last_out and last_out.prompt_token_ids else 0
            n_gen = len(last_out.outputs[0].token_ids) if last_out else 0
            finish = last_out.outputs[0].finish_reason if last_out else None

            # 生成完了。overlap 除去。new は「history の続き 〜 現在」の全文 (pending 含む)。
            # 最後に確定してから PREFIX_LAG_SEC 秒経っていれば history へ確定 (graduate) し、
            # 次の pending 期間を開始する。経っていなければ pending を丸ごと差し替えるだけ
            # (前回の pending は捨てて、今回の再推論結果で上書き = 復帰の機会)。
            if USE_PREFIX:
                new, overlap = remove_overlap(prefix, raw)
                if secs - last_graduate_sec >= PREFIX_LAG_SEC:
                    history.append((secs, new))
                    last_graduate_sec = secs
                    pending_text = ""
                else:
                    pending_text = new
                confirmed_now = "".join(nt for _, nt in history) + pending_text
            else:
                new, overlap = raw, 0
                confirmed_now = raw

            await sock.send_json({
                "type": "update", "new": new, "confirmed": confirmed_now,
                "audio_sec": round(secs, 1), "sent_sec": round(sent_sec, 1),
                "latency": round(dt, 2),
                "n_prompt": n_prompt, "n_gen": n_gen,
                "finish": finish, "overlap": overlap,
                "raw": raw, "skipped": n_skipped,
            })
            print(f"[{secs:6.1f}s sent={sent_sec:4.1f}s] {dt:5.2f}s "
                  f"prompt={n_prompt:5d} gen={n_gen:3d} "
                  f"ov={overlap:2d} hist={len(history):2d} "
                  f"prep={prepended or '-'} +{new[:40]!r}", flush=True)
        except Exception as e:
            import traceback; traceback.print_exc()
            await sock.send_json({"type": "error", "msg": f"{type(e).__name__}: {e}"})
        finally:
            busy = False

    try:
        while True:
            data = await sock.receive()
            if "bytes" in data and data["bytes"]:
                a = np.frombuffer(data["bytes"], dtype=np.float32)
                chunks.append(a)
                n_samples += len(a)
            elif "text" in data and data["text"]:
                msg = json.loads(data["text"])
                if msg.get("cmd") == "reset":
                    chunks.clear(); history.clear()
                    pending_text = ""; last_graduate_sec = 0.0
                    n_samples = 0; last_infer_sec = 0.0; n_skipped = 0
                    await sock.send_json({"type": "reset"})
                    continue
                if msg.get("cmd") == "stop":
                    break

            sec = n_samples / SR
            # 最初は START_AFTER_SEC まで貯める。以降は音声が INTERVAL 秒ぶん増えたら回す。
            due = (sec >= START_AFTER_SEC) and (sec - last_infer_sec >= INTERVAL
                                                or last_infer_sec == 0.0)
            if due:
                if busy:
                    # 更新要求を積むと遅延が増え続けるので、常に最新だけを処理する
                    n_skipped += 1
                else:
                    last_infer_sec = sec
                    asyncio.create_task(run_inference())
    except WebSocketDisconnect:
        pass
    except Exception:
        import traceback; traceback.print_exc()
