from kubernetes import client, config


def create_nginx_deployment(name, namespace, spec):
    apps_v1 = client.AppsV1Api()

    container = client.V1Container(
        name="nginx",
        image=f"nginx:{spec.get('nginxVersion', 'latest')}",
        ports=[client.V1ContainerPort(container_port=80)],
    )

    # Add resource requests/limits if specified
    if "resources" in spec:
        container.resources = client.V1ResourceRequirements(**spec["resources"])

    template = client.V1PodTemplateSpec(
        metadata=client.V1ObjectMeta(labels={"app": name}),
        spec=client.V1PodSpec(containers=[container]),
    )

    spec = client.V1DeploymentSpec(
        replicas=spec.get("replicas", 1),
        selector=client.V1LabelSelector(match_labels={"app": name}),
        template=template,
    )

    deployment = client.V1Deployment(
        api_version="apps/v1",
        kind="Deployment",
        metadata=client.V1ObjectMeta(
            name=name, namespace=namespace, labels={"asterius.fr/proxy": "true"}
        ),
        spec=spec,
    )

    return apps_v1.create_namespaced_deployment(namespace, deployment)
