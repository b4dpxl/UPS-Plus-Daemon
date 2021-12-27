Deamonised version of the `uplsplus.py` script from <https://github.com/geeekpi/upsplus>. Also supports sending stats to MQTT.

Run `pip3 install -r requirements.txt` for the dependencies.

Copy `config.sample` to `config.cfg` and edit as appropriate.

Copy `ups-poweroff` to `/lib/systemd/system-shutdown/` and `Chmod +x`

Create the service with:

```
sudo systemctl edit --force --full upsplus.service
```

and enter the contents of `upsplus.service` - change paths as necessary.

To add a monitor to Home Assistant, add an MQTT sensor as below:

```
- platform: mqtt
  name: "UPS power"
  state_topic: "upsplus/battery"
  value_template: "{{ value_json.percent }}"
  unit_of_measurement: "%"
  device_class: battery
  json_attributes_topic: "upsplus/battery"
```
