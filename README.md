Deamonised version of the `uplsplus.py` script from <https://github.com/geeekpi/upsplus>. Also supports sending stats to MQTT.

Run `pip3 install -r requirements.txt` for the dependencies.

copy `ups-poweroff` to `/lib/systemd/system-shutdown/` and `chmod +x`

Create the service with:

```
sudo systemctl edit --force --full upsplus.service
```

and enter the contents of `upsplus.service` - change paths as necessary.
