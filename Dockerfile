# One image, many services. NIGHTSHIFT_SERVICE selects which app it serves.
#
# The domain services have genuinely different authority boundaries and deploy as
# separate Cloud Run services with separate service accounts and separate URLs. They
# share an image because their code and dependencies are identical — what differs is
# the identity they run as and the routes they expose, and both of those are runtime
# configuration, not build output.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

# Dependencies first so application edits do not invalidate the dependency layer.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY nightshift ./nightshift
COPY services ./services
COPY agents ./agents
COPY assurance ./assurance
COPY fixtures ./fixtures
COPY skills ./skills
COPY corpus ./corpus
COPY apps/api ./apps/api

# Published evidence and the claim ledger are read at request time by the public
# evidence, drills, and proof surfaces. They are part of the deliverable, not build
# scratch, so they ship inside the image.
COPY evidence ./evidence
COPY docs ./docs

RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    PORT=8080 \
    NIGHTSHIFT_STORE=firestore \
    NIGHTSHIFT_ENV=cloud-run

# Cloud Run sets PORT; the entrypoint resolves NIGHTSHIFT_SERVICE to an ASGI app.
# The rest of scripts/ ships too, because the scheduled Cloud Run Job runs
# scripts/scheduled_tick.py out of this same image.
COPY scripts ./scripts

EXPOSE 8080
CMD ["python", "scripts/serve.py"]
