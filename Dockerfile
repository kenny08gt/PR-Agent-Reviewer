# Docker-container GitHub Action image. Kept intentionally small:
# python:3.13-slim + pure-Python wheels only. If a future dep needs a
# compiler (e.g. tiktoken on a new Python minor), add the build deps in
# a throwaway `RUN apt-get install --no-install-recommends ...` that we
# drop in a multi-stage build rather than bloating the runtime layer.
FROM python:3.13-slim

WORKDIR /app

# Install deps first so layer caching survives src/ edits.
COPY src/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY src /app/src

# GitHub runs Docker actions with `--workdir /github/workspace` (the
# consumer's repo checkout), overriding the image WORKDIR. Put /app on
# PYTHONPATH so `python -m src.action` resolves regardless of cwd.
ENV PYTHONPATH=/app

# Action entry point. GitHub invokes the container with no extra args;
# all inputs arrive via INPUT_* env vars and src/action.py reads them.
ENTRYPOINT ["python", "-m", "src.action"]
