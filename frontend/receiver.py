#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# receiver.py
import requests
import json
import socket
import sys
import time
import os
import struct
import argparse


def send_data(current_data, server_url='http://47.94.80.218:8888/update_data'):
    try:
        response = requests.post(server_url, json=current_data)
        if response.status_code == 200:
            pass
        else:
            print("Failed to send data.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


def receive_file(algo, host='47.113.180.171', port=5000):
    optimized = 1 if algo == 'fastbts' else 0
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_socket.connect((host, port))
    print("[+] Connected to server {}:{}".format(host, port))

    # Send the requested algorithm to the server
    client_socket.sendall(algo.encode())

    # Receive header
    header_size = struct.calcsize('!Q16s')
    header_data = b''
    while len(header_data) < header_size:
        chunk = client_socket.recv(header_size - len(header_data))
        if not chunk:
            print("[-] Connection closed unexpectedly while receiving header.")
            client_socket.close()
            return
        header_data += chunk

    file_size, algo_used_bytes = struct.unpack('!Q16s', header_data)
    algo_used = algo_used_bytes.decode().strip('\x00')
    print("[*] File size: {} bytes".format(file_size))
    if algo_used == 'cubic':
        print("[*] Receiving file using transmission method: Regular")
    if algo_used == 'fastbts':
        print("[*] Receiving file using transmission method: Burst")

    received_size = 0
    with open('./Digits_Tranin_{}.txt'.format(algo_used), 'wb') as f:
        start_time = time.time()
        last_report_time = start_time
        last_received_size = 0
        data = {
            "from": 1,
            "to": 2,
            "bandwidth": 0,
            "latency": 90,
            "progress": 0,
            'timeusage': 0,
            "optimized": optimized
        }
        send_data(data)
        while received_size < file_size:
            data = client_socket.recv(4096)
            if not data:
                break
            f.write(data)
            received_size += len(data)
            progress = (received_size / file_size) * 100
            sys.stdout.write("\rReceiving: {:.2f}%".format(progress))
            sys.stdout.flush()
            now = time.time()
            if now - last_report_time > 0.5:
                bw = ((received_size - last_received_size) * 8 / 0.5) / (1024 * 1024)
                data = {
                    "from": 1,
                    "to": 2,
                    "bandwidth": bw,
                    "latency": 90,
                    "progress": progress / 100,
                    'timeusage': now - start_time,
                    "optimized": optimized
                }
                print(json.dumps(data))
                send_data(data)
                last_report_time = now
                last_received_size = received_size
        end_time = time.time()
        elapsed_time = end_time - start_time
        avg_speed = (file_size * 8 / elapsed_time) / (1024 * 1024)  # Mbps
        print("\n[+] File received using {}.".format(algo_used))
        print("[*] Time taken: {:.2f} seconds".format(elapsed_time))
        print("[*] Average speed: {:.2f} Mbps".format(avg_speed))

    client_socket.close()
    print("[*] Connection closed.")
    return elapsed_time


if __name__ == "__main__":
    algos = ['cubic', 'fastbts']
    receive_file(algos[0])
    receive_file(algos[1])
