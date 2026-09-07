FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . ./
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY entrypoint.sh /usr/local/bin/prama-nginx-entrypoint
RUN chmod +x /usr/local/bin/prama-nginx-entrypoint
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80

ENTRYPOINT ["/usr/local/bin/prama-nginx-entrypoint"]
