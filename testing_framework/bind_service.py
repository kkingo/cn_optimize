#!/usr/bin/env python3
"""
This script queries all pods with the label "app=sim" and creates 100 services for each pod.
Each service is assigned a unique clusterIP starting from "10.96.1.1", incrementing by 1 for each service.
All created services have the label "app=sim".
"""

from kubernetes import client, config
import ipaddress


def ip_to_str(ip_obj):
    """
    Convert an ipaddress.IPv4Address object to string.

    :param ip_obj: IPv4Address object
    :return: String representation of the IP
    """
    return str(ip_obj)


def main():
    # Load Kubernetes configuration from the default location (e.g., ~/.kube/config)
    config.load_kube_config()

    # Create a CoreV1Api client to interact with the Kubernetes API
    v1 = client.CoreV1Api()

    # Query all pods with the label "app=sim" across all namespaces
    pods = v1.list_pod_for_all_namespaces(label_selector="app=sim").items
    print("Found {} pods with label app=sim.".format(len(pods)))

    # Initialize the starting clusterIP as an ipaddress object
    current_ip = ipaddress.IPv4Address("10.96.1.1")

    # Iterate over each pod found
    for pod in pods:
        # Use the namespace of the pod for creating the service
        namespace = pod.metadata.namespace
        pod_name = pod.metadata.name

        # Create 100 services for the current pod
        for i in range(100):
            # Construct a unique service name using pod name and an index
            service_name = f"{pod_name}-service-{i}"

            # Define the service object with the desired metadata and spec.
            # The metadata includes the name and label "app=sim"
            # The spec defines the clusterIP and a simple port mapping.
            service_body = client.V1Service(
                metadata=client.V1ObjectMeta(
                    name=service_name,
                    labels={"app": "sim"}
                ),
                spec=client.V1ServiceSpec(
                    # Note: The selector below is set to "app=sim".
                    # In practice, this might match multiple pods; adjust accordingly if a pod-specific selection is needed.
                    selector={"app": "sim"},
                    cluster_ip=ip_to_str(current_ip),
                    ports=[client.V1ServicePort(
                        port=80,  # Service port
                        target_port=80  # Target port on the pod(s)
                    )]
                )
            )

            try:
                # Create the service in the pod's namespace
                v1.create_namespaced_service(namespace=namespace, body=service_body)
                print(
                    f"Created service: {service_name} in namespace: {namespace} with clusterIP: {ip_to_str(current_ip)}")
            except Exception as e:
                # If there is an error during creation, print the error message.
                print(f"Error creating service {service_name} in namespace {namespace}: {e}")

            # Increment the current IP by 1 for the next service
            current_ip += 1


if __name__ == "__main__":
    main()
