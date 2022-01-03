# Web streaming example
# Source code from the official PiCamera package
# http://picamera.readthedocs.io/en/latest/recipes2.html#web-streaming

# https://randomnerdtutorials.com/video-streaming-with-raspberry-pi-camera/

from configparser import NoSectionError, NoOptionError, SafeConfigParser
from datetime import datetime
from http import server
from fractions import Fraction
import io
import logging
from pathlib import Path
import socketserver
from ssl import wrap_socket
from threading import Condition
from time import sleep

import picamera

parser = SafeConfigParser()
parser.read('/etc/pi-camera.conf')

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.DEBUG)
try:
    log_file = parser.get('general', 'log_file')
except (NoOptionError, NoSectionError):
    log_file = 'camera.log'

frmt = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

fh = logging.FileHandler(log_file)
fh.setLevel(logging.DEBUG)
fh.setFormatter(frmt)
LOGGER.addHandler(fh)

sh = logging.StreamHandler()
sh.setLevel(logging.DEBUG)
sh.setFormatter(frmt)
LOGGER.addHandler(sh)

LOGGER.info('Starting Camera Process')

try:
    ENABLE_SAVE = parser.get('general', 'picture_save_enable')
    OUTPUT_DIR = parser.get('general', 'picture_save_dir')
except (NoOptionError, NoSectionError):
    ENABLE_SAVE = False
    OUTPUT_DIR = None

try:
    SSL_CERT = parser.get('general', 'ssl_certificate_file')
except (NoOptionError, NoSectionError):
    SSL_CERT = None

try:
    SERVER_PORT = int(parser.get('general', 'server_port'))
except (NoOptionError, NoSectionError):
    SERVER_PORT = 8000

try:
    TITLE = parser.get('general', 'title')
except (NoOptionError, NoSectionError):
    TITLE = 'pi-camera'

PAGE = """<html>
    <head>
        <title>{title}</title>
    </head>
    <body>
        <center><h1>{title}</h1></center>
        <center><img src="stream.mjpg" width="50%" heigh="50%"></center>
    </body>
</html>
""".format(title=TITLE)


class StreamingOutput(object):
    def __init__(self):
        self.frame = None
        self.buffer = io.BytesIO()
        self.condition = Condition()
        if ENABLE_SAVE:
            self.output_path = Path(OUTPUT_DIR)

    def write(self, buf):
        if buf.startswith(b'\xff\xd8'):
            # New frame, copy the existing buffer's content and notify all
            # clients it's available
            self.buffer.truncate()
            with self.condition:
                self.frame = self.buffer.getvalue()
                self.condition.notify_all()
            self.buffer.seek(0)
            if ENABLE_SAVE:
                output_file_name = self.output_path / f'{datetime.now().strftime("%Y-%m-%d-%H-%M-%S.%f")}.jpg'
                with open(str(output_file_name), 'wb') as file_writer:
                    file_writer.write(buf)
                LOGGER.info(f'Saving capture to file {str(output_file_name)}')
        return self.buffer.write(buf)


class StreamingHandler(server.BaseHTTPRequestHandler):
    def do_GET(self):
        LOGGER.info("GET request,\nPath: %s\nHeaders:\n%s\n", str(self.path), str(self.headers))
        if self.path == '/':
            self.send_response(301)
            self.send_header('Location', '/index.html')
            self.end_headers()

        elif self.path == '/index.html':
            content = PAGE.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)

        elif self.path == '/stream.mjpg':
            self.send_response(200)
            self.send_header('Age', 0)
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()

            try:
                while True:
                    with output.condition:
                        output.condition.wait()
                        frame = output.frame
                    self.wfile.write(b'--FRAME\r\n')
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', len(frame))
                    self.end_headers()
                    self.wfile.write(frame)
                    self.wfile.write(b'\r\n')
            except Exception as e:
                LOGGER.warning('Removed streaming client %s: %s', self.client_address, str(e))
        else:
            self.send_error(404)
            self.end_headers()

class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

with picamera.PiCamera(resolution='1296x972', framerate=32) as camera:
        output = StreamingOutput()
        camera.start_recording(output, format='mjpeg')
        try:
            address = ('', SERVER_PORT)
            server = StreamingServer(address, StreamingHandler)
            if SSL_CERT:
                server.socket = wrap_socket(server.socket,
                                            certfile=SSL_CERT,
                                            server_side=True)
            server.serve_forever()
        finally:
            camera.stop_recording()
