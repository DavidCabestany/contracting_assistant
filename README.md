## Creating Web Apps via ECS

This template lets you create your own web app and host it on ECS. Edit the Dockerfile (which initially contains
sample commands to create a Streamlit app) as required. Once the changes are pushed, a pipeline builds the docker
image and deploys it on ECS.

The web-app-config.json file can be used to increase the Node Count along with the CPU and Memory of each node
in the ECS service. The valid compatible CPU + Memory values are-

CPU value       |   Valid Memory Value
---             |   ---
256 (.25 vCPU)  |   512 MiB, 1 GB, 2 GB
512 (.5 vCPU)   |   1 GB, 2 GB, 3 GB, 4 GB
1024 (1 vCPU)   |   2 GB, 3 GB, 4 GB, 5 GB, 6 GB, 7 GB, 8 GB
2048 (2 vCPU)   |   Between 4 GB and 16 GB in 1 GB increments
4096 (4 vCPU)   |   Between 8 GB and 30 GB in 1 GB increments
8192 (8 vCPU)   |   Between 16 GB and 60 GB in 4 GB increments
16384 (16vCPU)  |   Between 32 GB and 120 GB in 8 GB increments
