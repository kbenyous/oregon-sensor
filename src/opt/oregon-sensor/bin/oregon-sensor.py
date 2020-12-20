#!/opt/oregon-sensor/virtualenv/bin/python3
# -*- coding: UTF-8 -*-

import configparser
import paho.mqtt.client as mqtt
import sdnotify
from smbus2 import SMBus
import logging
import json
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')


def main():

    # Notifications pour SystemD
    systemd_notifier = sdnotify.SystemdNotifier()

    # Lecture de la conf
    systemd_notifier.notify('RELOADING=1')
    config = configparser.RawConfigParser()
    config.read('/etc/oregon-sensor/oregon-sensor.conf')

    # Configuration du client mqtt
    mqtt_broker_hostname = config.get('mqtt_broker', 'hostname', fallback='localhost')
    mqtt_broker_port = config.getint('mqtt_broker', 'port', fallback=1883)
    mqtt_client_name = config.get('mqtt_broker', 'client_name', fallback='Oregon-Sensor')
    logging.info("Connecting to MQTT broker {}:{}...".format(mqtt_broker_hostname, mqtt_broker_port))

    # Get channel names
    channel_names = dict()
    for i in range(1, 4):
        channel_names[str(i)] = config.get('oregon_sensor', 'channel_' + str(i) + '_name', fallback=str(i))

    # Configuration du bus I2C
    message_size = config.getint('oregon_sensor', 'i2c_msg_size', fallback=25)
    arduino_address = config.getint('oregon_sensor', 'i2c_sensor_address', fallback=4)

    # Définition des files d'entrée / sortie
    data_queue = config.get('oregon_sensor', 'data_queue', fallback="house/sensors/weather/{}")
    status_queue = config.get('oregon_sensor', 'status_queue', fallback="house/probes/oregon-sensor/status")

    # Configuration du client mqtt
    client = mqtt.Client(mqtt_client_name)
    client_user_data = dict()
    client_user_data["status_queue"] = status_queue
    client.user_data_set(client_user_data)
    client.will_set(status_queue, payload="Connection Lost", qos=2, retain=True)
    client.on_connect = on_connect
    client.connect_async(mqtt_broker_hostname, mqtt_broker_port)
    client.loop_start()
    systemd_notifier.notify('READY=1')

    with SMBus(1) as i2cbus:
        while True:
            for channel in range(1, 4):
                systemd_notifier.notify('WATCHDOG=1')
                try:

                    logging.debug("Requesting data for channel {}".format(channel))
                    data = i2cbus.read_i2c_block_data(arduino_address, channel, message_size)

                    if(len(data) > 0 and data[0] > 0):
                        logging.debug("Getting updated data from channel {}".format(channel))
                        message = dict()

                        # Temperature
                        sign = -1 if (data[6] & 0x8) else 1
                        temp = ((data[5] & 0xF0) >> 4)*10 + (data[5] & 0xF) + (float)(((data[4] & 0xF0) >> 4) / 10.0)
                        temperature = sign * temp
                        message['Temperature'] = str(temperature)

                        # Humidity
                        if(data[0] == 0x1A and data[1] == 0x2D):
                            humidity = (data[7] & 0xF) * 10 + ((data[6] & 0xF0) >> 4)
                            message['Humidity'] = str(humidity)

                        # Battery
                        message['Battery'] = "10" if (data[4] & 0x4) else "90"

                        # Channel
                        message['Channel'] = "1" if data[2] == 0x10 else "2" if data[2] == 0x20 else "3"

                        # Sensor ID
                        message['Id'] = hex(data[3])

                        # Room (from service configuration)
                        message['Room'] = channel_names[str(message['Channel'])]

                        logging.debug(json.dumps(message))
                        client.publish(data_queue.format(message['Room']), payload=json.dumps(message), qos=0)
                except OSError as e:
                    logging.error(e)
                time.sleep(20)


def on_connect(client, userdata, flags, rc):
    logging.info("Connected to broker")
    client.publish(userdata["status_queue"], payload="Connected", qos=2, retain=True)


if __name__ == '__main__':
    main()
