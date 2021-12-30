#!/usr/bin/env python3

import argparse
import configparser
import json
import os
import time
import smbus2
import sys

from ina219 import INA219,DeviceRangeError
from termcolor import colored
from threading import Thread
from typing import Tuple

__version__ = "0.0.1"

parser = argparse.ArgumentParser(description="GeeekPi UPS+ daemon ({})".format(__version__))
parser.add_argument("-v", "--verbose", dest="verbose", help="Verbose output", required=False, action="store_true")
parser.add_argument('--version', '-V', action='version', version='%(prog)s {}'.format(__version__))
args = parser.parse_args()


print(__file__)
CONF_FILE = "{}/config.cfg".format(os.path.dirname(os.path.realpath(__file__)))
config = configparser.ConfigParser()
config.read(CONF_FILE)

# UPS+ config
DEVICE_BUS = config.getint('UPS', 'DEVICE_BUS')
addr = config.get('UPS', 'DEVICE_ADDR')
if addr.strip().lower().startswith('0x'):
    DEVICE_ADDR = int(addr, 16)
else:    
    DEVICE_ADDR = int(addr)
PROTECT_VOLT = config.getint('UPS', 'PROTECT_VOLT')
POWER_OFF = config.getint('UPS', 'POWER_OFF')
SAMPLE_PERIOD = config.getint('UPS', 'SAMPLE_PERIOD')
##UPS_POWER_OFF = config.getint('UPS', 'UPS_POWER_OFF')

# display debug/verbose messages
DEBUG = args.verbose

log = os.fdopen(sys.stdout.fileno(), 'wb', 0)
_error = lambda x: log.write("\033[91m[!]\033[0m {}\n".format(x).encode())
_ok = lambda x: log.write("\033[92m[+]\033[0m {}\n".format(x).encode())
_warn = lambda x: log.write("\033[93m[~]\033[0m {}\n".format(x).encode())
_info = lambda x: log.write("\033[94m[*]\033[0m {}\n".format(x).encode())
__debug = lambda x: log.write("\033[90m[ ]\033[0m {}\n".format(x).encode())

def _debug(s):
    if DEBUG:
        __debug(s)

# MQTT
try:
    import paho.mqtt.client as mqtt
    HAS_MQTT = True
except:
    _debug("Paho MQTT not available")
    HAS_MQTT = False

if HAS_MQTT:
    _debug("Configuring MQTT")
    if config.has_section('MQTT'):
        try:
            config['MQTT']['CLIENT_ID']
            config['MQTT']['SERVER']
            config['MQTT']['PORT']
            config['MQTT']['USER']
            config['MQTT']['PASS']
            config['MQTT']['TOPIC']
            _info("MQTT config available")
    
        except KeyError:
            _warn("MQTT configuration problem")
            HAS_MQTT = False
    
    else:
        _debug("MQTT not configured")
        HAS_MQTT = False

class UPSThread(Thread):

    _running = True
    _mqtt = None

    def __init__(self):
        Thread.__init__(self)
        # Instance INA219 and getting information from it.
        self.ina_supply = INA219(0.00725, address=0x40, busnum=DEVICE_BUS)
        self.ina_supply.configure()

        # Batteries information
        self.ina_batt = INA219(0.005, address=0x45, busnum=DEVICE_BUS)
        self.ina_batt.configure()

        # Raspberry Pi Communicates with MCU via i2c protocol.
        self.bus = smbus2.SMBus(DEVICE_BUS)

        self._setup_mcu()

        _info("Checking every {} seconds".format(SAMPLE_PERIOD))

        if HAS_MQTT:
            self._mqtt = MQTT()
            self._mqtt.connect()

    def _setup_mcu(self) -> None:
        # Enable Back-to-AC function.
        # Enable: write 1 to register 0x19 == 25
        # Disable: write 0 to register 0x19 == 25
        self.bus.write_byte_data(DEVICE_ADDR, 25, 1)
        _ok("Enabled power-on on AC restore")

        # Reset Protect voltage
        self.bus.write_byte_data(DEVICE_ADDR, 17, PROTECT_VOLT & 0xFF)
        self.bus.write_byte_data(DEVICE_ADDR, 18, (PROTECT_VOLT >> 8)& 0xFF)
        _ok("Set protection voltage to {}mV\n    Will power off at {}mV".format(PROTECT_VOLT, PROTECT_VOLT + POWER_OFF))

    def _is_charging(self) -> Tuple[bool, str]:  # this doesn't seem to work, it's showing Micro USB regardless of anything else
        aReceiveBuf = []
        aReceiveBuf.append(0x00)

        # Read register and add the data to the list: aReceiveBuf
        for i in range(1, 255):
            aReceiveBuf.append(self.bus.read_byte_data(DEVICE_ADDR, i))

        if (aReceiveBuf[8] << 8 | aReceiveBuf[7]) > 4000:
            return True, "USB-C"

        elif (aReceiveBuf[10] << 8 | aReceiveBuf[9])> 4000:
            return True, "micro USB"

        else:
            return False, None

    def run(self):
        while True:
            self._check_battery()
            for _ in range(SAMPLE_PERIOD):
                if not self._running:
                    return
                time.sleep(1)

    def stop(self):
        self._running = False

        if self._mqtt:
            self._mqtt.stop()

    __last_print_info_time = 0
    __batt_voltage = 0
    __charging_state = False
    __low_voltage_notified = False

    def _check_battery(self):
        _debug("Checking battery")
        batt_voltage = self.ina_batt.voltage()
        try:
            batt_voltage = float(batt_voltage)
            if batt_voltage == 0:
                _error("Bad battery voltage: {}".format(batt_voltage))
            else:

