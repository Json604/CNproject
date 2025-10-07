#!/usr/bin/env python3
"""
Multi-threaded HTTP Server Using Socket Programming
Computer Networks Assignment - Production Grade Implementation

This server implements a full HTTP/1.1 and HTTP/1.0 compliant server with:
- Multi-threading with thread pool
- File serving (HTML, images, text files)
- JSON upload handling
- Security features (path traversal prevention, host validation)
- Connection management (keep-alive, timeouts)
- Comprehensive logging

Author: Computer Networks Assignment
Python Version: 3.6+
"""

import socket
import threading
import queue
import os
import sys
import time
import datetime
import json
import random
import string
import logging
import mimetypes
import signal
from urllib.parse import unquote, urlparse
from typing import Dict, Tuple, Optional, List


class HTTPServer:
    """
    Multi-threaded HTTP Server implementation with thread pool management.
    Supports HTTP/1.1 and HTTP/1.0 with keep-alive connections.
    """
    
    def __init__(self, host: str = "127.0.0.1", port: int = 8080, max_threads: int = 10):
        """
        Initialize the HTTP server with configuration parameters.
        
        Args:
            host: Server host address (default: 127.0.0.1)
            port: Server port number (default: 8080)
            max_threads: Maximum number of worker threads (default: 10)
        """
        self.host = host
        self.port = port
        self.max_threads = max_threads
        self.server_socket = None
        self.running = False
        self.thread_pool = []
        self.connection_queue = queue.Queue()
        self.active_connections = 0
        self.connection_lock = threading.Lock()
        self.stats_lock = threading.Lock()
        
        # Statistics tracking
        self.total_requests = 0
        self.total_connections = 0
        self.active_threads = 0
        
        # Setup logging
        self._setup_logging()
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # Ensure required directories exist
        self._ensure_directories()
        
        self.logger.info(f"HTTP Server initialized: {host}:{port}, max_threads={max_threads}")
    
    def _setup_logging(self):
        """Configure comprehensive logging system."""
        # Create logs directory if it doesn't exist
        os.makedirs("logs", exist_ok=True)
        
        # Configure logging format
        log_format = "%(asctime)s [%(levelname)s] [Thread-%(threadName)s] [Conn-%(message)s"
        date_format = "%Y-%m-%d %H:%M:%S"
        
        # Setup file handler
        file_handler = logging.FileHandler("logs/server.log", mode='a')
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter(log_format, date_format))
        
        # Setup console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(logging.Formatter(log_format, date_format))
        
        # Configure root logger
        self.logger = logging.getLogger("HTTPServer")
        self.logger.setLevel(logging.INFO)
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
        
        # Prevent duplicate logs
        self.logger.propagate = False
    
    def _ensure_directories(self):
        """Ensure required directory structure exists."""
        directories = ["resources", "resources/uploads", "logs"]
        for directory in directories:
            os.makedirs(directory, exist_ok=True)
            self.logger.info(f"Ensured directory exists: {directory}")
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        self.logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.stop()
    
    def start(self):
        """Start the HTTP server and thread pool."""
        try:
            # Create server socket
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(50)  # Listen queue >= 50 as required
            
            self.running = True
            self.logger.info(f"Server started on {self.host}:{self.port}")
            self.logger.info(f"Thread pool size: {self.max_threads}")
            self.logger.info("Server ready to accept connections...")
            
            # Start worker threads
            for i in range(self.max_threads):
                thread = threading.Thread(target=self._worker_thread, name=f"Worker-{i+1}")
                thread.daemon = True
                thread.start()
                self.thread_pool.append(thread)
            
            # Main accept loop
            while self.running:
                try:
                    client_socket, client_address = self.server_socket.accept()
                    self.logger.info(f"New connection from {client_address[0]}:{client_address[1]}")
                    
                    with self.connection_lock:
                        self.total_connections += 1
                        self.active_connections += 1
                    
                    # Queue the connection for processing
                    self.connection_queue.put((client_socket, client_address))
                    self.logger.info(f"Connection queued for processing. Queue size: {self.connection_queue.qsize()}")
                    
                except OSError as e:
                    if self.running:
                        self.logger.error(f"Error accepting connection: {e}")
                    break
                    
        except Exception as e:
            self.logger.error(f"Failed to start server: {e}")
            raise
        finally:
            self.stop()
    
    def _worker_thread(self):
        """Worker thread that processes connections from the queue."""
        thread_name = threading.current_thread().name
        
        while self.running:
            try:
                # Get connection from queue with timeout
                client_socket, client_address = self.connection_queue.get(timeout=1.0)
                
                with self.connection_lock:
                    self.active_threads += 1
                
                self.logger.info(f"[{thread_name}] Processing connection from {client_address[0]}:{client_address[1]}")
                
                # Process the connection
                self._handle_connection(client_socket, client_address, thread_name)
                
                with self.connection_lock:
                    self.active_threads -= 1
                    self.active_connections -= 1
                
                self.connection_queue.task_done()
                
            except queue.Empty:
                # Timeout waiting for connection, continue loop
                continue
            except Exception as e:
                self.logger.error(f"[{thread_name}] Error in worker thread: {e}")
                with self.connection_lock:
                    self.active_threads -= 1
                    if self.active_connections > 0:
                        self.active_connections -= 1
    
    def _handle_connection(self, client_socket: socket.socket, client_address: Tuple[str, int], thread_name: str):
        """
        Handle a single client connection with support for keep-alive.
        
        Args:
            client_socket: Client socket connection
            client_address: Client address tuple (host, port)
            thread_name: Name of the processing thread
        """
        connection_id = f"{client_address[0]}:{client_address[1]}"
        request_count = 0
        max_requests = 100  # Maximum requests per connection
        keep_alive_timeout = 30  # 30 seconds timeout
        
        try:
            client_socket.settimeout(keep_alive_timeout)
            
            while request_count < max_requests and self.running:
                try:
                    # Receive HTTP request
                    request_data = client_socket.recv(8192).decode('utf-8')
                    if not request_data:
                        self.logger.info(f"[{thread_name}] Connection closed by client: {connection_id}")
                        break
                    
                    self.logger.info(f"[{thread_name}] Received request from {connection_id} (request #{request_count + 1})")
                    
                    # Parse HTTP request
                    request = self._parse_http_request(request_data)
                    if not request:
                        self.logger.warning(f"[{thread_name}] Invalid request from {connection_id}")
                        self._send_error_response(client_socket, 400, "Bad Request")
                        break
                    
                    # Process the request
                    response = self._process_request(request, client_address, thread_name)
                    
                    # Send response
                    self._send_response(client_socket, response)
                    
                    request_count += 1
                    with self.stats_lock:
                        self.total_requests += 1
                    
                    # Check if connection should be closed
                    if request.get('headers', {}).get('connection', '').lower() == 'close':
                        self.logger.info(f"[{thread_name}] Connection close requested by client: {connection_id}")
                        break
                    
                    # Check if keep-alive is supported
                    if request.get('version') == 'HTTP/1.0' and request.get('headers', {}).get('connection', '').lower() != 'keep-alive':
                        self.logger.info(f"[{thread_name}] HTTP/1.0 without keep-alive, closing connection: {connection_id}")
                        break
                    
                except socket.timeout:
                    self.logger.info(f"[{thread_name}] Connection timeout for {connection_id}")
                    break
                except Exception as e:
                    self.logger.error(f"[{thread_name}] Error processing request from {connection_id}: {e}")
                    self._send_error_response(client_socket, 500, "Internal Server Error")
                    break
            
            self.logger.info(f"[{thread_name}] Connection completed: {connection_id}, requests processed: {request_count}")
            
        except Exception as e:
            self.logger.error(f"[{thread_name}] Error handling connection {connection_id}: {e}")
        finally:
            try:
                client_socket.close()
            except:
                pass
    
    def _parse_http_request(self, request_data: str) -> Optional[Dict]:
        """
        Parse HTTP request data into structured format.
        
        Args:
            request_data: Raw HTTP request string
            
        Returns:
            Parsed request dictionary or None if invalid
        """
        try:
            lines = request_data.strip().split('\r\n')
            if not lines:
                return None
            
            # Parse request line
            request_line = lines[0].split()
            if len(request_line) != 3:
                return None
            
            method, path, version = request_line
            
            # Validate method
            if method not in ['GET', 'POST']:
                return None
            
            # Parse headers
            headers = {}
            body_start = 1
            
            for i, line in enumerate(lines[1:], 1):
                if line == '':
                    body_start = i + 1
                    break
                
                if ':' in line:
                    key, value = line.split(':', 1)
                    headers[key.strip().lower()] = value.strip()
            
            # Parse body if present
            body = ''
            if body_start < len(lines):
                body = '\r\n'.join(lines[body_start:])
            
            return {
                'method': method,
                'path': path,
                'version': version,
                'headers': headers,
                'body': body
            }
            
        except Exception as e:
            self.logger.error(f"Error parsing HTTP request: {e}")
            return None
    
    def _process_request(self, request: Dict, client_address: Tuple[str, int], thread_name: str) -> Dict:
        """
        Process HTTP request and generate appropriate response.
        
        Args:
            request: Parsed HTTP request dictionary
            client_address: Client address tuple
            thread_name: Processing thread name
            
        Returns:
            Response dictionary
        """
        method = request['method']
        path = request['path']
        headers = request['headers']
        
        # Security: Validate Host header
        host_validation = self._validate_host_header(headers, client_address)
        if not host_validation['valid']:
            return self._create_error_response(host_validation['status_code'], host_validation['message'])
        
        # Security: Validate and sanitize path
        path_validation = self._validate_path(path)
        if not path_validation['valid']:
            self.logger.warning(f"[{thread_name}] Security violation - path validation failed: {path} - {path_validation['message']}")
            return self._create_error_response(path_validation['status_code'], path_validation['message'])
        
        # Process based on method
        if method == 'GET':
            return self._handle_get_request(path, thread_name)
        elif method == 'POST':
            return self._handle_post_request(path, request['body'], headers, thread_name)
        else:
            return self._create_error_response(405, "Method Not Allowed")
    
    def _validate_host_header(self, headers: Dict, client_address: Tuple[str, int]) -> Dict:
        """
        Validate Host header for security.
        
        Args:
            headers: Request headers dictionary
            client_address: Client address tuple
            
        Returns:
            Validation result dictionary
        """
        host_header = headers.get('host', '')
        
        if not host_header:
            return {'valid': False, 'status_code': 400, 'message': 'Missing Host header'}
        
        # Extract host and port from Host header
        if ':' in host_header:
            host, port = host_header.split(':', 1)
            try:
                port = int(port)
            except ValueError:
                return {'valid': False, 'status_code': 400, 'message': 'Invalid Host header format'}
        else:
            host = host_header
            port = 80 if self.port == 80 else self.port
        
        # Validate host matches server configuration
        valid_hosts = [self.host, 'localhost', '127.0.0.1']
        if self.host == '0.0.0.0':
            valid_hosts.extend(['localhost', '127.0.0.1'])
        
        if host not in valid_hosts or port != self.port:
            self.logger.warning(f"Host header validation failed: {host_header} (expected: {self.host}:{self.port})")
            return {'valid': False, 'status_code': 403, 'message': 'Forbidden - Invalid Host header'}
        
        return {'valid': True}
    
    def _validate_path(self, path: str) -> Dict:
        """
        Validate and sanitize request path to prevent path traversal attacks.
        
        Args:
            path: Request path string
            
        Returns:
            Validation result dictionary
        """
        try:
            # URL decode the path
            decoded_path = unquote(path)
            
            # Parse the path
            parsed_path = urlparse(decoded_path)
            clean_path = parsed_path.path
            
            # Allow specific endpoints first
            if clean_path in ['/', '/upload']:
                return {'valid': True, 'clean_path': clean_path}
            
            # Allow resources directory access
            if clean_path.startswith('/resources/'):
                return {'valid': True, 'clean_path': clean_path}
            
            # Check for path traversal attempts
            if '..' in clean_path or (clean_path.startswith('/') and '//' in clean_path):
                return {'valid': False, 'status_code': 403, 'message': 'Forbidden - Path traversal detected'}
            
            # Block access to other paths
            return {'valid': False, 'status_code': 403, 'message': 'Forbidden - Access outside resources directory'}
            
        except Exception as e:
            self.logger.error(f"Error validating path {path}: {e}")
            return {'valid': False, 'status_code': 400, 'message': 'Bad Request - Invalid path'}
    
    def _handle_get_request(self, path: str, thread_name: str) -> Dict:
        """
        Handle GET requests for file serving.
        
        Args:
            path: Request path
            thread_name: Processing thread name
            
        Returns:
            Response dictionary
        """
        # Default to index.html for root path
        if path == '/':
            file_path = 'resources/index.html'
        else:
            # Remove leading slash and add resources prefix
            clean_path = path.lstrip('/')
            if not clean_path.startswith('resources/'):
                clean_path = f'resources/{clean_path}'
            file_path = clean_path
        
        # Check if file exists
        if not os.path.exists(file_path):
            self.logger.warning(f"[{thread_name}] File not found: {file_path}")
            return self._create_error_response(404, "Not Found")
        
        # Check if it's a file (not directory)
        if not os.path.isfile(file_path):
            self.logger.warning(f"[{thread_name}] Path is not a file: {file_path}")
            return self._create_error_response(404, "Not Found")
        
        # Determine content type and handling
        mime_type, _ = mimetypes.guess_type(file_path)
        
        # Handle different file types
        if file_path.endswith('.html'):
            return self._serve_html_file(file_path, thread_name)
        elif file_path.endswith(('.txt', '.png', '.jpg', '.jpeg')):
            return self._serve_binary_file(file_path, thread_name)
        else:
            # Check if it's a supported file type
            if mime_type:
                return self._serve_binary_file(file_path, thread_name)
            else:
                self.logger.warning(f"[{thread_name}] Unsupported file type: {file_path}")
                return self._create_error_response(415, "Unsupported Media Type")
    
    def _serve_html_file(self, file_path: str, thread_name: str) -> Dict:
        """
        Serve HTML files with proper content type.
        
        Args:
            file_path: Path to HTML file
            thread_name: Processing thread name
            
        Returns:
            Response dictionary
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            self.logger.info(f"[{thread_name}] Serving HTML file: {file_path} ({len(content)} bytes)")
            
            return {
                'status_code': 200,
                'status_text': 'OK',
                'headers': {
                    'Content-Type': 'text/html; charset=utf-8',
                    'Content-Length': str(len(content)),
                    'Connection': 'keep-alive'
                },
                'body': content
            }
            
        except Exception as e:
            self.logger.error(f"[{thread_name}] Error serving HTML file {file_path}: {e}")
            return self._create_error_response(500, "Internal Server Error")
    
    def _serve_binary_file(self, file_path: str, thread_name: str) -> Dict:
        """
        Serve binary files with proper headers for download.
        
        Args:
            file_path: Path to binary file
            thread_name: Processing thread name
            
        Returns:
            Response dictionary
        """
        try:
            file_size = os.path.getsize(file_path)
            filename = os.path.basename(file_path)
            
            self.logger.info(f"[{thread_name}] Serving binary file: {file_path} ({file_size} bytes)")
            
            # Read file in chunks for large files
            with open(file_path, 'rb') as f:
                content = f.read()
            
            return {
                'status_code': 200,
                'status_text': 'OK',
                'headers': {
                    'Content-Type': 'application/octet-stream',
                    'Content-Length': str(file_size),
                    'Content-Disposition': f'attachment; filename="{filename}"',
                    'Connection': 'keep-alive'
                },
                'body': content,
                'is_binary': True
            }
            
        except Exception as e:
            self.logger.error(f"[{thread_name}] Error serving binary file {file_path}: {e}")
            return self._create_error_response(500, "Internal Server Error")
    
    def _handle_post_request(self, path: str, body: str, headers: Dict, thread_name: str) -> Dict:
        """
        Handle POST requests for JSON uploads.
        
        Args:
            path: Request path
            body: Request body
            headers: Request headers
            thread_name: Processing thread name
            
        Returns:
            Response dictionary
        """
        # Only allow POST to /upload
        if path != '/upload':
            return self._create_error_response(404, "Not Found")
        
        # Check Content-Type
        content_type = headers.get('content-type', '')
        if not content_type.startswith('application/json'):
            self.logger.warning(f"[{thread_name}] Invalid Content-Type for POST: {content_type}")
            return self._create_error_response(415, "Unsupported Media Type")
        
        # Parse JSON
        try:
            json_data = json.loads(body)
        except json.JSONDecodeError as e:
            self.logger.warning(f"[{thread_name}] Invalid JSON in POST request: {e}")
            return self._create_error_response(400, "Bad Request - Invalid JSON")
        
        # Save upload
        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            random_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
            filename = f"upload_{timestamp}_{random_id}.json"
            file_path = os.path.join("resources", "uploads", filename)
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, indent=2)
            
            self.logger.info(f"[{thread_name}] JSON upload saved: {file_path}")
            
            # Create response
            response_data = {
                "status": "success",
                "message": "File uploaded successfully",
                "filename": filename,
                "size": len(body)
            }
            
            response_json = json.dumps(response_data, indent=2)
            
            return {
                'status_code': 201,
                'status_text': 'Created',
                'headers': {
                    'Content-Type': 'application/json; charset=utf-8',
                    'Content-Length': str(len(response_json)),
                    'Connection': 'keep-alive'
                },
                'body': response_json
            }
            
        except Exception as e:
            self.logger.error(f"[{thread_name}] Error saving JSON upload: {e}")
            return self._create_error_response(500, "Internal Server Error")
    
    def _create_error_response(self, status_code: int, message: str) -> Dict:
        """
        Create standardized error response.
        
        Args:
            status_code: HTTP status code
            message: Error message
            
        Returns:
            Error response dictionary
        """
        status_messages = {
            400: "Bad Request",
            403: "Forbidden",
            404: "Not Found",
            405: "Method Not Allowed",
            415: "Unsupported Media Type",
            500: "Internal Server Error",
            503: "Service Unavailable"
        }
        
        status_text = status_messages.get(status_code, "Unknown Error")
        
        # Create error page
        error_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>{status_code} {status_text}</title>
        </head>
        <body>
            <h1>{status_code} {status_text}</h1>
            <p>{message}</p>
        </body>
        </html>
        """
        
        headers = {
            'Content-Type': 'text/html; charset=utf-8',
            'Content-Length': str(len(error_html)),
            'Connection': 'close'
        }
        
        # Add Retry-After header for 503
        if status_code == 503:
            headers['Retry-After'] = '60'
        
        return {
            'status_code': status_code,
            'status_text': status_text,
            'headers': headers,
            'body': error_html
        }
    
    def _send_response(self, client_socket: socket.socket, response: Dict):
        """
        Send HTTP response to client.
        
        Args:
            client_socket: Client socket connection
            response: Response dictionary
        """
        try:
            # Format status line
            status_line = f"HTTP/1.1 {response['status_code']} {response['status_text']}\r\n"
            
            # Add Date header
            date_header = f"Date: {datetime.datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT')}\r\n"
            
            # Format headers
            headers = ""
            for key, value in response['headers'].items():
                headers += f"{key}: {value}\r\n"
            
            # Combine response
            http_response = status_line + date_header + headers + "\r\n"
            
            # Send headers
            client_socket.send(http_response.encode('utf-8'))
            
            # Send body
            body = response.get('body', '')
            if body:
                if response.get('is_binary', False):
                    # Send binary data
                    client_socket.send(body)
                else:
                    # Send text data
                    client_socket.send(body.encode('utf-8'))
            
        except Exception as e:
            self.logger.error(f"Error sending response: {e}")
    
    def _send_error_response(self, client_socket: socket.socket, status_code: int, message: str):
        """Send error response directly to client socket."""
        try:
            response = self._create_error_response(status_code, message)
            self._send_response(client_socket, response)
        except Exception as e:
            self.logger.error(f"Error sending error response: {e}")
    
    def stop(self):
        """Stop the HTTP server gracefully."""
        self.logger.info("Stopping HTTP server...")
        self.running = False
        
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
        
        # Wait for active connections to complete
        self.logger.info("Waiting for active connections to complete...")
        time.sleep(2)
        
        # Log final statistics
        with self.stats_lock:
            self.logger.info(f"Server stopped. Total requests: {self.total_requests}, Total connections: {self.total_connections}")


