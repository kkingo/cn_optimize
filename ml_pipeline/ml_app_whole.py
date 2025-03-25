import os
import pickle
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.datasets import fetch_openml
from flask import Flask, request, jsonify
import threading
import logging
import requests
import copy

# ======================
# Logging configuration
# ======================
log_file = "app.log"
logger = logging.getLogger("MyLogger")
logger.setLevel(logging.DEBUG)

file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
file_handler.setLevel(logging.DEBUG)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

logger.addHandler(file_handler)
logger.addHandler(console_handler)

# ===========================
# Global configuration values
# ===========================
REPLICATION = 4  # Number of times to send/receive data
DATA_SPLIT = 0.6 # Train/test split ratio

# 下面这几个全局列表（或字典），用于在接收时缓存数据。
# 当某个角色接收端收到的数据达到了 REPLICATION 次数后，再进行后续的操作，然后清空缓存。
received_raw_data_list = []
received_train_data_list = []
received_test_data_list = []
received_model_list = []

# 线程锁，避免多线程同时操作全局变量
data_lock = threading.Lock()

# ===========================
# Data download and preprocess functions
# ===========================
def download_data():
    logger.info("Fetching data...")
    if os.path.exists('mnist_X.npy') and os.path.exists('mnist_y.npy'):
        logger.info('Hitting cache. Loading data from local file...')
        X = np.load('mnist_X.npy')
        y = np.load('mnist_y.npy')
    else:
        mnist = fetch_openml('mnist_784', version=1, as_frame=False, parser="pandas")
        X, y = mnist.data, mnist.target.astype(np.int32)
        logger.info("Data prepared from openml")
    X = X.reshape(-1, 28, 28)
    return {'X': X, 'y': y}

def preprocess_data(data):
    """
    Preprocess data: flatten images, normalize and split.
    """
    X = data['X'].reshape((-1, 28 * 28)).astype('float32') / 255.0
    y = data['y']
    split = int(DATA_SPLIT * len(X))
    return {'X': X[:split], 'y': y[:split]}, {'X': X[split:], 'y': y[split:]}

# ===========================
# Flask Application
# ===========================
app = Flask(__name__)

# ---------------------------
# Download module (ROLE=download)
# ---------------------------
def download_handler():
    @app.route('/start', methods=['GET'])
    def handle_start():
        """
        Download role entry point.
        This endpoint downloads the data (or loads from cache)
        and then sends it REPLICATION times to the Preprocess module.
        """
        raw_data = download_data()
        next_host = os.environ['NEXT_HOST']  # e.g. "mlpipe-preprocess"
        next_port = os.environ['NEXT_PORT']  # e.g. "5001"
        url = f"http://{next_host}:{next_port}/receive"

        # Serialize data
        payload = pickle.dumps({'data': raw_data})
        logger.info(f"Data size to be sent: {len(payload) / (1024 * 1024)} MB")

        # Send the same data multiple times according to REPLICATION
        # so that the receiver can accumulate them.
        success_count = 0
        for i in range(REPLICATION):
            try:
                response = requests.post(url, data=payload, headers={"Content-Type": "application/octet-stream"})
                if response.status_code == 200:
                    logger.info(f"Data sent successfully (iteration {i+1}).")
                    success_count += 1
                else:
                    logger.error(f"Failed to send data on iteration {i+1}: {response.text}")
            except Exception as e:
                logger.error(f"Error sending data on iteration {i+1}: {e}")

        if success_count == REPLICATION:
            return jsonify({"status": f"data sent successfully {REPLICATION} times"}), 200
        else:
            return jsonify({"status": "partial failure"}), 500

    logger.info("Download module is running on port 5000")
    app.run(host='0.0.0.0', port=5000)

