# Multi-threaded HTTP Server (Socket Programming)

A production-grade, educational HTTP/1.1 and HTTP/1.0 server implemented using only Python standard library modules (socket, threading, queue, os, sys, time, datetime, json, random, string, logging, mimetypes).

## Features
- Thread pool with connection queue (default 10 workers; configurable)
- HTTP/1.1 keep-alive (timeout=30s, max=100 requests/connection) and HTTP/1.0 close-by-default
- GET static file serving from `resources/`
  - `text/html; charset=utf-8` for `.html`
  - `application/octet-stream` download for `.txt`, `.png`, `.jpg`, `.jpeg`
  - Binary-safe handling with `Content-Disposition` for downloads
- POST JSON upload to `/upload` saving files to `resources/uploads/`
- Security: path traversal prevention, Host header validation
- Comprehensive logging (console + `logs/server.log`)

## Directory Layout
```
project/
├── server.py
├── resources/
│   ├── index.html
│   ├── sample.html
│   ├── test.txt
│   ├── test.json
│   ├── logo.png
│   ├── photo.jpg
│   ├── large_image.png
│   ├── large_photo.jpg
│   └── uploads/           # created automatically if missing
└── logs/
    └── server.log         # created automatically
```

## Quick Start
```bash
python3 server.py                 # 127.0.0.1:8080, 10 threads
python3 server.py 8000            # custom port
python3 server.py 8000 0.0.0.0    # custom host
python3 server.py 8000 0.0.0.0 20 # custom host, port, max_threads
```
Then open `http://localhost:8080/` in your browser.

If port is busy:
```bash
lsof -nP -iTCP:8080 -sTCP:LISTEN
kill -9 <PID>
```

## Testing
### Browser
- Visit `/` for the dashboard and links to test files
- Use the JSON upload form to POST to `/upload`

### curl
```bash
# HTML
curl -H "Host: localhost:8080" http://localhost:8080/

# Binary downloads
curl -H "Host: localhost:8080" -O http://localhost:8080/resources/test.txt
curl -H "Host: localhost:8080" -O http://localhost:8080/resources/logo.png
curl -H "Host: localhost:8080" -O http://localhost:8080/resources/photo.jpg

# JSON upload
curl -i -X POST http://localhost:8080/upload \
  -H "Host: localhost:8080" \
  -H "Content-Type: application/json" \
  -d '{"name":"test","value":123}'
```
Expected on success: `201 Created` with JSON body including `filename` and `size`.

## HTTP Behaviour
- Default Keep-Alive for HTTP/1.1. Close by default for HTTP/1.0 unless `Connection: keep-alive`.
- Server sets `Date` (RFC 7231), `Content-Type`, `Content-Length`, `Connection`, and `Keep-Alive` (timeout=30, max=100) where applicable.
- Error codes: 400, 403, 404, 405, 415, 500, 503 (with `Retry-After`).

## Security
- Path traversal protection: canonicalize paths; block `..`, `//`, absolute escapes; only allow `/`, `/upload`, and files under `/resources/`.
- Host header validation: only `localhost:PORT`, `127.0.0.1:PORT`, or configured host:port.
- All violations logged to `logs/server.log`.

## Thread Pool
- Fixed-size pool using `threading` + `queue.Queue`
- Accept loop enqueues connections; workers dequeue and serve
- Logs queueing/dequeueing and active usage

## Known Limitations
- No TLS/HTTPS (HTTP only)
- No compression (gzip/deflate)
- No auth/rate limiting
- Large file sends are buffered by process (sufficient for course scope)

## Troubleshooting
- Address in use: free port 8080 via `lsof`/`kill`
- 403 on `/upload`: ensure server is latest and running; request must use `Content-Type: application/json`
- UI error parsing: the web UI handles HTML error responses gracefully; check `logs/server.log`

## License
For educational use in a Computer Networks assignment.
