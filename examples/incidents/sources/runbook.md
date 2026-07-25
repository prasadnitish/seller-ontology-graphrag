# Authentication service incident runbook

If authentication errors rise after a feature configuration deployment, disable the new flag,
verify token issuance in two regions, and confirm checkout recovery before closing the incident.

Escalate to Identity Foundations when token issuance fails. Edge Infrastructure owns the feature
flag dependency and must confirm propagation state.
