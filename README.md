# Camera Project

Project for basic pi-hole camera & motion sensor.

## Camera Daemon

Run camera w/ motion sensor that takes picture periodically and video when motion detected.

### Example Config

Config location */etc/pi-camera.conf*

```
[general]
log_file=/var/log/camera/camera.log
media_save_dir = /opt/camera/media-saves

[camera]
framerate=6

[sensor]
queue_length=8
sample_rate=4
threshold=.6

[watcher]
log_file=/var/log/camera/watcher.log
```

### Example systemd job

```
root@front-door:~# cat /etc/systemd/system/camera.service
[Unit]
Description=camera Service
After=multi-user.target

[Service]
Type=idle
User=root
ExecStart=/opt/camera/venv/bin/python /opt/camera/camera-daemon.py
Restart=always

[Install]
WantedBy=multi-user.target
root@front-door:~#
```