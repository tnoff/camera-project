# Camera Project

Project for basic pi-hole camera.

## Camera Daemon

Run camera as a daemon, will stream to given port. Also supports https with proper certs.

### Example Config

Config location */etc/pi-camera.conf*

```
[general]
log_file=/var/log/camera/camera.log
picture_save_enable = True
picture_save_dir = /opt/camera/picture-saves
ssl_certificate_file = /opt/camera/certs/combined.pem
server_port = 443
title = Front Door
```