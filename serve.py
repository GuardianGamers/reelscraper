#!/usr/bin/env python3
"""
Simple web server that serves the video stories HTML at the root URL
"""

import http.server
import socketserver
from pathlib import Path

PORT = 8000
HTML_FILE = "all_video_stories_presigned.html"

class CustomHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        # Redirect root to the HTML file
        if self.path == '/' or self.path == '':
            self.path = '/' + HTML_FILE
        return super().do_GET()

def main():
    # Check if HTML file exists
    if not Path(HTML_FILE).exists():
        print(f"❌ Error: {HTML_FILE} not found!")
        print(f"   Run: python3 generate_presigned_urls.py")
        return 1
    
    Handler = CustomHandler
    
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print("🌐 GuardianGamer Video Stories Server")
        print("=" * 50)
        print(f"📺 Open in your browser: http://localhost:{PORT}")
        print("=" * 50)
        print("\nPress Ctrl+C to stop the server\n")
        
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n\n👋 Server stopped")
            return 0

if __name__ == "__main__":
    exit(main())

