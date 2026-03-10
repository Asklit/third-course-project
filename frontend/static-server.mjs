import { createServer } from "node:http";
import { createReadStream, existsSync, statSync } from "node:fs";
import { extname, join, normalize } from "node:path";

const PORT = Number(process.env.PORT || 80);
const ROOT = join(process.cwd(), "dist");

const MIME_TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".webp": "image/webp",
  ".ico": "image/x-icon",
  ".txt": "text/plain; charset=utf-8",
};

function safePath(urlPath) {
  const cleanPath = (urlPath || "/").split("?")[0].split("#")[0];
  const normalizedPath = normalize(cleanPath).replace(/^([.][.][/\\])+/, "");
  return join(ROOT, normalizedPath);
}

function sendFile(res, filePath) {
  const ext = extname(filePath).toLowerCase();
  const contentType = MIME_TYPES[ext] || "application/octet-stream";

  res.statusCode = 200;
  res.setHeader("Content-Type", contentType);
  createReadStream(filePath).pipe(res);
}

createServer((req, res) => {
  const method = req.method || "GET";
  if (method !== "GET" && method !== "HEAD") {
    res.statusCode = 405;
    res.end("Method Not Allowed");
    return;
  }

  const requested = safePath(req.url || "/");
  if (existsSync(requested) && statSync(requested).isFile()) {
    if (method === "HEAD") {
      res.statusCode = 200;
      res.end();
      return;
    }
    sendFile(res, requested);
    return;
  }

  const indexFile = join(ROOT, "index.html");
  if (!existsSync(indexFile)) {
    res.statusCode = 500;
    res.end("Build output not found");
    return;
  }

  if (method === "HEAD") {
    res.statusCode = 200;
    res.end();
    return;
  }
  sendFile(res, indexFile);
}).listen(PORT, "0.0.0.0", () => {
  console.log(`Frontend server started on port ${PORT}`);
});
