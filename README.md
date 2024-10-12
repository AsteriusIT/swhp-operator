# SWHP Operator

[![Build Status](https://github.com/AsteriusIT/swhp-operator/actions/workflows/build-deploy.yml/badge.svg)](https://github.com/AsteriusIT/swhp-operator/actions/workflows/build-deploy.yml)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Helm Chart](https://img.shields.io/badge/helm%20chart-v0.0.7-blue)](https://github.com/AsteriusIT/swhp-operator/releases/tag/v0.0.7)

SWHP Operator (Static Web Host Proxy) is a Kubernetes operator that simplifies the management of Azure
static websites in a Kubernetes cluster. It enables seamless access to static
websites hosted in Azure Storage accounts through Kubernetes ingresses.

## Features

- Automatically create and configure Nginx configuration to serve static
  websites from Azure Storage accounts
- Generate the necessary Nginx configuration, ConfigMap, and Nginx Ingress
  resources
- Seamlessly route requests to the appropriate Azure Storage account endpoint
- Manage Static host resources using custom resource definitions (CRDs)

## How It Works

SWHP Operator extends the Kubernetes API by introducing a custom resource
definition (CRD) named `AzureStaticHost`. When you create or update an
`AzureStaticHost` resource, the operator watches for these changes and takes the
necessary actions to configure the Nginx server and route requests to the Azure
Storage account.

The operator is written in Python and uses the `kopf` framework for Kubernetes
operator development. It follows the declarative configuration approach, where
you define the desired state of your Static host using the `AzureStaticHost`
custom resource. The operator then continuously reconciles the actual state with
the desired state, ensuring that the Nginx server and ingress are properly
configured.

## Installation

### Prerequisites

- Kubernetes cluster (version 1.19 or higher)
- Helm (version 3.0 or higher)

### Installing with Helm

SWHP Operator is deployed using a Helm chart. The Helm chart is published in the
Scaleway container registry. To install SWHP Operator, follow these steps:

1. Install the SWHP Operator Helm chart:
   ```bash
   helm install swhp-operator oci://rg.fr-par.scw.cloud/asterius-public-helm/operators/swhp-operator --version 0.0.7
   ```

   This will install SWHP Operator in the `default` namespace.

## Usage

### Creating a Static Host

To create an Static host, you need to define an `StaticHost` custom resource.
Here's an example:

```yaml
apiVersion: asterius.fr/v1
kind: StaticHost
metadata:
  name: azure
spec:
  provider: azure
  ingress: example.asterius.fr
  azure:
    accountName: test
    dnsZoneId: 28
    subpath: /
```

To create an AWS static host, you need to define an `StaticHost` custom
resource. Here's an example:

```yaml
apiVersion: asterius.fr/v1
kind: StaticHost
metadata:
  name: aws
spec:
  provider: aws
  ingress: example.asterius.fr
  aws:
    bucketName: test
    region: eu-west-3
```

Save this YAML to a file named `statichost.yaml` and apply it to your Kubernetes
cluster:

```bash
kubectl apply -f statichost.yaml
```

SWHP Operator will create the necessary Nginx server, configuration, and ingress
resources to serve the static website from the specified Azure Storage account.

### Configuring Static Host

You can configure the Static host by modifying the `spec` section of the
`AzureStaticHost` custom resource. Update the desired configuration in the YAML
file and apply the changes:

```bash
kubectl apply -f statichost.yaml
```

SWHP Operator will handle the necessary updates to the Nginx server and ingress
resources.

### Custom Nginx proxy

You can setup the name of the Nginx service:

```yaml
apiVersion: asterius.fr/v1
kind: StaticHost
metadata:
  name: azure
spec:
  provider: azure
  ingress: example.asterius.fr
  azure:
    accountName: test
    dnsZoneId: 28
    subpath: /
  proxy:
    service: my-nginx-service
```

## Contributing

Contributions are welcome! If you find any issues or have suggestions for
improvements, please open an issue or submit a pull request. Make sure to follow
the [contribution guidelines](CONTRIBUTING.md).

## License

This project is licensed under the [Apache License 2.0](LICENSE).

## Contact

For any questions or inquiries, please contact the maintainers at
[support@asteriusit.com](mailto:support@asteriusit.com).
