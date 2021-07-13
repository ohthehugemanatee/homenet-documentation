# Elasticsearch

1. Install the elasticsearch operator

`kubectl apply -f https://download.elastic.co/downloads/eck/1.6.0/all-in-one.yaml`

2. Edit and apply the elasticsearch manifest in `services/elasticsearch.yaml`

3. Get the credentials. A default user named elastic is automatically created with the password stored in a Kubernetes secret:
```
PASSWORD=$(kubectl get secret quickstart-es-elastic-user -o go-template='{{.data.elastic | base64decode}}')
```

4. Applications can access elasticsearch through the HTTP endpoint service, `<name>-es-http:9200`. HTTPS is disabled in the manifest because of untrusted certificates... and it's a local only service, after all.

