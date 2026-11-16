"""
comun
─────
Código compartido por todas las Lambdas del sistema de gestión académica.
El stack CDK copia esta carpeta dentro del paquete de cada Lambda, de modo
que en ejecución se importa como `from comun import ...`.

  claves.py     Llaves de DynamoDB (Single Table Design) y de Redis
  db.py         Acceso a DynamoDB: lecturas, consultas y transacciones
  cache.py      Abstracción de Redis: cache-aside, sesiones, rate limiting
  http.py       Respuestas, errores y enrutador para API Gateway (proxy)
  seguridad.py  Hash de contraseñas, tokens firmados y autorización por rol
  dominio.py    Reglas compartidas de matrícula: lecturas, permisos e invalidación
"""
