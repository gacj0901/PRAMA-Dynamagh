FROM node:22-alpine
WORKDIR /contracts
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
CMD ["npm","test"]
