FROM python:3.12-slim AS builder

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY publisher ./publisher
COPY content ./content
ARG BASE_URL=https://example.com
ENV BASE_URL=${BASE_URL}
RUN python -m publisher build --content content/pages --output dist --state data/state.sqlite3 --base-url ${BASE_URL}

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 8080

