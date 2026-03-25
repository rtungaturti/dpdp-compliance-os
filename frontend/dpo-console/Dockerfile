FROM node:20-alpine
WORKDIR /app
COPY . .
EXPOSE 3002
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD wget -q --spider http://localhost:3002/ || exit 1
CMD ["node", "server.js"]
