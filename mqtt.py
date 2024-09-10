import os
import time
import logging
import paho.mqtt.client as mqtt

# Fixed MQTT broker details
MQTT_BROKER = "10.15.160.13"
MQTT_PORT = 1883

# MQTT topics from environment variables
MQTT_TOPIC_STEP = os.getenv("MQTT_TOPIC_STEP", "D2C/1/14/37/52/1/2-1/859-1/0")

def on_mqtt_connect(client, userdata, flags, rc):
    if rc == 0:
        logging.info("Successfully connected to MQTT broker")
        client.subscribe(MQTT_TOPIC_STEP)
        client.subscribe(MQTT_TOPIC_PRODUCT)
    else:
        logging.error(f"Failed to connect to MQTT broker, return code {rc}")

def on_mqtt_disconnect(client, userdata, rc):
    if rc != 0:
        logging.warning("Disconnected from MQTT broker, attempting to reconnect...")
        reconnect_mqtt(client)

def reconnect_mqtt(client):
    while True:
        try:
            logging.info("Attempting to reconnect to MQTT broker...")
            client.reconnect()
            logging.info("Reconnected to MQTT broker")
            break
        except Exception as e:
            logging.error(f"Failed to reconnect: {e}")
            time.sleep(5)

def connect_mqtt(on_mqtt_message):
    client = mqtt.Client()

    client.on_connect = on_mqtt_connect
    client.on_disconnect = on_mqtt_disconnect
    client.on_message = on_mqtt_message  # Use the callback passed from main.py

    while True:
        try:
            logging.info(f"Connecting to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}")
            client.connect(MQTT_BROKER, MQTT_PORT, 60)
            client.loop_start()  # Start the loop in a non-blocking manner
            break
        except Exception as e:
            logging.error(f"Error connecting to MQTT broker: {e}")
            time.sleep(5)
