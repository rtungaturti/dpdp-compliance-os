const http = require('http');
const fs = require('fs');
const port = 3002;
const html = fs.readFileSync('index.html', 'utf8');
http.createServer((req, res) => {
  if (req.url === '/health') { res.writeHead(200); res.end('ok'); return; }
  res.writeHead(200, {'Content-Type': 'text/html'});
  res.end(html);
}).listen(port, () => console.log('dpo-console on :' + port));
