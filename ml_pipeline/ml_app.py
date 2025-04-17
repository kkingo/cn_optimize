import json
import os
import pickle
import tempfile

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.datasets import fetch_openml
from flask import Flask, request, jsonify
import threading
import logging
import requests
import shutil
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
REPLICATION = 6  # Number of times to send data (if needed)
DATA_SPLIT = 0.6  # Train/test split ratio


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


def jsonlog_send_operation(receivers):
    FILE = "trans_metrics.json"
    for receiver in receivers:
        entry = {
            "sender": os.environ.get('ROLE', '').lower(),
            "receiver": receiver,
        }
        try:
            with open(FILE, "w") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            print(f"Log error: {str(e)}")


def log_send_operation(receivers):
    FILE = "trans_metrics.pkl"
    # 先收集所有条目
    entry = { "sender": os.environ.get('ROLE', '').lower(), "receiver": receivers}

    try:
        # 使用二进制写入模式，全量覆盖保存
        with open(FILE, "wb") as f:
            pickle.dump(entry, f)
    except Exception as e:
        print(f"Log error: {str(e)}")

def preprocess_data(data):
    """
    Preprocess data: flatten images, normalize and split.
    """
    X = data['X'].reshape((-1, 28 * 28)).astype('float32') / 255.0
    y = data['y']
    split = int(DATA_SPLIT * len(X))
    return {'X': X[:split], 'y': y[:split]}, {'X': X[split:], 'y': y[split:]}


# =====================================================
# Helpers for chunked (streaming) transmission and parse
# =====================================================
def chunked_data_generator(payload, times, chunk_size=8192):
    """
    Generator function for streaming. It repeats the same payload 'times' times,
    and splits each repetition into chunks of size 'chunk_size'.
    """
    # payload: bytes
    # times: int
    # chunk_size: int
    for _ in range(times):
        start = 0
        while start < len(payload):
            yield payload[start:start + chunk_size]
            start += chunk_size


def receive_first_object_from_request(flask_request, chunk_size=8192):
    """
    从Flask请求流中分块读取数据，逐步构建缓冲区，使用Unpickler正确解析首个完整对象。
    解析成功后丢弃剩余数据，避免网络缓冲阻塞。
    """
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        temp_path = temp_file.name
        try:
            # 分块读取请求数据并写入临时文件
            while True:
                chunk = flask_request.stream.read(chunk_size)
                if not chunk:
                    break
                temp_file.write(chunk)

            # 重新以内存映射模式打开临时文件
            with open(temp_path, 'rb') as file:
                # 使用pickle的Unpickler流式解析
                unpickler = pickle.Unpickler(file)
                try:
                    obj = unpickler.load()
                except (EOFError, pickle.UnpicklingError) as e:
                    raise ValueError("Invalid or incomplete pickle data") from e
            return obj
        finally:
            # 清理临时文件
            temp_file.close()
            shutil.os.remove(temp_path)


# def receive_first_object_from_request(flask_request, chunk_size=8192):
#     """
#     Read the raw data from `flask_request` as a stream, in increments of 'chunk_size' bytes.
#     Try to unpickle repeatedly until we get the first valid object.
#     After successfully unpickling the first object, drain any remaining data (repeated chunks),
#     but do not parse them again.
#     """
#     buffer = bytearray()
#     i = 0
#     # 1) 持续分块读取数据
#     while True:
#         chunk = flask_request.stream.read(chunk_size)
#         if not chunk:
#             # No more data available
#             break
#         buffer.extend(chunk)
#         i += 1
#         logger.info(f"received chunks number is {i}")
#         # 2) 每次读取后尝试反序列化
#         try:
#             first_data = pickle.loads(buffer)
#             # 3) 成功后，读取并丢弃剩余重复数据，保证不会卡住网络缓冲
#             while True:
#                 leftover = flask_request.stream.read(chunk_size)
#                 if not leftover:
#                     break
#             # 4) 返回成功解析的对象
#             return first_data
#         except EOFError:
#             # Means not enough data to unpickle yet, continue reading...
#             continue
#
#     # 如果循环结束都没能解析出来，说明数据不完整或有问题
#     raise ValueError("Could not unpickle the data from the incoming stream. Possibly corrupt or incomplete.")


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
        # Trigger data download and send raw data via HTTP POST to preprocess service in a streaming way.
        raw_data = download_data()
        next_host = os.environ['NEXT_HOST']  # e.g., "mlpipe-preprocess"
        next_port = os.environ['NEXT_PORT']  # e.g., "5001"
        url = f"http://{next_host}:{next_port}/receive"
        log_send_operation([next_host])

        # Serialize once
        payload = pickle.dumps({'data': raw_data})
        logger.info(f"Serializing data: {len(payload)} bytes total")

        # Prepare generator for streaming repeated data
        def stream_generator():
            """Yield the same pickled payload REPLICATION times in chunks."""
            yield from chunked_data_generator(payload, REPLICATION, 4096)


        # Send data in a chunked (streamed) manner
        logger.info(f"Sending raw data to {url} in streaming mode, repeated {REPLICATION} times...")
        try:
            response = requests.post(
                url,
                data=stream_generator(),
                headers={"Content-Type": "application/octet-stream"},
                stream=True  # This is for requests to also use chunked encoding
            )
            if response.status_code == 200:
                logger.info("Data sent successfully")
                return jsonify({"status": "data sent successfully"}), 200
            else:
                logger.error(f"Failed to send data: {response.text}")
                return jsonify({"status": "failed", "error": response.text}), response.status_code
        except Exception as e:
            logger.error(f"Error sending data: {e}")
            return jsonify({"status": "error", "error": str(e)}), 500

    logger.info("Download module is running on port 5000")
    app.run(host='0.0.0.0', port=5000)


