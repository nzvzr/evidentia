# Platform API Reference

## Authentication
API access requires scoped tokens with least-privilege permissions.

## Rate Limits
Default account limit is 2,000 requests per minute, burstable to 5,000.

## Error Handling
Clients should implement retry with exponential backoff for transient failures.

## Webhooks
Webhook delivery is retried for 24 hours before being marked failed.
