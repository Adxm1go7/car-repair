# Build stage: compile the React app to static files.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Serve stage: nginx serves the static files and proxies /api to the backend.
FROM nginx:1.29-alpine
# The base image can lag behind Alpine's security fixes; take them at build time.
RUN apk upgrade --no-cache
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY security-headers.conf /etc/nginx/security-headers.conf
COPY --from=build /app/dist /usr/share/nginx/html