# ---------------------------
# Preprocess module (ROLE=preprocess)
# ---------------------------
def preprocess_handler():
    @app.route('/receive', methods=['POST'])
    def receive_data():
        try:
            # Read and parse only the first data object from the stream
            logger.info("Receiving raw data in streaming mode...")
            first_data_obj = receive_first_object_from_request(request, chunk_size=4096)
            logger.info(f'received data length of the first object is {len(first_data_obj)}')
            raw_data = first_data_obj['data']
            logger.info(f"Data prepared with {len(raw_data)}")

            logger.info("Received raw data (first object). Starting preprocessing...")
            train_data, test_data = preprocess_data(raw_data)

            # Prepare URLs and payloads
            train_host = os.environ['TRAIN_HOST']
            train_port = os.environ['TRAIN_PORT']
            url_train = f"http://{train_host}:{train_port}/receive"
            payload_train = pickle.dumps({'data': train_data})

            test_host = os.environ['TEST_HOST']
            test_port = os.environ['TEST_PORT']
            url_test = f"http://{test_host}:{test_port}/receive_test"
            payload_test = pickle.dumps({'data': test_data})

            payload_train = pickle.dumps({'data': train_data})
            logger.info(f"Preparing to send train data: {len(payload_train)} bytes")
            log_send_operation([train_host, test_host])
            # Define send function with error handling
            def send_data(url, payload):
                try:
                    def generator():
                        yield from chunked_data_generator(payload, REPLICATION, 4096)

                    response = requests.post(
                        url,
                        data=generator(),
                        headers={"Content-Type": "application/octet-stream"},
                        stream=True
                    )
                    if response.status_code != 200:
                        logger.error(f"Failed to send to {url}: {response.text}")
                        return (False, response.text)
                    logger.info(f"Data sent to {url} successfully")
                    return (True, None)
                except Exception as e:
                    logger.error(f"Error sending to {url}: {str(e)}")
                    return (False, str(e))

            # Use threads to send data concurrently
            from threading import Thread
            results = {}

            def train_sender():
                results['train'] = send_data(url_train, payload_train)

            def test_sender():
                results['test'] = send_data(url_test, payload_test)

            # Start threads
            threads = [
                Thread(target=train_sender),
                Thread(target=test_sender)
            ]
            for t in threads:
                t.start()

            # Wait for all threads to complete
            for t in threads:
                t.join()

            # Check results
            errors = []
            if not results['train'][0]:
                errors.append(f"Train: {results['train'][1]}")
            if not results['test'][0]:
                errors.append(f"Test: {results['test'][1]}")

            if errors:
                error_msg = "Errors occurred: " + "; ".join(errors)
                return jsonify({"status": "error", "error": error_msg}), 500
            else:
                return jsonify({"status": "preprocessing complete and data sent"}), 200

        except Exception as e:
            logger.error(f"Error in preprocessing: {e}")
            return jsonify({"status": "error", "error": str(e)}), 500

    logger.info("Preprocess module is running on port 5001")
    app.run(host='0.0.0.0', port=5001)


