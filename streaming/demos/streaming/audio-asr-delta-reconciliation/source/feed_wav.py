"""マイクの代わりに wav を WebSocket へ流し込む (切り分け用).

デモサーバと同じ経路 (WS -> バッファ -> vLLM) を、既知の音声で通す。
モデルもサーバコードも同一で、変わるのは音声だけ。これで
「モデル/サーバが悪いのか、マイク音声が悪いのか」が決まる。

localhost に繋ぐので、電話音声(PII)は public proxy に出ない。
"""
import argparse, asyncio, json, sys
import librosa, numpy as np
import websockets

SR = 16000


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://localhost:8080/ws")
    ap.add_argument("--wav", required=True)
    ap.add_argument("--limit", type=float, default=60.0, help="何秒ぶん流すか")
    ap.add_argument("--realtime", action="store_true",
                    help="実時間で流す (既定は即送りして待つ=速い)")
    args = ap.parse_args()

    wav, _ = librosa.load(args.wav, sr=SR, mono=True)
    wav = wav[: int(args.limit * SR)].astype(np.float32)
    print(f"[feed] {args.wav}  {len(wav)/SR:.1f}s  -> {args.url}", flush=True)

    async with websockets.connect(args.url, max_size=None) as ws:
        async def reader():
            async for m in ws:
                d = json.loads(m)
                if d["type"] == "update":
                    print(f"\n[{d['audio_sec']:6.1f}s] {d['latency']}s "
                          f"prompt={d['n_prompt']} gen={d['n_gen']} ({d['finish']})", flush=True)
                    print(f"  {d['confirmed']}", flush=True)
                elif d["type"] == "error":
                    print(f"  ERROR: {d['msg']}", flush=True)

        task = asyncio.create_task(reader())
        # ブラウザの ScriptProcessor と同じ 4096 サンプル単位で送る
        step = 4096
        for i in range(0, len(wav), step):
            await ws.send(wav[i:i + step].tobytes())
            if args.realtime:
                await asyncio.sleep(step / SR)
            else:
                await asyncio.sleep(0.001)   # サーバに処理させる隙を作る
        print("\n[feed] 送信完了。推論の完了を待機...", flush=True)
        await asyncio.sleep(25)
        task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
