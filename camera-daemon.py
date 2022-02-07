# https://randomnerdtutorials.com/video-streaming-with-raspberry-pi-camera/
from configparser import NoSectionError, NoOptionError, SafeConfigParser
from copy import deepcopy
from datetime import datetime
from enum import Enum
from fractions import Fraction
from http.server import HTTPServer, BaseHTTPRequestHandler
from io import BytesIO
from logging import Formatter, getLogger, StreamHandler, DEBUG
from logging.handlers import RotatingFileHandler
from pathlib import Path
from socketserver import ThreadingMixIn
from threading import Condition
import ssl
from time import sleep

import click
from picamera import PiCamera
import requests

PAGE='''<html>
<head>
<title>Front Door</title>
</head>
<body>
<center><h1>Front Door</h1></center>
<center><img src="stream.mjpg"></center>
</body>
</html>
'''

DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S,%f'

def openweather_get_sunrise_sunset(logger, openweather_api_key, openweather_location_id):
    url = f'https://api.openweathermap.org/data/2.5/weather?appId={openweather_api_key}&id={openweather_location_id}'
    req = requests.get(url)
    if req.status_code != 200:
        logger.warning(f'Invalid status code for weather api {req.status_code}, {req.text}')
        return None, None
    return datetime.fromtimestamp(req.json()['sys']['sunrise']), datetime.fromtimestamp(req.json()['sys']['sunset']) 


class CameraMode(Enum):
    Day = 'day'
    Night = 'night'

class StreamingOutput(object):
    def __init__(self, picture_path, framerate, logger):
        self.frame = None
        self.buffer = BytesIO()
        self.condition = Condition()
        self.picture_path = picture_path
        self.framerate = framerate
        self.last_picture_taken = datetime.now().timestamp()
        self.logger = logger
        self.shutdown_called = False

    def write(self, buf):
        if not self.shutdown_called:
            now = datetime.now()
            if (now.timestamp() - self.last_picture_taken) >= ( 1.0 / self.framerate):
                file_path = self.picture_path / f'{now.strftime(DATETIME_FORMAT)}.jpg'
                self.logger.debug(f'Saving frame to picture file {str(file_path)}')
                file_path.write_bytes(buf)
                self.last_picture_taken = now.timestamp()

        if buf.startswith(b'\xff\xd8'):
            # New frame, copy the existing buffer's content and notify all
            # clients it's available
            self.buffer.truncate()
            with self.condition:
                self.frame = self.buffer.getvalue()
                self.condition.notify_all()
            self.buffer.seek(0)
        return self.buffer.write(buf)

class StreamingServer(ThreadingMixIn, HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address, logger, output, camera,
                 openweather_api_key=None, openweather_location_id=None):
        
        super().__init__(server_address, generate_handler(output))
        self.openweather_api_key = openweather_api_key
        self.openweather_location_id = openweather_location_id
        self.last_openweather_check = datetime.now()
        self.sunrise = None
        self.sunset = None
 
        self.logger = logger
        self.output = output
        # Default should always be "daylight" mode
        self.mode = CameraMode.Day

        self.camera = camera
        self.original_framerate = deepcopy(self.camera.framerate)
        self.original_shutter_speed = deepcopy(self.camera.shutter_speed)
        self.original_iso = deepcopy(self.camera.iso)
        self.original_expose_mode = deepcopy(self.camera.exposure_mode)
        self.camera.start_recording(self.output, format='mjpeg')

    def service_actions(self, *args, **kwargs):
        if not self.openweather_api_key:
            return
        self.logger.debug('Checking if should put server in day or night mode')
        now = datetime.now()
        # Check if we should just take cached value
        if (now - self.last_openweather_check).seconds > (60 * 60 * 4) or self.sunrise is None:
            self.logger.debug('Checking openweather api for sunset/sunrise data')
            self.sunrise, self.sunset = openweather_get_sunrise_sunset(self.logger,
                                                                       self.openweather_api_key,
                                                                       self.openweather_location_id)
        # If mode was day and need to switch, stop
        if self.mode == CameraMode.Day and (now < self.sunrise or now > self.sunset):
            self.logger.debug('Switching camera to night mode, calling shutdown')
            self.mode = CameraMode.Night
            self.output.shutdown_called = True
            self.camera.stop_recording()
            framerate = Fraction(1, 6)
            self.output.framerate = framerate
            self.camera.framerate = framerate
            self.camera.shutter_speed = 6000000
            self.camera.iso = 800
            self.logger.debug('Waiting for 30 seconds for camera exposure')
            sleep(30)
            self.camera.exposure_mode = 'off'
            self.output.shutdown_called = False
            self.camera.start_recording(self.output, format='mjpeg')
        elif self.mode == CameraMode.Night and (now > self.sunrise and now < self.sunset):
            self.logger.debug('Switching to day mode, calling shutdown')
            self.mode = CameraMode.Day
            self.output.shutdown_called = True
            self.camera.stop_recording()
            framerate = self.original_framerate
            self.output.framerate = framerate
            self.camera.framerate = framerate
            self.camera.shutter_speed = self.original_shutter_speed
            self.camera.iso = self.original_iso
            self.camera.exposure_mode = self.original_expose_mode
            self.camera.start_recording(self.output, format='mjpeg')

    def shutdown(self):
        super().shutdown()
        self.camera.stop_recording()

