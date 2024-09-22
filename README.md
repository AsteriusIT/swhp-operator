# STP Operator

[![Build Status](https://github.com/AsteriusIT/stp-operator/workflows/CI/badge.svg)](https://github.com/AsteriusIT/stp-operator/actions)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Helm Chart](https://img.shields.io/badge/helm%20chart-v1.0.0-blue)](https://github.com/AsteriusIT/stp-operator/releases/tag/v1.0.0)

STP Operator is a Kubernetes operator that simplifies the management of Azure
static websites in a Kubernetes cluster. It enables seamless access to static
websites hosted in Azure Storage accounts through Kubernetes ingresses.

## Features

- Automatically create and configure Nginx configuration to serve static
  websites from Azure Storage accounts
- Generate the necessary Nginx configuration, ConfigMap, and Nginx Ingress
  resources
- Seamlessly route requests to the appropriate Azure Storage account endpoint
- Manage Azure static host resources using custom resource definitions (CRDs)

## How It Works

STP Operator extends the Kubernetes API by introducing a custom resource
definition (CRD) named `AzureStaticHost`. When you create or update an
`AzureStaticHost` resource, the operator watches for these changes and takes the
necessary actions to configure the Nginx server and route requests to the Azure
Storage account.

The operator is written in Python and uses the `kopf` framework for Kubernetes
operator development. It follows the declarative configuration approach, where
you define the desired state of your Azure static host using the
`AzureStaticHost` custom resource. The operator then continuously reconciles the
actual state with the desired state, ensuring that the Nginx server and ingress
are properly configured.

## Installation

### Prerequisites

- Kubernetes cluster (version 1.19 or higher)
- Helm (version 3.0 or higher)

### Installing with Helm

STP Operator is deployed using a Helm chart. The Helm chart is published in the
Scaleway container registry. To install STP Operator, follow these steps:

1. Add the Scaleway Helm repository:
   ```bash
   helm repo add stp-operator rg.fr-par.scw.cloud/asterius-public-helm/operators/stp-operator
   ```

2. Update the Helm repository:
   ```bash
   helm repo update
   ```

3. Install the STP Operator Helm chart:
   ```bash
   helm install stp-operator stp-operator/stp-operator
   ```

   This will install STP Operator in the `default` namespace.

## Usage

### Creating an Azure Static Host

To create an Azure static host, you need to define an `AzureStaticHost` custom
resource. Here's an example:

```yaml
apiVersion: stp.operator.com/v1alpha1
kind: AzureStaticHost
metadata:
  name: mystatichost
spec:
    host: mystatichost.com
    source:
        host: mystatichost.z6.web.core.windows.net
        path: /mywebsite
```

Save this YAML to a file named `statichost.yaml` and apply it to your Kubernetes
cluster:

```bash
kubectl apply -f statichost.yaml
```

STP Operator will create the necessary Nginx server, configuration, and ingress
resources to serve the static website from the specified Azure Storage account.

### Configuring Azure Static Host

You can configure the Azure static host by modifying the `spec` section of the
`AzureStaticHost` custom resource. Update the desired configuration in the YAML
file and apply the changes:

```bash
kubectl apply -f statichost.yaml
```

STP Operator will handle the necessary updates to the Nginx server and ingress
resources.

## Contributing

Contributions are welcome! If you find any issues or have suggestions for
improvements, please open an issue or submit a pull request. Make sure to follow
the [contribution guidelines](CONTRIBUTING.md).

## License

This project is licensed under the [Apache License 2.0](LICENSE).

## Contact

For any questions or inquiries, please contact the maintainers at
[support@asteriusit.com](mailto:support@asteriusit.com).
