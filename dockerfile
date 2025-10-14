# Sử dụng Python 3.11 làm base image
FROM python:3.11-slim

# Cài đặt dependencies cho Playwright
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# Tạo thư mục làm việc
WORKDIR /app

# Copy file requirements và cài thư viện
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Cài Chromium cho Playwright
RUN playwright install chromium
RUN playwright install-deps chromium

# Copy toàn bộ code vào container
COPY . .

# Expose port 8000
EXPOSE 8000

# Chạy ứng dụng FastAPI
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]