# ---------------------------
# Train module (ROLE=train)
# ---------------------------
def train_handler():
    @app.route('/receive', methods=['POST'])
    def receive_train_data():
        try:
            logger.info("Receiving training data in streaming mode...")
            first_data_obj = receive_first_object_from_request(request, chunk_size=4096)
            train_data = first_data_obj['data']

            logger.info("Received training data (first object). Starting model training...")
            model = LogisticRegression(max_iter=1000)
            model.fit(train_data['X'], train_data['y'])

            serialized_model = pickle.dumps(model)
            logger.info(f"Model trained. Serialized model size: {len(serialized_model)} bytes")

            # Send the model to test module in streaming form
            test_host = os.environ['TEST_HOST']  # e.g., "mlpipe-test"
            model_port = os.environ['MODEL_PORT']  # e.g., "5003"
            url_model = f"http://{test_host}:{model_port}/receive_model"
            log_send_operation([test_host])
            def model_generator():
                yield from chunked_data_generator(serialized_model, REPLICATION, 4096)

            logger.info(f"Sending trained model to {url_model}, repeated {REPLICATION} times...")
            response = requests.post(
                url_model,
                data=model_generator(),
                headers={"Content-Type": "application/octet-stream"},
                stream=True
            )
            if response.status_code == 200:
                logger.info("Model sent successfully")
                return jsonify({"status": "model trained and sent"}), 200
            else:
                logger.error(f"Failed to send model: {response.text}")
                return jsonify({"status": "failed", "error": response.text}), response.status_code

        except Exception as e:
            logger.error(f"Error in training: {e}")
            return jsonify({"status": "error", "error": str(e)}), 500

    logger.info("Train module is running on port 5002")
    app.run(host='0.0.0.0', port=5002)


# ---------------------------
# Test module (ROLE=test)
# ---------------------------
# Global variables to store received test data and model
received_test_data = None
received_model = None
data_lock = threading.Lock()


def test_handler():
    @app.route('/receive_test', methods=['POST'])
    def receive_test():
        global received_test_data
        try:
            logger.info("Receiving test data in streaming mode...")
            first_data_obj = receive_first_object_from_request(request, chunk_size=4096)
            with data_lock:
                received_test_data = first_data_obj['data']
                logger.info("Test data received (first object).")
                # If model is already present, compute accuracy
                if received_model is not None:
                    model = pickle.loads(received_model)
                    accuracy = model.score(received_test_data['X'], received_test_data['y'])
                    logger.info(f"Model accuracy: {accuracy}")
            return jsonify({"status": "test data received"}), 200
        except Exception as e:
            logger.error(f"Error receiving test data: {e}")
            return jsonify({"status": "error", "error": str(e)}), 500

    @app.route('/receive_model', methods=['POST'])
    def receive_model_data():
        global received_model
        try:
            logger.info("Receiving model in streaming mode...")
            first_data_obj = receive_first_object_from_request(request, chunk_size=4096)
            with data_lock:
                # Here, the 'first_data_obj' itself is raw bytes of the model, so we just store it.
                # In the pipeline above, we sent the model as serialized bytes (not a dict).
                # So we can treat 'first_data_obj' as the actual unpickled object if we had used
                # a dict. But for direct model bytes, we might approach differently.
                #
                # However, for consistency, let's assume we are passing just the model bytes
                # wrapped in a single 'pickle.dumps(model)' call. Then it unpickles to a model
                # object. So let's assume it is indeed the model object.
                # If not, we can just store the raw bytes.
                #
                # Here we treat it as a model object:
                if isinstance(first_data_obj, LogisticRegression):
                    received_model = pickle.dumps(first_data_obj)
                else:
                    # If we had sent raw bytes only, 'first_data_obj' might be the actual model object
                    # or it might be something else. Adjust as needed.
                    # For safety, let's do:
                    received_model = pickle.dumps(first_data_obj)

                logger.info("Model received (first object).")
                if received_test_data is not None:
                    model = pickle.loads(received_model)
                    accuracy = model.score(received_test_data['X'], received_test_data['y'])
                    logger.info(f"Model accuracy: {accuracy}")
            return jsonify({"status": "model received"}), 200
        except Exception as e:
            logger.error(f"Error receiving model: {e}")
            return jsonify({"status": "error", "error": str(e)}), 500

    logger.info("Test module is running on port 5003")
    app.run(host='0.0.0.0', port=5003)


# ===========================
# Main entry point: role-based dispatch
# ===========================
if __name__ == "__main__":
    role = os.environ.get('ROLE', '').lower()
    logger.info(f"Starting module with role: {role}")
    if role == 'download-0':
        download_handler()
    elif role == 'preprocess-1':
        preprocess_handler()
    elif role == 'train-2':
        train_handler()
    elif role == 'test-3':
        test_handler()
    else:
        logger.error("Invalid role specified")
        exit("Invalid role specified")
