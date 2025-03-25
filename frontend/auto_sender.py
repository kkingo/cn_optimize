#!/usr/bin/env python3
# sender.py

import socket
import threading
import os
import sys
import time
import struct

def send_file(file_path, conn, addr, algo):
    print("[+] Accepted connection from {}:{}".format(addr[0], addr[1]))

    # Set congestion control algorithm
    try:
        TCP_CONGESTION = getattr(socket, 'TCP_CONGESTION', 13)  # 13 is the value for TCP_CONGESTION
        conn.setsockopt(socket.IPPROTO_TCP, TCP_CONGESTION, algo.encode())
        print("[*] Set congestion control algorithm to '{}'".format(algo))
    except socket.error as e:
        print("[-] Could not set congestion control algorithm to '{}': {}".format(algo, e))
        conn.close()
        return

    file_size = os.path.getsize(file_path) * 5
    # Pack file size and algo into header
    header = struct.pack('!Q16s', file_size, algo.encode())
    conn.sendall(header)

    # Start sending the file
    for i in range(5):
        with open(file_path, 'rb') as f:
            sent_size = 0
            start_time = time.time()
            while True:
                bytes_read = f.read(4096)
                if not bytes_read:
                    break
                conn.sendall(bytes_read)
                sent_size += len(bytes_read)
                # Update progress
                progress = (sent_size / file_size) * 100
                sys.stdout.write("\rSending with {}: {:.2f}%".format(algo, progress))
                sys.stdout.flush()
            end_time = time.time()
            elapsed_time = end_time - start_time
            avg_speed = (file_size * 8 / elapsed_time) / (1024 * 1024)  # Mbps

            print("\n[+] File sent using {}.".format(algo))
            print("[*] Time taken: {:.2f} seconds".format(elapsed_time))
            print("[*] Average speed: {:.2f} Mbps".format(avg_speed))

    conn.close()
    print("[*] Connection with {} closed.".format(addr))

def start_server(file_path, host='0.0.0.0', port=5000):
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind((host, port))
    server_socket.listen(5)
    print("[*] Server listening on {}:{}".format(host, port))
    algo_list = ['fastbts', 'cubic']  # Ensure 'fastbts' is installed on your system
    while True:
        conn, addr = server_socket.accept()
        # Receive the requested algorithm from the client
        requested_algo = conn.recv(1024).decode().strip()
        if requested_algo not in algo_list:
            print("[-] Requested algorithm '{}' is not supported.".format(requested_algo))
            conn.close()
            continue
        client_thread = threading.Thread(target=send_file, args=(file_path, conn, addr, requested_algo))
        client_thread.start()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python sender.py <file_path>")
        sys.exit(1)
    file_path = sys.argv[1]
    start_server(file_path)
