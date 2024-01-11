# web_server.py
from http.server import SimpleHTTPRequestHandler
from socketserver import TCPServer
import threading
import os

class CustomHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_my_headers()

    def send_my_headers(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        super().end_headers()

    def do_POST(self):
        # Handle the POST request here
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length).decode('utf-8')
        print(f'Received POST data: {post_data}')

def run_web_server():
    port = 5000
    server_address = ('localhost', port)

    httpd = TCPServer(server_address, CustomHandler)

    web_directory = os.path.join(os.path.dirname(__file__), '../web')
    os.chdir(web_directory)

    # print(f'Fusion Server, open http://localhost:{port} to see the web site')
    print(f'PyFusion Server')
    print(f'Open http://localhost:{port} to see the web site')
    try:
        server_thread = threading.Thread(target=httpd.serve_forever)
        server_thread.start()
    except KeyboardInterrupt:
        print('Server stopped.')
        httpd.server_close()

if __name__ == '__main__':
    # Run the web server in a separate thread
    run_web_server()
