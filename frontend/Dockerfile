FROM node:22-alpine AS build
WORKDIR /workspace
COPY frontend/package.json ./frontend/package.json
RUN npm --prefix frontend install
COPY frontend ./frontend
COPY UI ./UI
RUN npm --prefix frontend run build

FROM nginx:1.27-alpine
COPY frontend/nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /workspace/frontend/dist /usr/share/nginx/html
EXPOSE 80
