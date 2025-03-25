# Container Network Optimization Demo


## ml-pipeline
A simple ML application for demonstrating large data transmission in container networks. 
Follow below steps to run on a general k8s cluster: 
1. use Dockerfile to build the image
2. run k8s yaml files in /ml-pipeline/k8s_yamls to create pods and services
3. curl http://127.0.0.1:30080/start to start the application

## frontend
### /serverless_dashboard.py
a python dash app to visualize the transmission time and bandwidth 
Run it directly without any parameters

## net_stat_monitor.py
real time monitoring of transmission speed of each pod and sends the results to serverless_dashboard for visualization

## large-scale container network simulation and optimization
1. select serval dedicated nodes for container network optimization
2. replace the variable `HOSTS` in pods_sim.py and node_exec.sh with the selected nodes
3. run pods_sim.py to generate pods
4. replace the variable `POD_CIDR` in network_policy.py with your k8s cluster setting. 
5. `/node_exec.sh network_policy.py initialized` to distribute the flow table for each selected node
6. run ml-pipeline to visualize the results
7. `./node_exec.sh network_policy.py optimized` to optimize the flow table for each selected node
8. run ml-pipeline again to visualize the results

### transmission docker images in different nodes 
**sender**: docker save local-ml-app:latest | pv | nc -q 0 node3 10000
**receiver**: nc -l 10000 | pv | docker load