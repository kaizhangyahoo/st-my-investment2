# Gateway: builds the React SPA and serves it with nginx, proxying /api to the backend.
FROM node:24-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
# The nginx image renders /etc/nginx/templates/*.template with envsubst at start-up.
ENV DATA_API_UPSTREAM=backend:8000 T212_UPSTREAM=backend:8000
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget -qO- http://127.0.0.1/nginx-health || exit 1
