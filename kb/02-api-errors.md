# Troubleshooting API Errors

For API failures, capture the HTTP status code, endpoint, request timestamp, and request ID if one is returned. Retry only transient 429 and 5xx responses with exponential backoff; do not repeatedly retry 4xx validation or authorization errors.

For persistent 500-series errors, send support the request ID and timestamp. Do not include passwords, access tokens, or full payment details in a ticket.
