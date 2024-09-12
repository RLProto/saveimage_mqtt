import mqtt
import asyncio
from threading import Thread
import json
import logging
from datetime import datetime
from PIL import Image
import cv2
import os
import io
import psycopg2
from threading import Timer, Lock
import websockets
import numpy as np
import base64
import time
from concurrent.futures import ThreadPoolExecutor

# Use ThreadPoolExecutor for non-blocking saving and processing
executor = ThreadPoolExecutor(max_workers=5)

# Global variables
latest_image = None
latest_lote = None  # Global variable to store the lote value
image_lock = Lock()  # Lock for thread-safe operations on latest_image

# Retrieve environment variables from docker-compose
WS_API_URL = os.getenv("WS_API_URL", "ws://100.100.47.141:9999/inference")
DB_HOST = os.getenv("DB_HOST", "10.15.160.2")
DB_PORT = os.getenv("DB_PORT", "8080")
DB_NAME = os.getenv("DB_NAME", "papude")
DB_USER = os.getenv("DB_USER", "papude")
DB_PASSWORD = os.getenv("DB_PASSWORD", "ambev2021")

STEP_TAG = os.getenv("STEP_TAG", "1.14.37.52.1.2-1.859-1.0.212")
LOTE_TAG = os.getenv("LOTE_TAG", "1.14.37.52.1.2-1.859-1.0.7238")
PRODUCT_TAG = os.getenv("PRODUCT_TAG", "1.14.37.52.1.2-1.859-1.0.9581")

EQUIPMENT = os.getenv('EQUIPMENT', 'Decantador')
VALID_STEPS = os.getenv('VALID_STEPS', "1;0;1;1,2;0;1;2,3;30;3;3,4;0;2;4,5;0;1;5")
BASE_IMAGE_SAVE_PATH = './data'

# Additional environment variables for product change capturing
PRODUCT_CAPTURE_INTERVAL = float(os.getenv('PRODUCT_CAPTURE_INTERVAL', 18))
PRODUCT_NUM_PICTURES = int(os.getenv('PRODUCT_NUM_PICTURES', 1))  

STEPS_RULE = os.getenv("STEPS_RULE", "Soda Vision")
PRODUCT_RULE = os.getenv("PRODUCT_RULE", "Soda Vision Produto")


# Define custom logging level
IMPORTANT = 20
logging.addLevelName(IMPORTANT, "IMPORTANT")
logging.Logger.important = lambda self, message, *args, **kws: self._log(IMPORTANT, message, args, **kws) if self.isEnabledFor(IMPORTANT) else None
logging.basicConfig(level=IMPORTANT, format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger('websockets').setLevel(logging.ERROR)

# Helper functions
def ensure_directory(path):
    if not os.path.exists(path):
        os.makedirs(path)

# Function to connect to the database
def connect_db():
    try:
        connection = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD
        )
        return connection
    except Exception as e:
        logging.error(f"Failed to connect to the database: {e}")
        return None

# Function to insert image into the database with the new 'tipo' column
def compress_and_insert_image_to_db(image_path, equipment, classification, accuracy, lote, tipo):
    try:
        original_image = Image.open(image_path)
        original_image = original_image.convert("RGB")
        compressed_image_io = io.BytesIO()
        original_image.save(compressed_image_io, format="JPEG", quality=70)
        compressed_image_bytes = compressed_image_io.getvalue()

        connection = connect_db()
        if connection is None:
            return

        cursor = connection.cursor()
        insert_query = """
            INSERT INTO saved_images (date, lote, image, equipamento, classificacao, acuracia, tipo) 
            VALUES (CURRENT_TIMESTAMP, %s, %s, %s, %s, %s, %s);
        """
        cursor.execute(insert_query, (lote, psycopg2.Binary(compressed_image_bytes), equipment, classification, accuracy, tipo))
        connection.commit()
        cursor.close()
        connection.close()
        logging.info(f"Image and classification data inserted into the database: {image_path}, {classification}, {accuracy}, lote: {lote}, tipo: {tipo}")
    except Exception as e:
        logging.error(f"Failed to insert image and classification data into the database: {e}")