# ---------------------------
# Preprocess module (ROLE=preprocess)
# ---------------------------
def preprocess_handler():
    @app.route('/receive', methods=['POST'])
    def receive_data():
        """
        Preprocess module receiver.
        Accumulate data until we receive REPLICATION times, then do the preprocess step once.
        After that, send the processed train/test data to the next modules, each repeated REPLICATION times.
        """
        global received_raw_data_list
        raw_payload = request.data
        data_dict = pickle.loads(raw_payload)
        raw_data = data_dict['data']

        # Accumulate data in a global list
        with data_lock:
            received_raw_data_list.append(raw_data)
            logger.info(f"Received raw data. Current count = {len(received_raw_data_list)} / {REPLICATION}")

            # Check if we have reached REPLICATION times
            if len(received_raw_data_list) < REPLICATION:
                # Not enough data yet, just return
                return jsonify({"status": "data received but waiting for more"}), 200
            else:
                # We have reached REPLICATION times data,
                # Merge or pick one (depending on actual requirements).
                # 这里假设所有重复数据是一样的，只需拿第一份做处理。如果想合并，可以自行合并逻辑。
                logger.info("All replication data received. Starting preprocessing...")

                # For simplicity, we just pick the first piece. If you want to combine them, implement logic here.
                data_to_process = received_raw_data_list[0]

                # Clear the list to be ready for next cycle
                received_raw_data_list = []

        # Perform preprocessing
        train_data, test_data = preprocess_data(data_to_process)

        # Send train data to train module
        train_host = os.environ['TRAIN_HOST']   # e.g., "mlpipe-train"
        train_port = os.environ['TRAIN_PORT']   # e.g., "5002"
        url_train = f"http://{train_host}:{train_port}/receive"
        payload_train = pickle.dumps({'data': train_data})
        logger.info(f"Sending train data to {url_train}, size {len(payload_train) / (1024 * 1024)} MB")

        # Repeat sending REPLICATION times
        for i in range(REPLICATION):
            r_train = requests.post(url_train, data=payload_train, headers={"Content-Type": "application/octet-stream"})
            if r_train.status_code == 200:
                logger.info(f"Train data sent successfully (iteration {i+1}).")
            else:
                logger.error(f"Failed to send train data on iteration {i+1}: {r_train.text}")

        # Send test data to test module
        test_host = os.environ['TEST_HOST']     # e.g., "mlpipe-test"
        test_port = os.environ['TEST_PORT']     # e.g., "5003"
        url_test = f"http://{test_host}:{test_port}/receive_test"
        payload_test = pickle.dumps({'data': test_data})
        logger.info(f"Sending test data to {url_test}, size {len(payload_test) / (1024 * 1024)} MB")

        for i in range(REPLICATION):
            r_test = requests.post(url_test, data=payload_test, headers={"Content-Type": "application/octet-stream"})
            if r_test.status_code == 200:
                logger.info(f"Test data sent successfully (iteration {i+1}).")
            else:
                logger.error(f"Failed to send test data on iteration {i+1}: {r_test.text}")

        return jsonify({"status": "preprocessing complete and data sent"}), 200

    logger.info("Preprocess module is running on port 5001")
    app.run(host='0.0.0.0', port=5001)

# ---------------------------
# Train module (ROLE=train)
# ---------------------------
def train_handler():
    @app.route('/receive', methods=['POST'])
    def receive_train_data():
        """
        Train module receiver.
        Accumulate the training data until we have REPLICATION copies,
        then do training once. After training completes, replicate the model to test module REPLICATION times.
        """
        global received_train_data_list
        raw_payload = request.data
        data_dict = pickle.loads(raw_payload)
        train_data = data_dict['data']

        # Accumulate train data
        with data_lock:
            received_train_data_list.append(train_data)
            logger.info(f"Received train data. Current count = {len(received_train_data_list)} / {REPLICATION}")

            if len(received_train_data_list) < REPLICATION:
                return jsonify({"status": "train data received but waiting for more"}), 200
            else:
                # We have reached REPLICATION times
                logger.info("All train data replications received. Starting model training...")
                # Again, assume all repeated data are the same, so we use the first
                data_to_train = received_train_data_list[0]
                # Clear the list
                received_train_data_list = []

        # Train the model
        model = LogisticRegression(max_iter=1000)
        model.fit(data_to_train['X'], data_to_train['y'])
        serialized_model = pickle.dumps(model)
        logger.info(f"Model trained. Serialized model size: {len(serialized_model)} bytes")

        # Send the model to test module REPLICATION times
        test_host = os.environ['TEST_HOST']  # e.g., "mlpipe-test"
        model_port = os.environ['MODEL_PORT']  # e.g., "5003"
        url_model = f"http://{test_host}:{model_port}/receive_model"
        logger.info(f"Sending trained model to {url_model}, size {len(serialized_model) / (1024 * 1024)} MB")

        success_count = 0
        for i in range(REPLICATION):
            response = requests.post(url_model, data=serialized_model, headers={"Content-Type": "application/octet-stream"})
            if response.status_code == 200:
                logger.info(f"Model sent successfully (iteration {i+1}).")
                success_count += 1
            else:
                logger.error(f"Failed to send model on iteration {i+1}: {response.text}")

        if success_count == REPLICATION:
            return jsonify({"status": "model trained and sent"}), 200
        else:
            return jsonify({"status": "partial failure"}), 500

    logger.info("Train module is running on port 5002")
    app.run(host='0.0.0.0', port=5002)

