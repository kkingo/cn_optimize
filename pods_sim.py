from kubernetes import client, config
import random
import string

HOSTS = ['node1', 'node2', 'node3']
def get_nodes():
    """Retrieve a list of nodes in the Kubernetes cluster."""
    v1 = client.CoreV1Api()
    nodes = v1.list_node().items
    return [node.metadata.name for node in nodes if node.metadata.name != "master"]


def generate_random_code(length=3):
    """Generate a random 3-character alphanumeric code."""
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

def create_pod(pod_name, node_name, image):
    """Create a Kubernetes pod on a specific node using Kubernetes API."""
    v1 = client.CoreV1Api()
    pod_manifest = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": pod_name,
            "labels": {"app":"sim"}
            },
        "spec": {
            "containers": [{
                "name": f"{pod_name}-container",
                "image": image
            }],
            "nodeSelector": {"kubernetes.io/hostname": node_name}
        }
    }
    v1.create_namespaced_pod(namespace="default", body=pod_manifest)
    print(f"Pod {pod_name} created on node {node_name} with image {image}")


def main():
    config.load_kube_config()
    nodes = HOSTS
    images = ["redis", "rabbitmq", "nginx", "httpd"]  # Mixed functional images
    n = 100  # Define the number of pods to create

    for i in range(n):
        image = random.choice(images)
        random_code = generate_random_code()
        pod_name = f"{image}-{random_code}"
        node_name = nodes[i % len(nodes)]
        create_pod(pod_name, node_name, image)


if __name__ == "__main__":
    main()

