#!/usr/bin/env bash
# Invite someone: creates their account and emails them the invitation (a temporary password, valid 3 days).
# Usage: scripts/invite_user.sh friend@example.com             invite someone new
#        scripts/invite_user.sh friend@example.com --resend    send a fresh temporary password (the first one expired)
# Needs AWS credentials (`aws login`).
set -euo pipefail

email="${1:?usage: scripts/invite_user.sh <email> [--resend]}"
action=()
if [ "${2:-}" = "--resend" ]; then
  action=(--message-action RESEND)
elif [ -n "${2:-}" ]; then
  echo "Unknown option: $2" >&2
  exit 1
fi
if ! [[ "$email" =~ ^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$ ]]; then
  echo "That does not look like an email address: $email" >&2
  exit 1
fi
region="${AWS_REGION:-us-east-2}"
pool="$(aws cloudformation describe-stacks --stack-name DealsWatcher --region "$region" \
  --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" --output text)"

aws cognito-idp admin-create-user --user-pool-id "$pool" --region "$region" --username "$email" ${action[@]+"${action[@]}"} \
  --user-attributes "Name=email,Value=$email" "Name=email_verified,Value=true" \
  --desired-delivery-mediums EMAIL --query 'User.UserStatus' --output text
echo "Invitation sent to $email. They have 3 days to use the temporary password."