# ---------------------------
# Test module (ROLE=test)
# ---------------------------
def test_handler():
    @app.route('/receive_test', methods=['POST'])
    def receive_test():
        """
        Test module receiver for test data.
        Accumulate until REPLICATION times, then check if model is already present.
        If the model is present, compute accuracy.
        """
        global received_test_data_list, received_model
        raw_payload = request.data
        data_dict = pickle.loads(raw_payload)
        test_data = data_dict['data']

        with data_lock:
            received_test_data_list.append(test_data)
            logger.info(f"Received test data. Current count = {len(received_test_data_list)} / {REPLICATION}")

            if len(received_test_data_list) < REPLICATION:
                return jsonify({"status": "test data received but waiting for more"}), 200
            else:
                # We have all REPLICATION test data sets (they are presumably the same)
                logger.info("All test data replications received.")
                # Use the first one
                final_test_data = received_test_data_list[0]
                # Clear the list
                received_test_data_list.clear()

                # Now check if the model is ready
                if received_model is not None:
                    model = pickle.loads(received_model)
                    accuracy = model.score(final_test_data['X'], final_test_data['y'])
                    logger.info(f"Model accuracy: {accuracy}")
                    return jsonify({"status": "test data received, accuracy computed", "accuracy": accuracy}), 200
                else:
                    logger.info("Test data received but model not yet available.")
                    return jsonify({"status": "test data received but model not available"}), 200

    @app.route('/receive_model', methods=['POST'])
    def receive_model():
        """
        Test module receiver for the model.
        Accumulate until REPLICATION times, then if test data is present, compute accuracy.
        """
        global received_model_list, received_test_data_list, received_model
        model_payload = request.data

        with data_lock:
            received_model_list.append(model_payload)
            logger.info(f"Received model data. Current count = {len(received_model_list)} / {REPLICATION}")

            if len(received_model_list) < REPLICATION:
                return jsonify({"status": "model received but waiting for more"}), 200
            else:
                logger.info("All model replications received.")
                # Assume the model is the same across replications
                final_model_payload = received_model_list[0]
                received_model_list.clear()
                received_model = final_model_payload

                # If we already have test data, we can compute accuracy right away.
                if len(received_test_data_list) >= REPLICATION:
                    # Actually, 这里可能已经收集完 test data 并在前面清空过，故仅做一次性判断
                    # 如果要在这里再次判断，可以再写一次逻辑合并，但此处示例中只用一次。
                    pass

                # 计算当前已有test_data的准确率（只要test_data已经到齐、并且received_test_data_list已经处理了，就去用final test data）
                if len(received_test_data_list) == 0:
                    # 说明此前test_data已经处理完或尚未到达
                    logger.info("Model is stored. Will compute accuracy later if test data arrives.")
                    return jsonify({"status": "model received, waiting for test data or test data already processed"}), 200
                else:
                    # 如果逻辑上存储着 test_data，还没处理
                    final_test_data = received_test_data_list[0]
                    model = pickle.loads(received_model)
                    accuracy = model
