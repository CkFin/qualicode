# Conectar AWS Academy (Learner Lab) con este equipo

El Learner Lab entrega **credenciales temporales**: una Access Key, una Secret Key y un **Session
Token**. Duran lo mismo que la sesión del laboratorio (unas 4 horas) y **cambian cada vez que se
inicia el lab**, así que los pasos 3 y 4 se repiten en cada sesión.

## 1. Instalar AWS CLI v2 (una sola vez)

En PowerShell:

```powershell
winget install -e --id Amazon.AWSCLI
```

Cierre y vuelva a abrir la terminal y VS Code, y compruebe la instalación con `aws --version`.

## 2. Iniciar el laboratorio

1. En AWS Academy abra **Laboratorio de aprendizaje → Iniciar el Laboratorio de aprendizaje**.
2. Pulse **▶ Start Lab** y espere a que el círculo junto a "AWS" pase de rojo a **verde**.

## 3. Copiar las credenciales

1. Pulse **ℹ AWS Details**.
2. Junto a *AWS CLI*, pulse **Show**. Aparece un bloque como este:

   ```ini
   [default]
   aws_access_key_id=ASIA...
   aws_secret_access_key=...
   aws_session_token=IQoJb3JpZ2luX2VjE...(muy largo)
   ```
3. Cópielo completo.

## 4. Pegarlas en el archivo de credenciales

Abra (o cree) `C:\Users\Jota\.aws\credentials`, **reemplace todo su contenido** por el bloque copiado y
guarde. Por ejemplo:

```powershell
notepad $env:USERPROFILE\.aws\credentials
```

El archivo `C:\Users\Jota\.aws\config` ya contiene `region = us-east-1`, que es la región permitida
del Learner Lab.

> **No comparta las credenciales en mensajes ni en el repositorio.** Basta con que estén en ese archivo:
> la AWS CLI y los scripts de `infra/aws/` las leen desde ahí.

## 5. Verificar

```bash
aws sts get-caller-identity
```

Si responde con un `Arn` que contiene `voclabs`, la conexión funciona.

## Notas del Learner Lab

- Al terminar la sesión (o pulsar **End Lab**) las instancias EC2 **se detienen**, pero no se borran.
  La siguiente vez que pulse Start Lab vuelven a arrancar. La **IP elástica** mantiene la misma
  dirección pública entre sesiones.
- El presupuesto es de **$50**. Una `t3.medium` cuesta unos $0.04 por hora y solo cobra mientras
  está encendida. La IP elástica cobra un poco aunque la instancia esté apagada.
- Al finalizar el curso: `bash infra/aws/destruir_infraestructura.sh`.
- Si la sesión expira a mitad de un comando aparece `ExpiredToken`. Repita los pasos 3 y 4.
