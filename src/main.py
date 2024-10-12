import datetime
import kopf
import kubernetes
from kubernetes.client.rest import ApiException
from tenacity import retry, stop_after_attempt, wait_exponential
from static_proxy import create_nginx_deployment

# Constants
LABEL_SELECTOR = "asterius.fr/proxy=true"
API_RETRY_ATTEMPTS = 3
API_RETRY_WAIT_SECONDS = 1
API_RETRY_MULTIPLIER = 2
NGINX_DEPLOYMENT_NAME = "nginx-proxy"


def create_ingress(networking_v1_api, namespace, name, host, svc_name):

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
                                        "name": svc_name,
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

    provider: str = spec["provider"]
    ingress: str = spec["ingress"]

    host: str = ""
    subpath: str = ""
    protocol: str = "https"

    if provider == "azure":
        account_name: str = spec["azure"]["accountName"]
        dns_zone_id: str = spec["azure"]["dnsZoneId"]

        host = f"{account_name}.z{dns_zone_id}.web.core.windows.net"
        subpath = spec["azure"].get("subpath", "")
    elif provider == "aws":
        bucket: str = spec["aws"]["bucketName"]
        region: str = spec["aws"]["region"]

        host = f"{bucket}.s3-website.{region}.amazonaws.com"
        subpath = spec["aws"].get("subpath", "")

        protocol = "http"

    full_host = f"{host}{subpath}".strip("/")

    return f"""
    server {{
        listen 80;
        server_name {ingress};
        location / {{
            proxy_pass {protocol}://{full_host}/;
            proxy_set_header Host {host};
            proxy_http_version 1.1;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            proxy_redirect {protocol}://{full_host}/ /;
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


def get_proxy_service(spec) -> str:
    if "proxy" in spec and "service" in spec["proxy"]:
        return spec["proxy"]["service"]

    return NGINX_DEPLOYMENT_NAME


@kopf.on.create("asterius.fr", "v1", "statichosts")
def create_azure_static_host(body, spec, name, namespace, logger, **kwargs):
    api = kubernetes.client.CoreV1Api()
    apps_api = kubernetes.client.AppsV1Api()
    networking_v1_api = kubernetes.client.NetworkingV1Api()

    nginx_config = get_nginx_config(spec)
    logger.debug(f"Nginx configuration for {name}:\n{nginx_config}")

    config_map = get_config_map(name, namespace, nginx_config)
    create_config_map(api, namespace, config_map)

    # Create an Ingress for the StaticHost
    create_ingress(
        networking_v1_api, namespace, name, spec["ingress"], get_proxy_service(spec)
    )

    logger.info(f"Creating StaticHost {name}")

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

    logger.info(f"StaticHost {name} created and Nginx configurations updated")


@kopf.on.delete("asterius.fr", "v1", "statichosts")
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

    logger.info(f"StaticHost {name} deleted and Nginx configurations removed")


# On update
@kopf.on.update("asterius.fr", "v1", "statichosts")
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

    logger.info(f"StaticHost {name} updated and Nginx configurations updated")


@kopf.on.create("asterius.fr", "v1", "staticproxies")
def create_static_proxy(spec, name, namespace, logger, **kwargs):
    logger.info(f"Creating StaticProxy: {name}")

    # Create Nginx deployment
    create_nginx_deployment(name, namespace, spec)

    # Create Service
    core_v1 = kubernetes.client.CoreV1Api()
    service = kubernetes.client.V1Service(
        metadata=kubernetes.client.V1ObjectMeta(name=name),
        spec=kubernetes.client.V1ServiceSpec(
            selector={"app": name},
            ports=[kubernetes.client.V1ServicePort(port=80, target_port=80)],
        ),
    )
    core_v1.create_namespaced_service(namespace, service)

    # Create Ingress if TLS is enabled
    if spec.get("tls", {}).get("enabled", False):
        networking_v1 = kubernetes.client.NetworkingV1Api()
        ingress = kubernetes.client.V1Ingress(
            metadata=kubernetes.client.V1ObjectMeta(name=name),
            spec=kubernetes.client.V1IngressSpec(
                tls=[
                    kubernetes.client.V1IngressTLS(
                        hosts=[spec["domain"]], secret_name=spec["tls"]["secretName"]
                    )
                ],
                rules=[
                    kubernetes.client.V1IngressRule(
                        host=spec["domain"],
                        http=kubernetes.client.V1HTTPIngressRuleValue(
                            paths=[
                                kubernetes.client.V1HTTPIngressPath(
                                    path="/",
                                    path_type="Prefix",
                                    backend=kubernetes.client.V1IngressBackend(
                                        service=kubernetes.client.V1IngressServiceBackend(
                                            name=name,
                                            port=kubernetes.client.V1ServiceBackendPort(
                                                number=80
                                            ),
                                        )
                                    ),
                                )
                            ]
                        ),
                    )
                ],
            ),
        )
        networking_v1.create_namespaced_ingress(namespace, ingress)

    return {"message": f"StaticProxy {name} created successfully"}


@kopf.on.delete("asterius.fr", "v1", "staticproxies")
def delete_fn(spec, name, namespace, logger, **kwargs):
    logger.info(f"Deleting StaticProxy: {name}")

    # Delete associated resources
    apps_v1 = kubernetes.client.AppsV1Api()
    core_v1 = kubernetes.client.CoreV1Api()
    networking_v1 = kubernetes.client.NetworkingV1Api()

    apps_v1.delete_namespaced_deployment(name, namespace)
    core_v1.delete_namespaced_service(name, namespace)

    if spec.get("tls", {}).get("enabled", False):
        networking_v1.delete_namespaced_ingress(name, namespace)

    return {"message": f"StaticProxy {name} deleted successfully"}