#                try:
#                    _debug(self._is_charging())
#                    charging, mode = self._is_charging()
#                    charging = not self.ina_supply.current() > 0  # assuming charging if current > 0
#                    _debug(self.ina_supply.current())
#
#                except OSError as e:
#                    _error("Unable to read charging state from I2C: {}".format(e))
#                    charging = self.ina_supply.current() > 0  # assuming charging if current > 0
#                    mode = "Unknown"

                self.__batt_current = self.ina_batt.current()
#                _debug((self.ina_supply.current(), self.__batt_current, self.ina_supply.current() + self.__batt_current))
                charging = self.ina_supply.current() + self.__batt_current > 0  # charging if current - discharge > 0

                # print info every 10 minutes, if the battery voltage changes, or if the charging state changes
                if time.time() - self.__last_print_info_time > (60 * 10) or not self.__batt_voltage == round(batt_voltage, 1) or not self.__charging_state == charging:
                    self.__last_print_info_time = time.time()
                    self.__batt_voltage = round(batt_voltage, 1)
                    self.__charging_state = charging
                    self._print_info()
   
                if charging:
#                    _debug("Charging on " + mode)
                    self.__low_voltage_notified = False  # charging so reset any warnings
                    return

                if (batt_voltage * 1000) < (PROTECT_VOLT + POWER_OFF):
                    _error("""Battery below  power off voltage ({:.2f}), shutting down!!""".format(batt_voltage))

                    # power off UPS in `UPS_POWER_OFF` seconds
                    # Not needed if using a script in /lib/systemd/system-shutdown/ups-poweroff
                    #_error("""Battery below  power off voltage ({:.2f}), shutting down!! UPS will shutdown in {} seconds""".format(batt_voltage, UPS_POWER_OFF))
                    # self.bus.write_byte_data(DEVICE_ADDR, 24, UPS_POWER_OFF)

                    os.system("sudo sync && sudo halt")
                    while True:
                        time.sleep(10)

                else:
                    if not self.__low_voltage_notified and (batt_voltage * 1000) < (PROTECT_VOLT + POWER_OFF + 200):
                        self.__low_voltage_notified = True
                        _warn("Battery approaching power off voltage: {:.2f}".format(batt_voltage))

        except ValueError:
            _error("Bad battery voltage: {}".format(batt_voltage))

        except OSError as e:
            _error("Unable to read i2c: {}".format(e))

    def _print_info(self):
        _info(time.asctime())
        supply_current = self.ina_supply.current()
        _info(
            """Supply voltage: {:.2f}v
    Pi current draw: {:.2f}mA""".format(self.ina_supply.voltage(), supply_current)
        )
            
        _info(
            """Battery voltage: {:.2f}v
    {}harging at {:.2f}mA""".format(self.__batt_voltage, "C" if self.__charging_state else "Disc", self.__batt_current)
        )
                        
        if HAS_MQTT:
            _info("Sending to MQTT")
            self._mqtt.publish(
                config['MQTT']['TOPIC'],
                json.dumps({
                    "charging": self.__charging_state,
                    "charge_current": round(supply_current, 2),
                    "voltage": self.__batt_voltage,
                    "current": round(self.__batt_current, 2),
                    "percent": int((self.__batt_voltage * 100 - 320))
                }),
                retain=False
            )


t = None

def die(code=0):
    print("Shutting down")
    if t:
        t.stop()
    sys.exit(code)


class MQTT:
    state = ""
    target = 0
    actual = 0
    away = False
    reconnect = False

    def __init__(self):
        self.client = mqtt.Client(config['MQTT']['CLIENT_ID'])

    def connect(self):
        self.client.username_pw_set(config['MQTT']['USER'], config['MQTT']['PASS'])
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect
        _info("Connecting to MQTT")
        for i in range(10):
            try:
                self.client.connect(config['MQTT']['SERVER'], port=config.getint('MQTT', 'PORT'))
                self.client.loop_start()
                # connected OK
                return
#            except KeyboardInterrupt:
#                die()
            except Exception as ex:
                _error("Can't connect because:\n {}".format(ex))
                w = 30 * (i + 1)
                _error("Waiting {} seconds to retry".format(w))
                time.sleep(w)

#            die(1)

    def disconnect(self):
        self.client.disconnect()

    def publish(self, topic, payload, retain=True):
        self.client.publish(topic, payload, retain=retain)
        _debug("Published {} to {}".format(payload, topic))

    def _on_connect(self, client, userdata, flags, rc):
        _debug("Connection returned code={}".format(rc))
        if rc == 0:
            if self.reconnect:
                _info("Reconnected to MQTT")
            else:
                _info("Connected to MQTT")

            if not self.reconnect:
                self.reconnect = True

        else:
            _error("Bad connection Returned code={}".format(rc))

    def _on_disconnect(self, client, userdata, rc):
        if rc != 0:
            warn("Unexpected disconnect. Will reconnect")

    def _on_message(self, client, userdata, message):
        _debug("Message received")
        _debug("{}: {}".format(message.topic, message.payload))

    def stop(self):
        self.client.loop_stop()


t = UPSThread()

def main():
    try:
        t.start()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        die(0)

main()