# Updated function to send image via WebSocket and handle response with tipo
async def send_image_to_api(image_path, lote, tipo):
    with open(image_path, "rb") as image_file:
        img_bytes = image_file.read()
        img_base64 = base64.b64encode(img_bytes).decode('utf-8')

    async with websockets.connect(WS_API_URL) as websocket:
        await websocket.send(img_base64)
        response = await websocket.recv()
        logging.info(f"Received response from server: {response}")
        
        # Parse response and extract data
        response_data = json.loads(response)
        classification = response_data.get("classification", "")
        confidence_score = response_data.get("confidence-score", 0)
        confidence_score = round(confidence_score)

        # Call database insert function with additional parameters
        compress_and_insert_image_to_db(image_path, EQUIPMENT, classification, confidence_score, lote, tipo)


def take_pictures(step, lote, num_pictures, is_product_change=False):
    # If product change, set tipo to "CIP", otherwise "Produzindo"
    tipo = "CIP" if is_product_change else "Produzindo"
    directory_suffix = "CIP" if is_product_change else step
    directory_path = os.path.join(BASE_IMAGE_SAVE_PATH, EQUIPMENT, directory_suffix)
    ensure_directory(directory_path)

    for i in range(num_pictures):
        with image_lock:
            if latest_image is None:
                logging.info("No image available to save.")
                return
            image_to_save = latest_image

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        image_path = os.path.join(directory_path, f'{lote}_{timestamp}_{i}.jpg')
        try:
            cv2.imwrite(image_path, image_to_save)
            logging.info(f"Image saved: {image_path}")
            # Pass tipo to send_image_to_api
            asyncio.run(send_image_to_api(image_path, lote, tipo))
        except Exception as e:
            logging.error(f"Failed to process image: {e}")
        time.sleep(0.47)  # Adjust this to control the pacing of images


# Parse the valid steps
def parse_valid_steps(config):
    steps = {}
    entries = config.split(',')
    for entry in entries:
        parts = entry.split(';')
        step = f"{float(parts[0]):.1f}"  # Format with one decimal place
        delay = float(parts[1])
        strategy = int(parts[2])
        num_pictures = int(parts[3]) if len(parts) > 3 else 1  # Default to 1 picture if not provided
        steps[step] = {'delay': delay, 'strategy': strategy, 'num_pictures': num_pictures}
    return steps

valid_steps = parse_valid_steps(VALID_STEPS)
logging.info(f"Valid steps loaded: {valid_steps}")

