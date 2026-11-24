# QualiCode · Plataforma segura de procesamiento en la nube

Proyecto final de Sistemas Operativos (Semana 16). Es una plataforma para cargar, procesar y almacenar
análisis de calidad de código. Corre sobre **Linux (Ubuntu 24.04)** con **Docker** en **AWS Academy (EC2)**.
**Despliegue actual:** http://98.83.189.88/

> **QualiCode** es una empresa ficticia de aseguramiento de calidad de software. Los desarrolladores
> suben las métricas de sus repositorios (CSV: cobertura de pruebas, complejidad y defectos por módulo) y
> bitácoras de revisión de código (TXT). La plataforma calcula un **informe de calidad por módulo**
> (semáforo según el lenguaje y esfuerzo estimado de pruebas, refactorización y corrección), y un
> revisor QA revisa y **libera** cada informe antes de que el desarrollador pueda descargarlo.

## Arquitectura en una línea

`Internet → [SG AWS: 22 admin, 80] → EC2 Ubuntu (UFW) → proxy nginx :80 → api FastAPI → PostgreSQL (cola + datos) ← worker`

Más detalle en [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md).

| Servicio | Imagen | Función | Usuario | Red | Límite |
|---|---|---|---|---|---|
| `proxy` | nginx-unprivileged 1.27 | Único punto público. Sirve el frontend, reenvía `/api/`, añade cabeceras de seguridad y limita los intentos de login | uid 101 | edge | 128 MiB / 0.25 CPU |
| `api` | python 3.12-slim | Autenticación, roles, carga, consultas, auditoría | uid 10001 `qualicode` | edge + backend | 384 MiB / 0.75 CPU |
| `worker` | python 3.12-slim | Procesa los trabajos en segundo plano | uid 10001 `qualicode` | backend (sin Internet) | 256 MiB / 0.5 CPU |
| `db` | postgres 16-alpine | Usuarios, trabajos (cola), auditoría | postgres | backend | 384 MiB / 0.75 CPU |

## Estructura del repositorio

```
FinalOPERATIVOS/
├── docker-compose.yml        # Orquestación: 4 servicios, 2 redes, 3 volúmenes, límites
├── .env.example              # Plantilla de configuración (el .env real NO se versiona)
├── api/                      # Servicio API (FastAPI)
│   ├── main.py               #   Arranque, logs de acceso, admin inicial
│   ├── manage.py             #   Consola: crear usuarios, cambiar roles
│   ├── security/             #   permissions.py (MATRIZ DE ROLES), passwords, tokens, deps
│   ├── routes/               #   auth.py, jobs.py (aislamiento + regla de negocio), admin.py
│   ├── validation/           #   Política de archivos (tipo, tamaño, firma, esquema)
│   └── storage/              #   Almacenamiento separado por usuario
├── worker/                   # Servicio trabajador (cola PostgreSQL SKIP LOCKED)
│   └── processing/           #   Procesamiento de CSV/TXT
├── common/                   # Código compartido: conexión BD, logs, auditoría
├── proxy/                    # nginx.conf + Dockerfile del proxy
├── db/init/                  # Esquema SQL + usuario de BD con mínimo privilegio
├── frontend/                 # index.html, app.js, style.css
├── dataset/                  # Carga de prueba propia (9 archivos sintéticos)
├── tests/                    # Pruebas funcionales, de carga y de recuperación
├── infra/
│   ├── aws/                  # Crear / destruir EC2, SG, IP elástica (AWS CLI)
│   ├── server/               # hardening.sh, generar_env.sh, deploy.sh
│   └── subir_codigo.sh       # Copia el proyecto al servidor sin secretos
├── docs/                     # Arquitectura (diagrama y decisiones) y despliegue en AWS Academy
└── evidencias/               # Salidas de comandos y resultados de las pruebas en AWS
```

## Despliegue desde cero (AWS Academy)

Requisitos en Windows: Git Bash, [AWS CLI v2](docs/AWS_ACADEMY.md) y credenciales del Learner Lab.

```bash
# 1) En Windows (Git Bash), en la carpeta del proyecto:
bash infra/aws/crear_infraestructura.sh          # EC2 + SG + IP elástica + llave
source infra/aws/estado.env
bash infra/subir_codigo.sh ubuntu@$PUBLIC_IP 22 $KEY_FILE

# 2) En el servidor:
ssh -i ~/.ssh/qualicode-key.pem ubuntu@$PUBLIC_IP
cd /opt/qualicode
sudo bash infra/server/hardening.sh               # actualizaciones, UFW, SSH, fail2ban, sysctl...
sudo bash infra/server/generar_env.sh aws         # secretos aleatorios; imprime la clave de admin
sudo bash infra/server/deploy.sh                  # build + up + verificación
```

Abrir `http://<IP_PUBLICA>/` e ingresar con `admin` y la clave que imprimió `generar_env.sh`.

## Operación diaria

```bash
cd /opt/qualicode
sudo docker compose ps                     # estado de los servicios
sudo docker compose logs -f worker         # logs en vivo
sudo docker stats                          # CPU / memoria frente a los límites
sudo docker compose restart worker         # reiniciar un servicio
sudo docker compose up -d --scale worker=2 # escalar trabajadores
sudo docker compose down                   # detener (los datos quedan en los volúmenes)
sudo docker compose up -d                  # volver a iniciar
```

Después de reiniciar el Learner Lab, la instancia vuelve a arrancar y los contenedores se levantan solos
(`restart: unless-stopped`). Si no arrancan, ejecute `sudo bash infra/server/deploy.sh`.

### Usuarios

```bash
sudo docker compose exec -it api python -m api.manage create-user ana productor
sudo docker compose exec api python -m api.manage set-role ana tecnico
sudo docker compose exec api python -m api.manage list-users
```

También se gestionan desde la pestaña **Usuarios y roles** como administrador.

## Pruebas (en el servidor, sin instalar nada)

```bash
cd /opt/qualicode
ADMIN_PASS='<clave admin>' python3 tests/pruebas_funcionales.py        # 35 pruebas de seguridad y funcionales
ADMIN_PASS='<clave admin>' python3 tests/prueba_carga.py --jobs 40     # rendimiento
sudo ADMIN_PASS='<clave admin>' python3 tests/prueba_recuperacion.py   # reinicios y persistencia
sudo bash tests/monitor_recursos.sh 120                                # muestreo de docker stats
```

Los resultados se guardan en `tests/resultados/`.

## Seguridad: qué nunca se versiona

`.env`, `*.pem` y `infra/aws/estado.env` están en `.gitignore`. Las imágenes Docker no contienen
secretos (`.dockerignore` excluye `.env`). Para comprobarlo:

```bash
git ls-files | grep -E '\.env$|\.pem$' || echo "sin secretos versionados"
```

## Limpieza al terminar el curso

```bash
bash infra/aws/destruir_infraestructura.sh
```
