#!/usr/bin/env bash
# =====================================================================
#  QualiCode - Aprovisiona la infraestructura IaaS en AWS Academy
#  (EC2 Ubuntu 24.04 + Security Group + IP elastica + par de llaves).
#
#  Requisitos: AWS CLI v2 con las credenciales del Learner Lab en
#  ~/.aws/credentials (ver docs/AWS_ACADEMY.md).
#  Uso (Git Bash):  bash infra/aws/crear_infraestructura.sh
#  Idempotente: si los recursos existen los reutiliza (y arranca la
#  instancia si estaba detenida).
# =====================================================================
set -euo pipefail

export AWS_REGION="${AWS_REGION:-us-east-1}"
export AWS_PAGER=""
export MSYS_NO_PATHCONV=1   # Git Bash: no convertir /dev/sda1 ni /aws/service/... a rutas Windows
NAME=qualicode
INSTANCE_TYPE="${INSTANCE_TYPE:-t3.medium}"
KEY_NAME=qualicode-key
KEY_FILE="$HOME/.ssh/qualicode-key.pem"
STATE_FILE="$(dirname "$0")/estado.env"

awsq() { aws "$@" | tr -d '\r'; }   # aws.exe en Windows devuelve CRLF

echo "==> Identidad AWS"
awsq sts get-caller-identity --query Arn --output text

VPC_ID=$(awsq ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
MY_IP=$(curl -fsS https://checkip.amazonaws.com | tr -d '\r\n')
echo "VPC por defecto: $VPC_ID | Tu IP publica: $MY_IP"

# --------------------------------------------------------- par de llaves
if ! aws ec2 describe-key-pairs --key-names "$KEY_NAME" >/dev/null 2>&1; then
  echo "==> Creando par de llaves $KEY_NAME"
  mkdir -p "$HOME/.ssh"
  awsq ec2 create-key-pair --key-name "$KEY_NAME" --key-type ed25519 \
       --query KeyMaterial --output text > "$KEY_FILE"
  chmod 600 "$KEY_FILE"
  echo "Llave privada guardada en $KEY_FILE (NO se versiona)"
fi

# --------------------------------------------------------- grupo de seguridad
SG_ID=$(awsq ec2 describe-security-groups --filters Name=group-name,Values=${NAME}-sg Name=vpc-id,Values="$VPC_ID" \
        --query 'SecurityGroups[0].GroupId' --output text)
if [[ "$SG_ID" == "None" || -z "$SG_ID" ]]; then
  echo "==> Creando grupo de seguridad ${NAME}-sg"
  SG_ID=$(awsq ec2 create-security-group --group-name ${NAME}-sg --vpc-id "$VPC_ID" \
          --description "QualiCode: SSH solo admin, HTTP publico" --query GroupId --output text)
  awsq ec2 authorize-security-group-ingress --group-id "$SG_ID" --ip-permissions \
       "IpProtocol=tcp,FromPort=80,ToPort=80,IpRanges=[{CidrIp=0.0.0.0/0,Description=HTTP-QualiCode}]" >/dev/null
fi
# SSH solo desde la IP actual del administrador (se agrega si cambio)
aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --ip-permissions \
    "IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=${MY_IP}/32,Description=SSH-admin}]" >/dev/null 2>&1 \
    && echo "SSH permitido desde ${MY_IP}/32" || echo "SSH ya permitido desde ${MY_IP}/32"

# --------------------------------------------------------- instancia EC2
INSTANCE_ID=$(awsq ec2 describe-instances \
  --filters Name=tag:Name,Values=${NAME}-server Name=instance-state-name,Values=pending,running,stopping,stopped \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)

if [[ "$INSTANCE_ID" == "None" || -z "$INSTANCE_ID" ]]; then
  AMI_ID=$(awsq ssm get-parameter \
      --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id \
      --query Parameter.Value --output text 2>/dev/null || true)
  if [[ -z "$AMI_ID" ]]; then
    AMI_ID=$(awsq ec2 describe-images --owners 099720109477 \
      --filters 'Name=name,Values=ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*' Name=state,Values=available \
      --query 'sort_by(Images,&CreationDate)[-1].ImageId' --output text)
  fi
  echo "==> Lanzando EC2 $INSTANCE_TYPE con Ubuntu 24.04 ($AMI_ID)"
  INSTANCE_ID=$(awsq ec2 run-instances --image-id "$AMI_ID" --instance-type "$INSTANCE_TYPE" \
      --key-name "$KEY_NAME" --security-group-ids "$SG_ID" \
      --metadata-options HttpTokens=required,HttpEndpoint=enabled,HttpPutResponseHopLimit=1 \
      --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=20,VolumeType=gp3,Encrypted=true,DeleteOnTermination=true}' \
      --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${NAME}-server},{Key=Proyecto,Value=QualiCode}]" \
      --query 'Instances[0].InstanceId' --output text)
else
  STATE=$(awsq ec2 describe-instances --instance-ids "$INSTANCE_ID" --query 'Reservations[0].Instances[0].State.Name' --output text)
  echo "Instancia existente $INSTANCE_ID ($STATE)"
  [[ "$STATE" == "stopped" ]] && awsq ec2 start-instances --instance-ids "$INSTANCE_ID" >/dev/null
fi
echo "==> Esperando a que $INSTANCE_ID este en ejecucion..."
aws ec2 wait instance-running --instance-ids "$INSTANCE_ID"

# --------------------------------------------------------- IP elastica (IP fija entre sesiones)
ALLOC_ID=$(awsq ec2 describe-addresses --filters Name=tag:Name,Values=${NAME}-eip --query 'Addresses[0].AllocationId' --output text)
if [[ "$ALLOC_ID" == "None" || -z "$ALLOC_ID" ]]; then
  ALLOC_ID=$(awsq ec2 allocate-address --domain vpc \
      --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=${NAME}-eip}]" --query AllocationId --output text)
fi
awsq ec2 associate-address --instance-id "$INSTANCE_ID" --allocation-id "$ALLOC_ID" >/dev/null
PUBLIC_IP=$(awsq ec2 describe-addresses --allocation-ids "$ALLOC_ID" --query 'Addresses[0].PublicIp' --output text)

cat > "$STATE_FILE" <<EOF
AWS_REGION=$AWS_REGION
INSTANCE_ID=$INSTANCE_ID
SG_ID=$SG_ID
ALLOC_ID=$ALLOC_ID
PUBLIC_IP=$PUBLIC_IP
KEY_FILE=$KEY_FILE
EOF

echo
echo "================================================================"
echo " Instancia: $INSTANCE_ID   IP publica: $PUBLIC_IP"
echo " SSH:   ssh -i $KEY_FILE ubuntu@$PUBLIC_IP"
echo " Subir: bash infra/subir_codigo.sh ubuntu@$PUBLIC_IP 22 $KEY_FILE"
echo "================================================================"
