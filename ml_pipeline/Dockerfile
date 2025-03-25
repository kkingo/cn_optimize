FROM python:3.9-slim
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
WORKDIR /app
COPY . .

# 快速安装Python依赖（禁用缓存清理）
RUN pip install --no-cache-dir \
    numpy \
    scikit-learn \
    pandas \
    flask \
    requests \
    ijson

CMD ["python", "ml_app.py"]