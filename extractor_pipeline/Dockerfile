FROM nvidia/cuda:13.2.1-runtime-ubuntu24.04

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip3 install --break-system-packages --no-cache-dir torch==2.5.1 --index-url https://download.pytorch.org/whl/cu121 && \
    pip3 install --break-system-packages --no-cache-dir -r requirements.txt

COPY src/ ./src/

RUN ln -s /usr/bin/python3 /usr/bin/python

EXPOSE 8001

CMD ["python3", "-u", "src/main.py"]
