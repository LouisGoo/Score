FROM node:24-alpine AS build
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
ARG PUBLIC_BASE_URL
ENV VITE_PUBLIC_BASE_URL=$PUBLIC_BASE_URL
RUN node -e 'const u=new URL(process.env.VITE_PUBLIC_BASE_URL); if(u.protocol!=="https:" || u.origin!==process.env.VITE_PUBLIC_BASE_URL) process.exit(1)' && npm run build

FROM nginx:stable-alpine
COPY infra/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
