import argparse
import ipaddress
from jinja2 import Template, Environment, FileSystemLoader
from datetime import datetime

def ip_generator(base_ip, offset):
    """Generate sequential IP addresses"""
    return str(ipaddress.IPv4Address(base_ip) + offset)

def validate_ip_range(start_ip, total_ips):
    """Ensure IP range validity"""
    try:
        base = ipaddress.IPv4Address(start_ip)
        end = base + total_ips - 1
        if not (base.is_private and end.is_private):
            raise ValueError("IP range must be in private network")
        return True
    except ipaddress.AddressValueError as e:
        print(f"Invalid IP range: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description='Kubernetes iPerf Deployment Generator')
    parser.add_argument('--nodes', nargs='+', default=['node1', 'node2', 'node3'],
                        help='Target node names (space-separated)')
    parser.add_argument('--pods', type=int, default=2,
                        help='Number of pods per node')
    parser.add_argument('--start-ip', default='10.96.0.100',
                        help='Starting ClusterIP (e.g. 10.96.0.100)')
    parser.add_argument('-o', '--output', default='testing.yaml',
                        help='Output filename')

    args = parser.parse_args()

    total_ips = len(args.nodes) * args.pods
    if not validate_ip_range(args.start_ip, total_ips):
        return

    env = Environment(loader=FileSystemLoader('.'))
    template = env.get_template('testing_pod_template.j2')

    output = template.render(
        timestamp=datetime.utcnow().isoformat(),
        nodes=args.nodes,
        pods_per_node=args.pods,
        start_ip=args.start_ip,
        get_cluster_ip=ip_generator
    )

    with open(args.output, 'w') as f:
        f.write(output)

    print(f"Deployment file generated: {args.output}")
    print(f"IP allocation verified for {total_ips} addresses")
    print(f"Apply with: kubectl apply -f {args.output}")

if __name__ == "__main__":
    main()