class SubHandler:
    def __init__(self):
        self.last_value = None
        self.last_product_value = 0
        self.active_timer = None
        self.last_strategy = None
        self.initial_product_change = False
        self.continuous_capture_timer = None

    def handle_value_change(self, new_value, lote):
        # Cancel the previous timer if it exists
        if self.continuous_capture_timer:
            self.continuous_capture_timer.cancel()
            self.continuous_capture_timer = None
            logging.info("Cancelled previous timer due to new valid step.")

        step_key = f"{float(new_value):.1f}"
        step_info = valid_steps.get(step_key)

        # Handle the end of a strategy 2 step (take pictures at the end of the step)
        if self.last_strategy == 2:
            if not step_info or step_info['strategy'] != 2:
                num_pictures = valid_steps.get(f"{float(self.last_value):.1f}", {}).get('num_pictures', 1)
                take_pictures(str(self.last_value), lote, num_pictures)

        # Handle the new step
        if step_info:
            strategy = step_info['strategy']
            delay = step_info['delay']
            num_pictures = step_info.get('num_pictures', 1)

            if strategy == 1:
                # Strategy 1: Take pictures at the start of the step, with optional delay
                if delay > 0:
                    self.active_timer = Timer(delay, lambda: take_pictures(step_key, lote, num_pictures))
                    self.active_timer.start()
                else:
                    take_pictures(step_key, lote, num_pictures)
            
            elif strategy == 2:
                # Strategy 2: Take pictures at the end of the step (handled in the next step change)
                pass

            elif strategy == 3:
                # Strategy 3: Continuous picture-taking during the step at intervals
                self.start_continuous_capture(step_key, delay, num_pictures, lote)

        self.last_value = new_value
        self.last_strategy = step_info['strategy'] if step_info else None

    def handle_product_change(self, product, lote):
        # Start continuous capture if product goes from positive/zero to negative
        if product < 0 and self.last_product_value >= 0:
            logging.info(f"Product value changed to negative. Starting continuous capture for lote {lote}.")
            # Pass is_product_change=True to indicate this is a product change
            self.start_continuous_capture("product_change", PRODUCT_CAPTURE_INTERVAL, PRODUCT_NUM_PICTURES, lote, is_product_change=True)
        
        # Stop continuous capture if product goes from negative to zero/positive
        elif product >= 0 and self.last_product_value < 0:
            logging.info(f"Product value changed to zero or positive. Stopping continuous capture for lote {lote}.")
            self.stop_continuous_capture()

        self.last_product_value = product


    def start_continuous_capture(self, step, interval, num_pictures, lote, is_product_change=False):
        if self.continuous_capture_timer:
            logging.info("Continuous capture is already running. Not starting a new one.")
            return

        def capture():
            take_pictures(step, lote, num_pictures, is_product_change)
            self.continuous_capture_timer = Timer(interval, capture)
            self.continuous_capture_timer.start()

        logging.info(f"Starting continuous capture for {lote} at step {step}. Interval: {interval}s, Pictures: {num_pictures}")
        capture()  # Start capturing immediately


    def stop_continuous_capture(self):
        if self.continuous_capture_timer:
            self.continuous_capture_timer.cancel()
            self.continuous_capture_timer = None
            logging.info("Continuous capture stopped.")


# MQTT callback functions
def on_mqtt_message(client, userdata, message):
    try:
        payload = json.loads(message.payload.decode('utf-8'))
        rule = payload.get("data", {}).get("rule", "")
        if rule == STEPS_RULE:
            values = payload.get("data", {}).get("values", {})
            if values:
                step_value = values.get(STEP_TAG, None)
                lote_value = values.get(LOTE_TAG, None)
                if step_value is not None and lote_value is not None:
                    logging.info(f"Step value: {step_value}, Lote: {lote_value}")
                    handler.handle_value_change(step_value, lote_value)

        elif rule == PRODUCT_RULE:
            values = payload.get("data", {}).get("values", {})
            if values:
                lote_value = values.get(LOTE_TAG, None)
                product_value = values.get(PRODUCT_TAG, None)
                if product_value is not None and lote_value is not None:
                    logging.info(f"Product value: {product_value}, Lote: {lote_value}")
                    handler.handle_product_change(product_value, lote_value)

    except json.JSONDecodeError:
        logging.error("Failed to decode MQTT message payload.")

# WebSocket handler for receiving images
async def websocket_handler(websocket, path):
    if path == "/ws/image":
        try:
            while True:
                data = await websocket.recv()
                img_bytes = base64.b64decode(data)
                img_array = np.frombuffer(img_bytes, dtype=np.uint8)
                image = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                if image is not None:
                    with image_lock:
                        global latest_image
                        latest_image = image
                    logging.getLogger().important(f"Latest image updated. Dimensions: {image.shape}")
        except websockets.exceptions.ConnectionClosed as e:
            pass
        except Exception as e:
            logging.getLogger().important(f"Unexpected error in WebSocket connection: {e}")
        finally:
            pass

# WebSocket server
async def websocket_server():
    async with websockets.serve(websocket_handler, "0.0.0.0", 8000):
        await asyncio.Future()  # This will run forever

# Main entry point
def main():
    global handler
    handler = SubHandler()

    # Start the MQTT connection
    mqtt_thread = Thread(target=mqtt.connect_mqtt, args=(on_mqtt_message,))
    mqtt_thread.start()

    # Start the WebSocket server
    asyncio.run(websocket_server())

if __name__ == '__main__':
    main()