def generate_handler(output):
    class StreamingHandler(BaseHTTPRequestHandler):
        def do_GET(self):
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
                    print(f'Removed streaming client {self.client_address}, {str(e)}')
            else:
                self.send_error(404)
                self.end_headers()
    return StreamingHandler



def read_settings_file(settings_file):
    path = Path(settings_file)
    if not path.exists():
        return {}

    parser = SafeConfigParser()
    parser.read(str(path))

    return_dict = {}
    config_options = {
        'log_file': {
            'path' : ['general', 'log_file'],
            'default': None,
            'type': 'path'
        },
        'output_dir': {
            'path': ['general', 'media_save_dir'],
            'default': None,
            'type': 'path',
        },
        'camera_resolution': {
            'path': ['camera', 'resolution'],
            'default': '1296x972',
            'type': 'string',
        },
        'camera_framerate': {
            'path': ['camera', 'framerate'],
            'default': 12,
            'type': 'integer',
        },
        'ssl_certificate_file': {
            'path': ['ssl', 'cert_file'],
            'default': None,
            'type': 'path',
        },
        'ssl_key_file': {
            'path': ['ssl', 'key_file'],
            'default': None,
            'type': 'path',
        },
        'openweather_api_key': {
            'path': ['openweather', 'api_key'],
            'default': None,
            'type': 'string',
        },
        'openweather_location_id': {
            'path': ['openweather', 'location_id'],
            'default': None,
            'type': 'string',
        }
    }
    for key, value in config_options.items():
        try:
            return_dict[key] = parser.get(*value['path'])
        except (NoOptionError, NoSectionError):
            return_dict[key] = value['default']
            continue
        if value['type'] == 'path':
            return_dict[key] = Path(return_dict[key])
        elif value['type'] == 'integer':
            return_dict[key] = int(return_dict[key])
        elif value['type'] == 'float':
            return_dict[key] = float(return_dict[key])
    return return_dict

@click.command()
@click.option('--settings-file', '-s', default='/etc/pi-camera.conf')
def main(settings_file):
    settings = read_settings_file(settings_file)

    logger = getLogger(__name__)
    logger.setLevel(DEBUG)
    frmt = Formatter('%(asctime)s - %(levelname)s - %(message)s')
    if settings['log_file']:
        settings['log_file'].parent.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(str(settings['log_file']), backupCount=3, maxBytes=(2 ** 20) * 10)
        fh.setLevel(DEBUG)
        fh.setFormatter(frmt)
        logger.addHandler(fh)

    sh = StreamHandler()
    sh.setLevel(DEBUG)
    sh.setFormatter(frmt)
    logger.addHandler(sh)

    if settings['output_dir']:
        output_dir_path = Path(settings['output_dir'])
        output_dir_path.mkdir(parents=True, exist_ok=True)
    else:
        raise Exception('No input dir given')

    picture_dir = output_dir_path / 'pictures'
    picture_dir.mkdir(parents=True, exist_ok=True)
    port = 8000
    if settings['ssl_certificate_file']:
        port = 443
    logger.info(f'Starting up motion sensor and camera with settings {settings}')

    while True:
        logger.info('Entering camera loop')
        camera = PiCamera(resolution=settings['camera_resolution'], framerate=settings['camera_framerate'])
        output = StreamingOutput(picture_dir, settings['camera_framerate'], logger)
        address = ('', port)
        server = StreamingServer(address, logger, output, camera,
                                openweather_api_key=settings['openweather_api_key'],
                                openweather_location_id=settings['openweather_location_id'])
        if settings['ssl_certificate_file']:
            server.socket = ssl.wrap_socket(server.socket,
                                            certfile=settings['ssl_certificate_file'],
                                            keyfile=settings['ssl_key_file'],
                                            server_side=True)
        server.serve_forever(poll_interval=5)

if __name__ == '__main__':
    main()