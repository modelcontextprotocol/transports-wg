FROM vllm/vllm-openai:v0.25.1
RUN pip install --no-cache-dir transformers==5.14.1 qwen-omni-utils librosa soundfile fastapi uvicorn
WORKDIR /app
COPY server.py index.html /app/
RUN chmod 777 /app
ENV USER=space LOGNAME=space HOME=/tmp XDG_CACHE_HOME=/tmp/.cache TORCHINDUCTOR_CACHE_DIR=/tmp/torchinductor
ENV MODEL=Qwen/Qwen3-Omni-30B-A3B-Instruct \
    USE_PREFIX=1 \
    INTERVAL=1.5 \
    START_AFTER_SEC=1.5 \
    PREFIX_LAG_SEC=3.0 \
    MAX_NEW_TOKENS=64 \
    WINDOW_SEC=30
ENTRYPOINT ["/usr/bin/python3", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "7860"]
