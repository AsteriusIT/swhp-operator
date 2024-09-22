import datetime
import kopf
import kubernetes
from kubernetes.client.rest import ApiException
from tenacity import retry, stop_after_attempt, wait_exponential

# Constants
LABEL_SELECTOR = "asterius.fr/proxy=true"
API_RETRY_ATTEMPTS = 3
API_RETRY_WAIT_SECONDS = 1
API_RETRY_MULTIPLIER = 2
NGINX_DEPLOYMENT_NAME = "nginx-proxy"


def create_ingress(networking_v1_api, namespace, name, host):

    body = {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "Ingress",
        "metadata": {
            "annotations": {"cert-manager.io/cluster-issuer": "letsencrypt-prod"},
            "name": name,
            "namespace": namespace,
        },
        "spec": {
            "ingressClassName": "nginx",
            "rules": [
                {
                    "host": host,
                    "http": {
                        "paths": [
                            {
                                "backend": {
                                    "service": {
                                        "name": NGINX_DEPLOYMENT_NAME,
                                        "port": {"number": 80},
                                    }
                                },
                                "pathType": "ImplementationSpecific",
                            }
                        ]
                    },
                }
            ],
            "tls": [{"hosts": [host], "secretName": f"{name}-tls"}],
        },
    }

    # Creation of the Deployment in specified namespace
    # (Can replace "default" with a namespace you may have created)
    networking_v1_api.create_namespaced_ingress(namespace, body)


def delete_ingress(client, namespace, name):
    networking_api = client.NetworkingV1Api()

    try:
        networking_api.delete_namespaced_ingress(name=name, namespace=namespace)
        print(f"Ingress '{name}' deleted successfully from namespace '{namespace}'")
    except client.ApiException as e:
        print(f"Error deleting Ingress '{name}': {e}")


# Utility functions
def get_nginx_config(spec):
    return f"""
    server {{
        listen 80;
        server_name {spec['host']};
        location / {{
            proxy_pass https://{spec['source']['host']}{spec['source'].get('path', '')}/;
            proxy_set_header Host {spec['source']['host']};
            proxy_http_version 1.1;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            proxy_redirect https://{spec['source']['host']}{spec['source'].get('path', '')}/ /;
        }}
    }}
    """


def get_config_map(name, _, nginx_config):
    return kubernetes.client.V1ConfigMap(
        metadata=kubernetes.client.V1ObjectMeta(name=f"{name}-nginx-config"),
        data={f"{name}.conf": nginx_config},
    )


def get_volume(name):
    return kubernetes.client.V1Volume(
        name=f"{name}-nginx-config",
        config_map=kubernetes.client.V1ConfigMapVolumeSource(
            name=f"{name}-nginx-config"
        ),
    )


def get_volume_mount(name):
    return kubernetes.client.V1VolumeMount(
        name=f"{name}-nginx-config",
        mount_path=f"/etc/nginx/conf.d/{name}.conf",
        sub_path=f"{name}.conf",
    )


@retry(
    stop=stop_after_attempt(API_RETRY_ATTEMPTS),
    wait=wait_exponential(multiplier=API_RETRY_MULTIPLIER, min=API_RETRY_WAIT_SECONDS),
)
def patch_workload(apps_api, workload, kind, name, namespace, logger):
    if kind == "Deployment":
        apps_api.patch_namespaced_deployment(
            name=name, namespace=namespace, body=workload
        )
    elif kind == "StatefulSet":
        apps_api.patch_namespaced_stateful_set(
            name=name, namespace=namespace, body=workload
        )
    elif kind == "DaemonSet":
        apps_api.patch_namespaced_daemon_set(
            name=name, namespace=namespace, body=workload
        )
    logger.info(f"Updated {kind} {name}")


def process_workload(apps_api, workload, kind, name, namespace, update_func, logger):
    workload.spec.template.spec.volumes = workload.spec.template.spec.volumes or []
    workload.spec.template.spec.volumes.append(get_volume(name))
    for container in workload.spec.template.spec.containers:
        container.volume_mounts = container.volume_mounts or []
        container.volume_mounts.append(get_volume_mount(name))
    try:
        update_func(apps_api, workload, kind, workload.metadata.name, namespace, logger)
    except ApiException as e:
        logger.error(f"Error updating {kind} {workload.metadata.name}: {e}")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def create_config_map(api, namespace, body):
    try:
        api.create_namespaced_config_map(namespace=namespace, body=body)
    except ApiException as e:
        if e.status != 409:  # Ignore 409 (Conflict) errors
            raise e


def update_config_map(api, namespace, name, body):
    try:
        api.patch_namespaced_config_map(name=name, namespace=namespace, body=body)
    except ApiException as e:
        if e.status != 404:  # Ignore 404 (Not Found) errors
            raise e