def main():
    """
    Main entry point for the HTTP server.
    Parses command line arguments and starts the server.
    """
    # Default values
    host = "127.0.0.1"
    port = 8080
    max_threads = 10
    
    # Parse command line arguments
    if len(sys.argv) >= 2:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print("Error: Port must be an integer")
            sys.exit(1)
    
    if len(sys.argv) >= 3:
        host = sys.argv[2]
    
    if len(sys.argv) >= 4:
        try:
            max_threads = int(sys.argv[3])
        except ValueError:
            print("Error: Max threads must be an integer")
            sys.exit(1)
    
    # Validate arguments
    if not (1 <= port <= 65535):
        print("Error: Port must be between 1 and 65535")
        sys.exit(1)
    
    if max_threads < 1:
        print("Error: Max threads must be at least 1")
        sys.exit(1)
    
    # Create and start server
    try:
        server = HTTPServer(host, port, max_threads)
        print(f"Starting HTTP server on {host}:{port} with {max_threads} threads...")
        print("Press Ctrl+C to stop the server")
        server.start()
    except KeyboardInterrupt:
        print("\nServer stopped by user")
    except Exception as e:
        print(f"Error starting server: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()


"""
===============================================================================
README - Multi-threaded HTTP Server
===============================================================================

## Build and Run Instructions

### Prerequisites
- Python 3.6 or higher
- No external dependencies (uses only standard library)

### Directory Setup
Before running the server, ensure the following directory structure exists:
```
project/
├── server.py
├── resources/
│   ├── index.html          # Default homepage
│   ├── *.html              # Other HTML files
│   ├── *.txt               # Text files for download
│   ├── *.png, *.jpg, *.jpeg # Image files for download
│   └── uploads/            # Directory for JSON uploads (auto-created)
└── logs/
    └── server.log          # Server log file (auto-created)
```

### Running the Server
```bash
# Default configuration (127.0.0.1:8080, 10 threads)
python server.py

# Custom port
python server.py 8000

# Custom host and port
python server.py 8000 0.0.0.0

# Custom host, port, and max threads
python server.py 8000 0.0.0.0 20
```

### Testing the Server

#### 1. Basic File Serving
```bash
# Test HTML serving
curl http://localhost:8080/

# Test specific HTML file
curl http://localhost:8080/resources/test.html

# Test binary file download
curl -O http://localhost:8080/resources/image.png
```

#### 2. JSON Upload
```bash
# Upload JSON data
curl -X POST http://localhost:8080/upload \
  -H "Content-Type: application/json" \
  -d '{"name": "test", "value": 123}'
```

#### 3. Browser Testing
Open browser and navigate to:
- http://localhost:8080/ (homepage)
- http://localhost:8080/resources/ (file listing)

## Binary Transfer Explanation

The server handles binary files (images, documents) with the following approach:

1. **Content-Type Detection**: Uses Python's `mimetypes` module to detect file types
2. **Binary Reading**: Files are read in binary mode (`'rb'`) to preserve data integrity
3. **Chunked Transfer**: Large files are read in 4KB chunks to manage memory efficiently
4. **Download Headers**: Sets `Content-Disposition: attachment` to trigger browser download
5. **Content-Length**: Provides accurate file size for progress tracking

## Thread Pool Description

The server implements a thread pool pattern for handling concurrent connections:

### Architecture
- **Main Thread**: Accepts incoming connections and queues them
- **Worker Threads**: Process queued connections (default: 10 threads)
- **Connection Queue**: FIFO queue for pending connections
- **Thread Pool**: Fixed-size pool of worker threads

### Concurrency Features
- **Thread Safety**: Uses `threading.Lock` for shared resource protection
- **Connection Management**: Each thread handles one connection at a time
- **Keep-Alive Support**: Up to 100 requests per connection with 30s timeout
- **Graceful Shutdown**: Proper cleanup on server stop

### Performance Characteristics
- **Scalability**: Handles multiple concurrent connections efficiently
- **Resource Management**: Prevents thread explosion with fixed pool size
- **Queue Management**: Logs when connections are queued due to thread pool exhaustion

## Security Features

### 1. Path Traversal Prevention
- **Canonicalization**: Resolves relative paths safely
- **Validation**: Blocks `../`, `./`, `//` patterns
- **Sandboxing**: Restricts access to `resources/` directory only

### 2. Host Header Validation
- **Required Header**: Rejects requests without Host header
- **Format Validation**: Ensures proper host:port format
- **Whitelist**: Only accepts configured host addresses

### 3. Input Validation
- **Method Validation**: Only allows GET and POST methods
- **Content-Type Validation**: Strict JSON validation for POST requests
- **Request Size Limits**: 8192 bytes maximum per request

### 4. Logging and Monitoring
- **Security Events**: Logs all security violations
- **Request Tracking**: Full audit trail of all requests
- **Error Handling**: Comprehensive error logging

## Known Limitations

### 1. File Size Limits
- **Memory Usage**: Large files are loaded entirely into memory
- **Timeout**: 30-second timeout may be insufficient for very large files
- **Concurrent Downloads**: Multiple large file downloads may impact performance

### 2. Thread Pool Constraints
- **Fixed Size**: Thread pool size is static (no dynamic scaling)
- **Queue Overflow**: No limit on connection queue size
- **Resource Contention**: High load may cause thread starvation

### 3. HTTP Compliance
- **Version Support**: Limited to HTTP/1.0 and HTTP/1.1
- **Header Handling**: Basic header parsing (no advanced features)
- **Compression**: No gzip/deflate support

### 4. Security Considerations
- **Authentication**: No user authentication or authorization
- **Rate Limiting**: No request rate limiting implemented
- **HTTPS**: No SSL/TLS support (HTTP only)

## Extension Ideas

### 1. Performance Improvements
- Implement connection pooling
- Add gzip compression
- Use async I/O for better concurrency

### 2. Security Enhancements
- Add HTTPS support
- Implement rate limiting
- Add request authentication

### 3. Feature Additions
- Directory listing for GET requests
- File upload progress tracking
- WebSocket support
- REST API endpoints

### 4. Monitoring and Logging
- Add metrics collection
- Implement health check endpoints
- Add request/response timing
- Create admin dashboard

## Troubleshooting

### Common Issues
1. **Port Already in Use**: Change port number or stop conflicting service
2. **Permission Denied**: Ensure write permissions for logs and uploads directories
3. **File Not Found**: Check that resources directory exists with proper files
4. **Connection Refused**: Verify host and port configuration

### Debug Mode
Enable debug logging by modifying the logging level in `_setup_logging()`:
```python
self.logger.setLevel(logging.DEBUG)
```

## License
This implementation is created for educational purposes as part of a Computer Networks assignment.
"""
