# syntax=docker/dockerfile:1.7
#
# Imagem da admin UI (SPEC §5.4 / Fase 7).
#
# Multi-stage: node 20 builda o bundle, nginx-alpine serve estático.
#   docker build -f ui/Dockerfile -t vagg/ui:dev ui/

FROM node:20-alpine AS builder
WORKDIR /app

# 1. install deps separadamente do código → cache-friendly
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund --loglevel=error

# 2. copia o código e builda o bundle
COPY . .
RUN npm run build

# 3. nginx serve o /dist com SPA fallback
FROM nginx:1.27-alpine
RUN rm -rf /usr/share/nginx/html/* /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
