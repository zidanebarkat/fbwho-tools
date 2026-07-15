FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl unzip ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install deno
RUN curl -fsSL https://deno.land/install.sh | sh || \
    (curl -fsSL -o /tmp/deno.zip https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip && \
     unzip /tmp/deno.zip -d /usr/local/bin/ && rm /tmp/deno.zip)
ENV DENO_INSTALL=/root/.deno
ENV PATH=$DENO_INSTALL/bin:/usr/local/bin:$PATH

RUN deno --version || echo "deno not available"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY render_yt_proxy.py .

EXPOSE 8000

CMD ["python3", "render_yt_proxy.py"]