@kopf.on.create("asterius.fr", "v1", "azurestatichosts")
def create_azure_static_host(body, spec, name, namespace, logger, **kwargs):
    api = kubernetes.client.CoreV1Api()
    apps_api = kubernetes.client.AppsV1Api()
    networking_v1_api = kubernetes.client.NetworkingV1Api()

    nginx_config = get_nginx_config(spec)
    logger.debug(f"Nginx configuration for {name}:\n{nginx_config}")

    config_map = get_config_map(name, namespace, nginx_config)
    create_config_map(api, namespace, config_map)

    # Create an Ingress for the AzureStaticHost
    create_ingress(networking_v1_api, namespace, name, spec["host"])

    logger.info(f"Creating AzureStaticHost {name}")

    for kind, list_func in [
        ("Deployment", apps_api.list_namespaced_deployment),
        ("StatefulSet", apps_api.list_namespaced_stateful_set),
        ("DaemonSet", apps_api.list_namespaced_daemon_set),
    ]:
        try:
            workloads = list_func(namespace=namespace, label_selector=LABEL_SELECTOR)
        except ApiException as e:
            logger.error(f"Error listing {kind}s: {e}")
            continue
        for workload in workloads.items:
            process_workload(
                apps_api, workload, kind, name, namespace, patch_workload, logger
            )

    logger.info(f"AzureStaticHost {name} created and Nginx configurations updated")


@kopf.on.delete("asterius.fr", "v1", "azurestatichosts")
def delete_azure_static_host(body, spec, name, namespace, logger, **kwargs):
    api = kubernetes.client.CoreV1Api()
    apps_api = kubernetes.client.AppsV1Api()

    config_map_name = f"{name}-nginx-config"

    # Function to update a workload
    def update_workload(workload, kind):
        # Remove the specific volume
        if workload.spec.template.spec.volumes:
            workload.spec.template.spec.volumes = [
                v
                for v in workload.spec.template.spec.volumes
                if v.name != config_map_name
            ]

        # Remove the specific volumeMount from each container
        for container in workload.spec.template.spec.containers:
            if container.volume_mounts:
                container.volume_mounts = [
                    vm for vm in container.volume_mounts if vm.name != config_map_name
                ]

        try:
            if kind == "Deployment":
                apps_api.replace_namespaced_deployment(
                    name=workload.metadata.name, namespace=namespace, body=workload
                )
            elif kind == "StatefulSet":
                apps_api.replace_namespaced_stateful_set(
                    name=workload.metadata.name, namespace=namespace, body=workload
                )
            elif kind == "DaemonSet":
                apps_api.replace_namespaced_daemon_set(
                    name=workload.metadata.name, namespace=namespace, body=workload
                )
            logger.info(
                f"Updated {kind} {workload.metadata.name} to remove configuration for {name}"
            )
        except kubernetes.client.exceptions.ApiException as e:
            logger.error(f"Error updating {kind} {workload.metadata.name}: {e}")

    # Process Deployments, StatefulSets, and DaemonSets
    for kind, list_func in [
        ("Deployment", apps_api.list_namespaced_deployment),
        ("StatefulSet", apps_api.list_namespaced_stateful_set),
        ("DaemonSet", apps_api.list_namespaced_daemon_set),
    ]:
        workloads = list_func(
            namespace=namespace, label_selector="asterius.fr/proxy=true"
        )
        for workload in workloads.items:
            update_workload(workload, kind)

    # Delete the ConfigMap
    try:
        api.delete_namespaced_config_map(name=config_map_name, namespace=namespace)
        logger.info(f"Deleted ConfigMap {config_map_name}")
    except kubernetes.client.exceptions.ApiException as e:
        if e.status != 404:  # Ignore 404 (Not Found) errors
            logger.error(f"Error deleting ConfigMap {config_map_name}: {e}")

    delete_ingress(kubernetes.client, namespace, name)

    logger.info(f"AzureStaticHost {name} deleted and Nginx configurations removed")


# On update
@kopf.on.update("asterius.fr", "v1", "azurestatichosts")
def update_azure_static_host(body, spec, name, namespace, logger, **kwargs):
    api = kubernetes.client.CoreV1Api()
    apps_api = kubernetes.client.AppsV1Api()

    nginx_config = get_nginx_config(spec)
    logger.debug(f"Nginx configuration for {name}:\n{nginx_config}")

    config_map = get_config_map(name, namespace, nginx_config)
    update_config_map(api, namespace, f"{name}-nginx-config", config_map)

    for kind, list_func in [
        ("Deployment", apps_api.list_namespaced_deployment),
        ("StatefulSet", apps_api.list_namespaced_stateful_set),
        ("DaemonSet", apps_api.list_namespaced_daemon_set),
    ]:
        workloads = list_func(namespace=namespace, label_selector=LABEL_SELECTOR)
        for workload in workloads.items:
            # Update the workload template to trigger a new rollout
            workload.spec.template.metadata.annotations = {
                "kubectl.kubernetes.io/restartedAt": datetime.datetime.now().isoformat()
            }

            patch_workload(
                apps_api, workload, kind, workload.metadata.name, namespace, logger
            )

    logger.info(f"AzureStaticHost {name} updated and Nginx configurations updated")
