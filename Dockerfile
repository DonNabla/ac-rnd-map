# Stage 1: validate the data and build the single-file site.
FROM python:3.12-alpine AS build
WORKDIR /src
COPY build.py ./
COPY data ./data
COPY src ./src
COPY vendor ./vendor
RUN python3 build.py

# Stage 2: serve it with nginx as a non-root user on port 8080.
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=build /src/site/ /usr/share/nginx/html/
USER nginx
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
CMD ["nginx", "-g", "daemon off;"]
