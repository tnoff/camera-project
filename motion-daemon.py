#from gpiozero import MotionSensor
#
#pir = MotionSensor(4)
#
#while True:
#    pir.wait_for_motion()
#    print('Movement')
#    pir.wait_for_no_motion()
from configparser import NoSectionError, NoOptionError, SafeConfigParser

import click
import daemon

@click.command()
@click.option('--settings-file', '-s', default='/etc/pi-camera.conf')
def main():
    try:
        input_dir = parser.get('general', 'picture_save_dir')
    except (NoOptionError, NoSectionError):
        raise Exception('No input dir, nothing to do')
    with daemon.DaemonContext():
        pass

if __name__ == '__main__':
    main()