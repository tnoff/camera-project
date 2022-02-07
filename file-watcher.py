from configparser import NoSectionError, NoOptionError, SafeConfigParser
from datetime import datetime
from logging import Formatter, getLogger, StreamHandler, DEBUG
from logging.handlers import RotatingFileHandler
from pathlib import Path
from time import sleep

import click

DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S,%f'

def read_settings_file(settings_file):
    path = Path(settings_file)
    if not path.exists():
        return {}

    parser = SafeConfigParser()
    parser.read(str(path))

    return_dict = {}
    config_options = {
        'log_file': {
            'path' : ['watcher', 'log_file'],
            'default': None,
            'type': 'path'
        },
        'output_dir': {
            'path': ['general', 'media_save_dir'],
            'default': None,
            'type': 'path',
        },
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

    while True:
        now = datetime.now()
        logger.debug('Checking for files to delete')
        for file_path in output_dir_path.glob('**/*'):
            last_modified = file_path.stat().st_mtime
            if (now - datetime.fromtimestamp(last_modified)).days > 1:
                logger.info(f'File path "{str(file_path)}" too old, deleting')
                file_path.unlink()
        sleep(60)

if __name__ == '__main__':
    main()