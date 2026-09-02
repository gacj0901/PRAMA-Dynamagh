FROM node:20-alpine

WORKDIR /app
COPY package.json ./
RUN npm install
COPY tsconfig.json ./
COPY src ./src
COPY tests ./tests

EXPOSE 8081
CMD ["npx", "tsx", "src/server.ts"]
