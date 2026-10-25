# image for the run_python tool, build once: docker build -t sensai-sandbox sandbox/
# sensai starts it w/ no network, cpu + mem caps, a read only fs and data/ mounted read only
FROM python:3.12-slim

RUN pip install --no-cache-dir \
    pandas==2.2.3 numpy==2.1.3 scipy==1.14.1 statsmodels==0.14.4 matplotlib==3.9.2

# the run user is set by sensai (--user), this 1 is for a manual docker run
RUN useradd --create-home sandbox
USER sandbox
ENV MPLBACKEND=Agg
