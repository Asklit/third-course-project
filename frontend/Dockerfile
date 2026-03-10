FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

FROM node:20-alpine AS runtime
WORKDIR /app
COPY --from=build /app/dist ./dist
COPY static-server.mjs ./static-server.mjs
EXPOSE 80
CMD ["node", "static-server.mjs"]
