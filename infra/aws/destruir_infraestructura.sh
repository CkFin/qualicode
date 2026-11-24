#!/usr/bin/env bash
# Elimina TODOS los recursos de QualiCode en AWS (al finalizar el curso).
# Uso: bash infra/aws/destruir_infraestructura.sh
set -euo pipefail
export AWS_REGION="${AWS_REGION:-us-east-1}" AWS_PAGER="" MSYS_NO_PATHCONV=1
awsq() { aws "$@" | tr -d '\r'; }

read -r -p "Esto ELIMINA la instancia, sus datos, la IP elastica y el grupo de seguridad. Escriba 'eliminar': " ok
[[ "$ok" == "eliminar" ]] || { echo "Cancelado"; exit 1; }

IDS=$(awsq ec2 describe-instances --filters Name=tag:Name,Values=qualicode-server \
      Name=instance-state-name,Values=pending,running,stopping,stopped \
      --query 'Reservations[].Instances[].InstanceId' --output text)
ALLOC_ID=$(awsq ec2 describe-addresses --filters Name=tag:Name,Values=qualicode-eip --query 'Addresses[0].AllocationId' --output text)

if [[ "$ALLOC_ID" != "None" && -n "$ALLOC_ID" ]]; then
  ASSOC=$(awsq ec2 describe-addresses --allocation-ids "$ALLOC_ID" --query 'Addresses[0].AssociationId' --output text)
  [[ "$ASSOC" != "None" ]] && aws ec2 disassociate-address --association-id "$ASSOC"
  aws ec2 release-address --allocation-id "$ALLOC_ID" && echo "IP elastica liberada"
fi
if [[ -n "$IDS" ]]; then
  aws ec2 terminate-instances --instance-ids $IDS >/dev/null
  echo "Terminando $IDS ..."; aws ec2 wait instance-terminated --instance-ids $IDS
fi
SG_ID=$(awsq ec2 describe-security-groups --filters Name=group-name,Values=qualicode-sg --query 'SecurityGroups[0].GroupId' --output text)
[[ "$SG_ID" != "None" ]] && aws ec2 delete-security-group --group-id "$SG_ID" && echo "Grupo de seguridad eliminado"
aws ec2 delete-key-pair --key-name qualicode-key && echo "Par de llaves eliminado en AWS"
rm -f "$(dirname "$0")/estado.env"
echo "Recursos eliminados."
