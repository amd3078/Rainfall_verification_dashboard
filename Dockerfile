# Fully self-contained image: all geo binaries (PROJ/GEOS/ecCodes) baked in.
# Build:  docker build -t rainfall-verif .
# Run:    docker run -p 8501:8501 -v /path/to/your/data:/data rainfall-verif
FROM mambaorg/micromamba:1.5.8

# install env from /tmp (world-writable) — micromamba/pip write temp files in the cwd
WORKDIR /tmp
COPY --chown=$MAMBA_USER:$MAMBA_USER environment.yml /tmp/environment.yml
RUN micromamba install -y -n base -f /tmp/environment.yml && micromamba clean -a -y

WORKDIR /app
COPY --chown=$MAMBA_USER:$MAMBA_USER . /app

EXPOSE 8501
ARG MAMBA_DOCKERFILE_ACTIVATE=1
CMD ["streamlit","run","app.py","--server.port=8501","--server.address=0.0.0.0","--server.headless=true"]
