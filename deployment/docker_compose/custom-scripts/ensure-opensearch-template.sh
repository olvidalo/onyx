#!/bin/bash
# Ensures the multilingual analyzer template exists in OpenSearch
# Run on startup or after fresh OpenSearch install

OPENSEARCH_HOST="${OPENSEARCH_HOST:-opensearch}"
OPENSEARCH_PORT="${OPENSEARCH_PORT:-9200}"
OPENSEARCH_USER="${OPENSEARCH_USER:-admin}"
OPENSEARCH_PASS="${OPENSEARCH_ADMIN_PASSWORD:-admin}"

TEMPLATE_NAME="multilingual_template"
URL="https://${OPENSEARCH_HOST}:${OPENSEARCH_PORT}"

# Wait for OpenSearch to be ready
for i in {1..30}; do
  if curl -sk -u "${OPENSEARCH_USER}:${OPENSEARCH_PASS}" "${URL}/_cluster/health" >/dev/null 2>&1; then
    break
  fi
  echo "Waiting for OpenSearch... ($i/30)"
  sleep 2
done

# Check if template exists
if curl -sk -u "${OPENSEARCH_USER}:${OPENSEARCH_PASS}" "${URL}/_index_template/${TEMPLATE_NAME}" | grep -q "multilingual"; then
  echo "Template ${TEMPLATE_NAME} already exists"
  exit 0
fi

echo "Creating template ${TEMPLATE_NAME}..."
curl -sk -X PUT "${URL}/_index_template/${TEMPLATE_NAME}" \
  -u "${OPENSEARCH_USER}:${OPENSEARCH_PASS}" \
  -H "Content-Type: application/json" \
  -d '
{
  "index_patterns": ["danswer_chunk_*"],
  "priority": 100,
  "template": {
    "settings": {
      "analysis": {
        "filter": {
          "english_stemmer": { "type": "stemmer", "language": "english" },
          "german_stemmer": { "type": "stemmer", "language": "german" },
          "english_stop": { "type": "stop", "stopwords": "_english_" },
          "german_stop": { "type": "stop", "stopwords": "_german_" }
        },
        "analyzer": {
          "multilingual": {
            "type": "custom",
            "tokenizer": "standard",
            "filter": ["lowercase", "english_stop", "german_stop", "english_stemmer", "german_stemmer"]
          }
        }
      }
    }
  }
}
'

echo "Template created"
