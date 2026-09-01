# A imagem oficial do Playwright já traz o Chromium e as bibliotecas de sistema.
# Montar isso à mão em cima de python:slim é a fonte número um de CI quebrado.
FROM mcr.microsoft.com/playwright/python:v1.56.0-jammy

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

ENTRYPOINT ["a11y-audit"]
CMD ["--help"]
