FROM node:20-alpine
WORKDIR /app
COPY . .
RUN echo '{"name":"executive-dashboard","version":"1.0.0","scripts":{"start":"node server.js"}}' > package.json
EXPOSE 3001
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD wget -q --spider http://localhost:3001/ || exit 1
CMD ["node", "server.js"]
